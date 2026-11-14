"""Niyet sınıflandırma: soru -> {"niyet", "sorgu", "parametreler"}.

Akışın ilk düğümü. Model yalnızca SINIFLANDIRIR ve SORGULAR menüsünden seçim yapar;
SQL yazmaz, firma_id seçmez. Çıktı kodda doğrulanır, geçersizse 1 kez daha denenir.

Kontrol (proje klasöründen):  python -m app.niyet
"""
import csv
import json
import re

from langchain_ollama import ChatOllama
from app.config import BUGUN, CSV_DIR, LLM_MODEL, OLLAMA_URL
from app.db import SORGULAR, TURLER, baglan, tur_normalize
from app.emirler import emir_cikar, emir_kalibi

NIYETLER = ["kayit", "belge", "islem", "kapsam_disi"]
AYLAR = ["ocak", "şubat", "mart", "nisan", "mayıs", "haziran", "temmuz",
         "ağustos", "eylül", "ekim", "kasım", "aralık"]


def _sorgu_menusu():
    satirlar = []
    for ad, s in SORGULAR.items():
        p = ", ".join(s["parametreler"] + [f"[{a}, isteğe bağlı]" for a in s.get("istege_bagli", [])])
        p = p or "parametre yok"
        satirlar.append(f'- "{ad}" ({p}): {s["aciklama"]}')
    return "\n".join(satirlar)


SISTEM = f"""Sen bir muhasebe asistanının soru sınıflandırıcısısın. Bugünün tarihi: {BUGUN} (Kasım 2026).
Kullanıcının sorusunu oku ve YALNIZCA şu JSON'u döndür:
{{"niyet": "...", "sorgu": "..." veya null, "parametreler": [...]}}

NİYETLER:
- "kayit": Kullanıcının kendi ödeme, borç, tutar, tarih, fatura kayıtları (ne kadar, ödendi mi, ne zaman ödedim, gecikmiş var mı).
- "belge": Beyanname içeriği, vergi takvimi, kurallar, kavramlar, "ne olur", "ne zaman verilir" gibi genel bilgi.
- "islem": Bir şey yapılmasını isteme (gönder, ilet, talep oluştur, görüşme ayarla).
- "kapsam_disi": YALNIZCA vergi, prim, beyanname, ödeme, fatura ve muhasebe ile HİÇ ilgisi olmayan sorular
  (hisse/yatırım tavsiyesi, hava durumu, sohbet). Vergi/SGK/KDV geçen bir soru asla kapsam_disi değildir.
Dikkat: "ne zaman ödedim / ödendi mi / ne kadardı" -> kayit (kullanıcının kendi kaydı).
"ne zaman ödenir / ne zaman verilir / ne olur" -> belge (genel kural, takvim).

"kayit" ise "sorgu" şu listeden biri olmalı (başka ad yazma):
{_sorgu_menusu()}
"belge", "islem", "kapsam_disi" için "sorgu": null ve "parametreler": [].

PARAMETRE KURALLARI:
- tur: tam olarak şunlardan biri: {", ".join(f'"{t}"' for t in TURLER)}
- donem ve ay: "YYYY-AA" biçiminde. Yıl söylenirse o yılı kullan; söylenmezse 2026.
  "bu ay" = "2026-11", "geçen ay" = "2026-10".
- Soruda belirli bir dönem ve tür varsa "durum" sorgusunu kullan.
- "bu ay ödenecek KDV" gibi ay + tür sorularında tür, ay_odemeleri/odenenler'e 2. parametre olarak eklenir.
- "ekim ayında ödenen / geçen ay ödediğim" -> "odenenler" (ödenmiş kayıtlar).
- yil: "YYYY" biçiminde. "bu yıl ödediğim / bu yıl yapılan ödemeler" -> "yil_odenenler" ["2026"].
- "son 3 ayda / son 6 ayda ödenen" -> "odeme_araligi" [başlangıç ayı, bitiş ayı]; bitiş = geçen ay (2026-10).
- "kaç çalışan / sektörüm / vergi numaram" -> "firma_bilgisi" [].
- Kullanıcının KENDİ eklediği kayıtlar: "planladığım / eklediğim ödemeler, kira" -> "planli_odemeler";
  "tahsilat / alacak / müşteriden gelecek para" -> "beklenen_tahsilatlar"; "nakit planı / para giriş çıkış"
  -> "nakit_plani". Bunlarda ay isteğe bağlıdır: ay söylenmezse [] (yaklaşanlar), söylenirse ["YYYY-AA"].
"""

# Few-shot örnekleri (test setindeki soruların birebir aynısı DEĞİL)
ORNEKLER = [
    ("Eylül SGK primim ödendi mi?", {"niyet": "kayit", "sorgu": "durum", "parametreler": ["SGK primi", "2026-09"]}),
    ("Haziran muhtasarı ne kadardı?", {"niyet": "kayit", "sorgu": "durum", "parametreler": ["Muhtasar", "2026-06"]}),
    ("2024 Nisan SGK primim ne kadardı?", {"niyet": "kayit", "sorgu": "durum", "parametreler": ["SGK primi", "2024-04"]}),
    ("Temmuz KDV'mi hangi gün ödedim?", {"niyet": "kayit", "sorgu": "durum", "parametreler": ["KDV", "2026-07"]}),
    ("Aralıkta hangi ödemelerim var, toplam ne kadar?", {"niyet": "kayit", "sorgu": "ay_odemeleri", "parametreler": ["2026-12"]}),
    ("Bu ay neleri ödemem gerekiyor?", {"niyet": "kayit", "sorgu": "ay_odemeleri", "parametreler": ["2026-11"]}),
    ("Geçen ay neler ödedim?", {"niyet": "kayit", "sorgu": "odenenler", "parametreler": ["2026-10"]}),
    ("Bu yıl toplam ne kadar ödeme yaptım?", {"niyet": "kayit", "sorgu": "yil_odenenler", "parametreler": ["2026"]}),
    ("2026 yılında ödediğim KDV toplamı nedir?", {"niyet": "kayit", "sorgu": "yil_odenenler", "parametreler": ["2026", "KDV"]}),
    ("Son 6 ayda ne kadar ödeme yaptım?", {"niyet": "kayit", "sorgu": "odeme_araligi", "parametreler": ["2026-05", "2026-10"]}),
    ("Firmamızda kaç çalışan kayıtlı?", {"niyet": "kayit", "sorgu": "firma_bilgisi", "parametreler": []}),
    ("Aralıkta planladığım ödemeler neler?", {"niyet": "kayit", "sorgu": "planli_odemeler", "parametreler": ["2026-12"]}),
    ("Müşterilerden ne kadar tahsilat bekliyorum?", {"niyet": "kayit", "sorgu": "beklenen_tahsilatlar", "parametreler": []}),
    ("Ödemesi geciken bir borcum var mı?", {"niyet": "kayit", "sorgu": "gecikmis", "parametreler": []}),
    ("Sıradaki ödemem ne zaman?", {"niyet": "kayit", "sorgu": "en_yakin", "parametreler": []}),
    ("KDV'leri en son ne zaman ödedim?", {"niyet": "kayit", "sorgu": "odeme_gecmisi", "parametreler": ["KDV"]}),
    ("Ekim ayı faturalarımı göster.", {"niyet": "kayit", "sorgu": "faturalar", "parametreler": ["2026-10"]}),
    ("Eylül KDV beyannamemde ne yazıyordu?", {"niyet": "belge", "sorgu": None, "parametreler": []}),
    ("Muhtasar beyannamesi ne demek?", {"niyet": "belge", "sorgu": None, "parametreler": []}),
    ("KDV'yi geç ödersem ceza var mı?", {"niyet": "belge", "sorgu": None, "parametreler": []}),
    ("Muhtasar beyannamesi en geç ne zaman verilir?", {"niyet": "belge", "sorgu": None, "parametreler": []}),
    ("Son beyannamemi e-postama gönder.", {"niyet": "islem", "sorgu": None, "parametreler": []}),
    ("Muhasebecime belge talebimi ilet.", {"niyet": "islem", "sorgu": None, "parametreler": []}),
    ("Hangi hisseyi alayım?", {"niyet": "kapsam_disi", "sorgu": None, "parametreler": []}),
    ("Yarın hava nasıl olacak?", {"niyet": "kapsam_disi", "sorgu": None, "parametreler": []}),
]


# Örnekler sistem metninin içine yazılır (küçük modelde ayrı sohbet mesajlarından daha iyi çalıştı:
# denemede 10/15 -> 14/15).
SISTEM_ORNEKLI = SISTEM + "\nÖRNEKLER:\n" + "\n".join(
    f"Soru: {s}\nJSON: {json.dumps(c, ensure_ascii=False)}" for s, c in ORNEKLER)


def _mesajlar(soru):
    return [("system", SISTEM_ORNEKLI), ("human", f"Soru: {soru}\nJSON:")]


_LLM = {}


def llm(temperature=0.0):
    if temperature not in _LLM:
        _LLM[temperature] = ChatOllama(model=LLM_MODEL, base_url=OLLAMA_URL, temperature=temperature,
                                       format="json", keep_alive="30m")
    return _LLM[temperature]


# ---------- Doğrulama ve düzeltme ----------
def _donem_normalize(deger):
    """'2026-10' / 'Ekim' / 'Ekim 2026' / '2026/10' -> '2026-10'. Tanınmazsa None."""
    d = str(deger).strip().replace("İ", "i").replace("I", "ı").lower()
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})", d)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{m.group(1)}-{int(m.group(2)):02d}"
    for i, ay in enumerate(AYLAR, 1):
        if ay in d:
            yil = re.search(r"\d{4}", d)
            return f"{yil.group() if yil else '2026'}-{i:02d}"
    return None


def dogrula(cikti):
    """Model çıktısını şemaya göre doğrula/düzelt. Geçersizse ValueError."""
    if not isinstance(cikti, dict) or cikti.get("niyet") not in NIYETLER:
        raise ValueError(f"geçersiz niyet: {cikti!r}")
    niyet = cikti["niyet"]
    if niyet != "kayit":
        return {"niyet": niyet, "sorgu": None, "parametreler": []}

    sorgu = cikti.get("sorgu")
    if sorgu not in SORGULAR:
        raise ValueError(f"geçersiz sorgu: {sorgu!r}")
    adlar = SORGULAR[sorgu]["parametreler"]
    ek = SORGULAR[sorgu].get("istege_bagli", [])
    ham = cikti.get("parametreler") or []
    if not isinstance(ham, list) or not len(adlar) <= len(ham) <= len(adlar) + len(ek):
        raise ValueError(f"{sorgu} için {adlar} bekleniyordu, gelen: {ham!r}")

    # Parametreleri SIRAYA göre değil TÜRÜNE göre yerleştir: küçük model sırayı karıştırabiliyor
    # (ör. odenenler için ["KDV", "2026-10"] yazdı; beklenen ["2026-10", "KDV"]).
    donemler = [d for d in (_donem_normalize(x) for x in ham) if d]
    turler = [t for t in (tur_normalize(x) for x in ham if x) if t]
    yillar = [str(x).strip() for x in ham if re.fullmatch(r"20\d{2}", str(x).strip())]
    temiz = []
    for ad in adlar:
        havuz = {"tur": turler, "yil": yillar}.get(ad, donemler)
        if not havuz:
            raise ValueError(f"geçersiz {ad}: {ham!r}")
        temiz.append(havuz.pop(0))
    # İsteğe bağlı tür: tanınmazsa atılır (hata sayılmaz); kural_duzelt sorudan yeniden bulabilir
    if "tur" in ek and turler:
        temiz.append(turler.pop(0))
    if "ay" in ek and donemler:  # planlı kayıt sorgularında isteğe bağlı ay
        temiz.append(donemler.pop(0))
    return {"niyet": "kayit", "sorgu": sorgu, "parametreler": temiz}


# Bu kelimelerden biri geçen soru muhasebe alanındadır; model "kapsam_disi" dese bile düzeltilir.
ALAN_KELIMELERI = ["vergi", "kdv", "sgk", "prim", "muhtasar", "beyanname", "ödeme", "ödedim", "öder",
                   "fatura", "borç", "matrah", "stopaj", "muhasebe", "ceza", "gecik"]
_TUR_KELIMELERI = [("geçici vergi", "Geçici vergi"), ("kdv", "KDV"), ("muhtasar", "Muhtasar"),
                   ("sgk", "SGK primi"), ("prim", "SGK primi")]


def _kucuk(metin):
    return metin.replace("İ", "i").replace("I", "ı").lower()


def kural_duzelt(soru, sonuc):
    """Küçük modelin bilinen hatalarını KODLA düzelt (LLM yorumlar, kod denetler).
    1) Alan kelimesi geçen soru kapsam dışı olamaz -> belge.
    2) Soruda açıkça ay/yıl veya tür yazıyorsa parametreyi sorudan al (model ayı/yılı karıştırabiliyor)."""
    s = _kucuk(soru)
    # Ücret/maaş tutarları veritabanında YOK, yalnızca MUHSGK beyannamelerinde (brüt ücret) var -> belge.
    # (Aksi hâlde model muhtasar/SGK ödemelerini "ücret" diye sunuyordu.)
    if re.search(r"ücret|maaş|bordro", s) and sonuc["niyet"] != "belge":
        return {"niyet": "belge", "sorgu": None, "parametreler": [],
                "duzeltme": f"ücret/maaş -> belge (model: {sonuc['niyet']})"}
    # Kesin kayıt kalıbı varsa model ne derse desin kayıt sorusudur (T04: model "belge" diyordu)
    kesin = _kesin_kayit(s)
    if kesin and sonuc["niyet"] != "kayit":
        ilk_niyet = sonuc["niyet"]
        aralik = _son_n_ay(s) or (BUGUN[:7], BUGUN[:7])
        bos = {"ay": BUGUN[:7] if "geçen ay" not in s else _onceki_ay(BUGUN[:7]), "donem": "", "tur": "",
               "yil": BUGUN[:4], "baslangic_ay": aralik[0], "bitis_ay": aralik[1]}
        sonuc = {"niyet": "kayit", "sorgu": kesin,
                 "parametreler": [bos[a] for a in SORGULAR[kesin]["parametreler"]]}
        duzeltilmis = kural_duzelt(soru, sonuc)
        duzeltilmis["duzeltme"] = f"niyet {ilk_niyet} -> kayit/{kesin} (kesin kalıp)"
        return duzeltilmis
    if sonuc["niyet"] == "kapsam_disi" and any(k in s for k in ALAN_KELIMELERI):
        return {**sonuc, "niyet": "belge", "duzeltme": "alan kelimesi -> belge"}
    if sonuc["niyet"] != "kayit":
        return sonuc

    ilk = (sonuc["sorgu"], list(sonuc["parametreler"]))
    sorgu, yeni = ilk[0], list(ilk[1])
    bu_ay, gecen_ay = BUGUN[:7], _onceki_ay(BUGUN[:7])

    ay_ifadesi = re.search(r"ayında|ayı içinde|geçen ay|bu ay", s)
    tur_var = any(k in s for k, _ in _TUR_KELIMELERI)
    aralik = _son_n_ay(s)
    planli = _planli_kalibi(s)
    # Kullanıcının kendi eklediği planlı ödeme / tahsilat soruları (ay aşağıda isteğe bağlı eklenir)
    if planli:
        sorgu, yeni = planli, []
    # "kaç kişi çalışıyor / sektörüm ne" -> firma bilgisi (yalnızca oturumdaki firma)
    elif _firma_kalibi(s):
        sorgu, yeni = "firma_bilgisi", []
    # "son 3 ayda ödenen" -> ay aralığını KOD hesaplar (model tek bir ay ya da tüm yıl seçiyordu)
    elif aralik:
        sorgu, yeni = "odeme_araligi", list(aralik)
    # "bu yıl yapılan ödemeler / 2026 yılında ödediğim" -> yıl içinde ödenmiş kayıtlar
    elif _yil_odeme_kalibi(s) and sorgu != "yil_odenenler":
        sorgu, yeni = "yil_odenenler", [BUGUN[:4]]
    # "ekim ayında ödenen / geçen ay ödediğim" -> ödenmiş kayıtlar (ödeme tarihine göre)
    elif re.search(r"ödenen\b|ödedi|ödemiş", s) and ay_ifadesi and sorgu != "odenenler":
        sorgu, yeni = "odenenler", [gecen_ay if "geçen ay" in s else bu_ay]
    # "Ağustos KDV'sini ne zaman ödedim?" DÖNEM sorusudur (ödeme ayı değil) -> durum
    elif (sorgu == "odenenler" and not ay_ifadesi and tur_var
          and any(re.search(rf"\b{ay}", s) for ay in AYLAR)):
        sorgu, yeni = "durum", ["", ""]  # tür ve dönem aşağıda sorudan doldurulur
    # "bu ay ... ödeyeceğim/ödenecek" -> her zaman bu ayın ödenmemişleri
    elif re.search(r"\bbu ay", s) and re.search(r"öde(yece|me|necek)", s) and sorgu != "ay_odemeleri":
        sorgu, yeni = "ay_odemeleri", [bu_ay]

    adlar = SORGULAR[sorgu]["parametreler"]
    ay_no = next((i for i, ay in enumerate(AYLAR, 1) if re.search(rf"\b{ay}", s)), None)
    yil = re.search(r"\b(20\d{2})\b", s)
    tur = next((t for k, t in _TUR_KELIMELERI if k in s), None)
    for i, ad in enumerate(adlar):
        if ad in ("donem", "ay") and ay_no:
            yeni[i] = f"{yil.group(1) if yil else '2026'}-{ay_no:02d}"
        elif ad == "tur" and tur:
            yeni[i] = tur
        elif ad == "yil":  # soruda yıl yazıyorsa o, "geçen yıl" ise bir önceki, yoksa bu yıl
            yeni[i] = yil.group(1) if yil else str(int(BUGUN[:4]) - ("geçen yıl" in s))

    # İsteğe bağlı tür filtresi: soruda TEK ve AÇIK bir tür adı geçiyorsa uygula
    # ("vergi ve prim" gibi genel sorularda filtre yok; çıplak "prim" sayılmaz).
    if "tur" in SORGULAR[sorgu].get("istege_bagli", []):
        acik = {t for k, t in _TUR_KELIMELERI if k != "prim" and k in s}
        yeni = yeni[:len(adlar)] + ([acik.pop()] if len(acik) == 1 else [])
    # İsteğe bağlı ay (planlı kayıtlar): soruda ay ifadesi varsa o ay, yoksa parametre yok = yaklaşanlar
    if "ay" in SORGULAR[sorgu].get("istege_bagli", []):
        ay = _soru_ayi(s)
        yeni = yeni[:len(adlar)] + ([ay] if ay else [])

    if (sorgu, yeni) != ilk:
        return {"niyet": "kayit", "sorgu": sorgu, "parametreler": yeni,
                "duzeltme": f"{ilk[0]}{ilk[1]} -> {sorgu}{yeni}"}
    return sonuc


def _kesin_kayit(s):
    """Kelimelerden kesin anlaşılan kayıt soruları -> sorgu adı; değilse None.
    Beyanname içeriği soruları ("beyannamemde ...") her zaman belge yoluna bırakılır."""
    if "beyan" in s:
        return None
    if _planli_kalibi(s):
        return _planli_kalibi(s)
    if re.search(r"gecik", s) and re.search(r"var mı|ödeme|borç", s):
        return "gecikmis"
    if _firma_kalibi(s):
        return "firma_bilgisi"
    if _son_n_ay(s):
        return "odeme_araligi"
    if _yil_odeme_kalibi(s):
        return "yil_odenenler"
    if re.search(r"ayında|ayı içinde|geçen ay|bu ay", s) and re.search(r"ödenen\b|ödedi|ödemiş", s):
        return "odenenler"
    if re.search(r"\bbu ay", s) and re.search(r"öde(yece|me|necek)", s):
        return "ay_odemeleri"
    ay_var = any(re.search(rf"\b{ay}", s) for ay in AYLAR)
    tur_var = any(k in s for k, _ in _TUR_KELIMELERI)
    # "Ağustos KDV'sini ne zaman ödedim?" de bir dönem kaydı sorusudur (T03)
    if ay_var and tur_var and re.search(r"ne kadar|tutar|ödendi mi|ödedim|ödendi", s):
        return "durum"
    return None


_SAYILAR = {"bir": 1, "iki": 2, "üç": 3, "dört": 4, "beş": 5, "altı": 6, "yedi": 7, "sekiz": 8,
            "dokuz": 9, "on": 10, "on bir": 11, "on iki": 12}


def _ay_ekle(ay, n):
    """'2026-10' + (-2) -> '2026-08'"""
    toplam = int(ay[:4]) * 12 + int(ay[5:7]) - 1 + n
    return f"{toplam // 12}-{toplam % 12 + 1:02d}"


def _son_n_ay(s):
    """'son 3 ayda / son üç ay' + geçmiş zamanlı ödeme -> (başlangıç, bitiş) ayları, yoksa None.
    Son N ay = içinde bulunduğumuz aydan önceki N TAM ay (bugün 2026-11 ise son 3 ay: 2026-08..2026-10)."""
    m = re.search(r"son (\d{1,2}|on iki|on bir|bir|iki|üç|dört|beş|altı|yedi|sekiz|dokuz|on) ay", s)
    if not m or not re.search(r"ödenen|ödedi|ödemiş|yapılan|ödendi|ödeme", s):
        return None
    n = int(m.group(1)) if m.group(1).isdigit() else _SAYILAR[m.group(1)]
    bitis = _onceki_ay(BUGUN[:7])
    return (_ay_ekle(bitis, -(max(n, 1) - 1)), bitis)


def _firma_kalibi(s):
    """Firmanın kendi bilgisi soruluyor mu? (çalışan sayısı, sektör, vergi no, firma türü)"""
    return bool((re.search(r"\bkaç\b", s) and re.search(r"çalış|personel|kişi", s))
                or re.search(r"çalışan sayı|personel sayı|vergi no|vergi numara|sektör|firma türü|şirket türü", s))


def _planli_kalibi(s):
    """Kullanıcının KENDİ eklediği planlı kayıtlar soruluyor mu? -> sorgu adı ya da None.
    Not: 'gelecek ay' bir zaman ifadesidir, 'ödeme gelecek' ise tahsilat; ikisi ayrı tutulur."""
    if re.search(r"nakit|giriş[- ]?çıkış|gelir[- ]?gider", s):
        return "nakit_plani"
    if re.search(r"tahsil|alacağ|alacak\b|alacaklar|para gelecek|ödeme gelecek|gelecek para|"
                 r"müşteri\w* (öde|para|gel)|ödeme alaca", s):
        return "beklenen_tahsilatlar"
    if re.search(r"planl|planladı|eklediğim|kaydettiğim|not ettiğim|girdiğim", s):
        return "planli_odemeler"
    return None


def _soru_ayi(s):
    """Sorudaki ay ifadesi -> 'YYYY-AA' ya da None. 'bu ay', 'geçen ay', 'gelecek ay', ay adı (+yıl)."""
    bu_ay = BUGUN[:7]
    if re.search(r"gelecek ay|önümüzdeki ay|haftaya ay", s):
        return _ay_ekle(bu_ay, 1)
    if "geçen ay" in s:
        return _onceki_ay(bu_ay)
    if re.search(r"\bbu ay", s):
        return bu_ay
    ay_no = next((i for i, a in enumerate(AYLAR, 1) if re.search(rf"\b{a}", s)), None)
    if ay_no:
        yil = re.search(r"\b(20\d{2})\b", s)
        return f"{yil.group(1) if yil else BUGUN[:4]}-{ay_no:02d}"
    return None


def _yil_odeme_kalibi(s):
    """'bu yıl / geçen yıl / 2026 yılında' + geçmiş zamanlı ödeme ('yapılan', 'ödenen', 'ödediğim')."""
    return bool(re.search(r"bu yıl|geçen yıl|yıl içinde|\b20\d{2} yılı", s)
                and re.search(r"ödenen|ödedi|ödemiş|yapılan|ödendi|ödeme yaptı", s))


def _onceki_ay(ay):
    yil, a = int(ay[:4]), int(ay[5:7])
    return f"{yil - 1}-12" if a == 1 else f"{yil}-{a - 1:02d}"


def _niyet_modelden(soru, temperature=0.0, deneme=2, duzelt=True):
    """Soruyu sınıflandır. 2 denemede de geçersizse güvenli varsayılan: belge (RAG çekimser kalabilir)."""
    hata = None
    for _ in range(deneme):
        try:
            yanit = llm(temperature).invoke(_mesajlar(soru)).content
            sonuc = dogrula(json.loads(yanit))
            return kural_duzelt(soru, sonuc) if duzelt else sonuc
        except (json.JSONDecodeError, ValueError) as e:
            hata = e
    varsayilan = {"niyet": "belge", "sorgu": None, "parametreler": [], "hata": str(hata)}
    return kural_duzelt(soru, varsayilan) if duzelt else varsayilan

def niyet_belirle(soru, temperature=0.0, deneme=2, duzelt=True):
    """Niyet (bilgi mi emir mi?) + emir isteminde emir ve alanları.
    Bilgi istemi -> {'niyet': 'kayit'|'belge', 'sorgu', 'parametreler'}
    Emir istemi  -> {'niyet': 'islem', 'emir', 'alanlar', 'eksik', 'eksik_sorusu'}"""
    sonuc = _niyet_modelden(soru, temperature, deneme, duzelt)
    # Emir kipindeki cümle ("... gönder", "... oluştur") model ne derse desin emirdir
    if duzelt and emir_kalibi(soru) and sonuc["niyet"] != "islem":
        sonuc = {"niyet": "islem", "sorgu": None, "parametreler": [],
                 "duzeltme": f"emir kipi -> islem (model: {sonuc['niyet']})"}
    if sonuc["niyet"] == "islem":
        sonuc.update(emir_cikar(soru))  # hangi emir, hangi belge/dönem, eksik ne?
    return sonuc


def baska_firma_adi(soru, firma_id):
    """Soruda başka bir firmanın adı geçiyorsa o unvanı döndür (T12). Model değil, kod kontrol eder."""
    kucuk = soru.replace("İ", "i").replace("I", "ı").lower()
    con = baglan()
    firmalar = con.execute("SELECT id, unvan FROM firmalar").fetchall()
    con.close()
    for f in firmalar:
        if f["id"] == firma_id:
            continue
        # "Demo Yazılım A.Ş." -> "demo yazılım" (ilk iki kelime yeterli)
        kisa = " ".join(f["unvan"].replace("İ", "i").lower().split()[:2])
        if kisa in kucuk:
            return f["unvan"]
    return None


def _kontrol():
    """CLAUDE.md Adım 6 Kontrol: test_seti'nde ≥14/15 niyet doğru."""
    import time
    with open(CSV_DIR / "test_seti.csv", encoding="utf-8") as f:
        testler = list(csv.DictReader(f))
    dogru = 0
    print(f"Model: {LLM_MODEL} | temperature=0 | format=json\n")
    for t in testler:
        bas = time.time()
        sonuc = niyet_belirle(t["soru"])
        sure = time.time() - bas
        ok = sonuc["niyet"] == t["beklenen_niyet"]
        dogru += ok
        ek = f" {sonuc['sorgu']}{sonuc['parametreler']}" if sonuc["sorgu"] else ""
        print(f"{'OK  ' if ok else 'YANLIŞ'} {t['id']} {sure:4.1f}s  beklenen={t['beklenen_niyet']:<11} "
              f"gelen={sonuc['niyet']:<11}{ek}  | {t['soru']}")
        if "duzeltme" in sonuc:
            print(f"       ↳ kod düzeltmesi: {sonuc['duzeltme']}")
        if baska_firma_adi(t["soru"], t["firma_id"]):
            print(f"       ↳ başka firma adı algılandı: {baska_firma_adi(t['soru'], t['firma_id'])}")
    print(f"\nNiyet doğruluğu: {dogru}/{len(testler)}")
    print("SONUÇ:", "Adım 6 Kontrol GEÇTİ ✅" if dogru >= 14 else "Kontrol GEÇMEDİ ❌ (hedef ≥14/15)")


if __name__ == "__main__":
    _kontrol()
