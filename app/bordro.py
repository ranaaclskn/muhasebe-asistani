"""Çalışan / maaş / bordro soruları: bordrolar + calisanlar tablolarından (kurgusal veri).

Neden ayrı yol? Bu sorular HESAP gerektirir (toplam, ortalama, kişi bazında liste, en yüksek maaş) ve
çoğu zaman bir KİŞİ adı içerir ("Ayşe'ye ekimde ne kadar ödedim?"). RAG bunları cevaplayamıyordu,
model de çalışan adını SQL'e güvenle çeviremez. Burada:
  - soru KODLA tanınır (bordro_kalibi), çalışan adı firmanın KENDİ çalışan listesinde KODLA aranır,
  - veriler SORGULAR'daki hazır sorgularla okunur (Kural 3), firma_id oturumdan gelir (Kural 2),
  - tüm toplam/ortalama Python'da hesaplanır, model çağrılmaz (Kural 1).

Kontrol (proje klasöründen):  python -m app.bordro
"""
import re

from app.config import BUGUN
from app.db import calistir
from app.kayit import donem_tr, tarih_tr, tl
from app.niyet import _SAYILAR, _ay_ekle, _kucuk, _onceki_ay, _soru_ayi

KISI = r"(?:çalışan|personel|eleman|işçi)\w*"
ODEME = r"öde|maaş|ücret|net|brüt|kesinti|kesil|ne kadar|aldı|alıyor|kazan|bordro|para|maliyet"
KIDEM = r"en eski|en kıdemli|en uzun süre|en yeni|en son işe|yeni başla|kaç yıl|ne zamandır|kıdem"
KARSILASTIR = (r"geçen aya göre|önceki aya göre|bir önceki|arttı|azaldı|değiş|fark|artış|düşüş|kıyasla|"
               r"karşılaştır|ay öncesine|aya göre|aylara göre|ayına göre|nazaran")
# İşe alım / işten ayrılış ("son bir senede kaç kişi işe alındı", "bu yıl işe alınanlar kimler")
ISE_ALIM = (r"işe (?:al|gir|başla)\w*|yeni (?:çalışan|personel|eleman|işçi)\w*|istihdam|eleman al\w*|"
            r"personel al\w*|alım yap\w*|işten (?:çık|ayrıl)\w*")
GRUPLA = (r"(?:görev|tür|pozisyon|unvan|meslek|departman|rol)\w*\s+(?:göre|bazında|bazlı)|"
          r"görev görev|her (?:bir )?görev")
_EKLER = {"", "e", "a", "ye", "ya", "i", "ı", "u", "ü", "yi", "yı", "yu", "yü", "in", "ın", "un", "ün",
          "nin", "nın", "nun", "nün", "de", "da", "te", "ta", "den", "dan", "ten", "tan", "le", "la",
          "yle", "yla", "ne", "na", "nde", "nda"}


# ---------- Soruyu tanıma ----------
def _norm(soru):
    """Küçük harf + sık yazım hataları: 'maaç' / 'maas' -> 'maaş', 'ucret' -> 'ücret'.
    (Arayüzde 'toplam maaç' yazılınca soru bordroya gelmemiş, model yıllık vergi özeti vermişti.)"""
    s = _kucuk(soru)
    s = re.sub(r"\bmaa[sç]", "maaş", s)
    return re.sub(r"\bucret", "ücret", s)


def _eslesir(isim, kelime):
    """'ayşe' ~ "ayşe'ye" / 'ayşeye' / 'ayşenin' (Türkçe ek alabilir), ama 'ayşegül' değil."""
    kok = kelime.split("'")[0].split("’")[0]
    return kok == isim or (kok.startswith(isim) and kok[len(isim):] in _EKLER)


def calisan_bul(soru, calisanlar):
    """Sorudaki çalışan(lar): önce ad+soyad, yoksa yalnız ad, yoksa yalnız soyad eşleşmesi."""
    kelimeler = re.findall(r"[a-zçğıöşüâî'’]+", _kucuk(soru))
    def var(isim):
        return any(_eslesir(isim, k) for k in kelimeler)
    adsoyad = [(c, *_kucuk(c["ad_soyad"]).split(maxsplit=1)) for c in calisanlar]
    tam = [c for c, ad, soyad in adsoyad if var(ad) and var(soyad)]
    return tam or [c for c, ad, _ in adsoyad if var(ad)] or [c for c, _, soyad in adsoyad if var(soyad)]


# Görev adlarındaki genel kelimeler tek başına görev saymaz ("elemanlara ödenen" -> Paketleme elemanı DEĞİL)
_GENEL_GOREV = {"genel", "eleman", "uzman", "sorumlu", "temsilci", "operatör", "şef", "lider", "ekip"}


def _gorev_koku(kelime):
    """'operatörü' -> 'operatör', 'sorumlusu' -> 'sorumlu', 'elemanı' -> 'eleman' (iyelik eki atılır)."""
    for ek in ("sı", "si", "su", "sü", "ı", "i", "u", "ü"):
        if kelime.endswith(ek) and len(kelime) - len(ek) >= 3:
            return kelime[: -len(ek)]
    return kelime


def gorev_puanlari(soru, gorevler):
    """Her görev için soruda geçen kelime oranı. 'paketleme elemanlarına' -> {'Paketleme elemanı': 1.0}.
    En az bir AYIRT EDİCİ kelime (paketleme, şoför, depo...) eşleşmeli ve oran >= 0,5 olmalı."""
    kelimeler = re.findall(r"[a-zçğıöşü]+", _kucuk(soru))
    puanlar = {}
    for g in gorevler:
        kokler = [_gorev_koku(k) for k in re.findall(r"[a-zçğıöşü]+", _kucuk(g)) if len(k) >= 3 and k != "ve"]
        eslesen = [k for k in kokler if any(w.startswith(k) for w in kelimeler)]
        if kokler and any(k not in _GENEL_GOREV for k in eslesen) and len(eslesen) / len(kokler) >= 0.5:
            puanlar[g] = len(eslesen) / len(kokler)
    return puanlar


def gorev_bul(soru, gorevler):
    """Soruda geçen görev(ler); en iyi eşleşenler ('üretim şefi' sorulunca üretim operatörü gelmez)."""
    puanlar = gorev_puanlari(soru, gorevler)
    en = max(puanlar.values(), default=0)
    return [g for g, p in puanlar.items() if p == en] if en else []


def _gorevler(firma_id):
    return list(dict.fromkeys(c["gorev"] for c in calistir("calisan_listesi", firma_id)))


def bordro_kalibi(soru, firma_id=None):
    """Çalışan/maaş sorusu mu? Beyannamedeki ÜCRET rakamları da buradan cevaplanır: belge bu tablodan
    üretiliyor ve RAG'da küçük model 'net ücret toplamı' ile 'ortalama net ücret' satırlarını karıştırıyordu.
    Ücretle ilgisiz beyanname soruları ('beyannamede ödenecek muhtasar') RAG'da kalır."""
    s = _norm(soru)
    if "beyan" in s and not re.search(r"ücret|maaş|\bnet\b|brüt|kesinti", s):
        return False
    # "ocaktaki TOPLAM giderler" maaştan fazlasıdır (vergi + maaş + planlı) -> kayit.aylik_gider_cevabi
    if re.search(r"toplam gider|tüm gider|bütün gider|giderler|harcama|masraf|nakit çıkış|para çıkış", s) \
            and not re.search(r"personel|maaş gider|ücret gider|işçilik", s):
        return False
    # "son bir senede kaç kişi işe alındı" firma kartına, "işe alınanlar kimler" kapsam dışına gidiyordu
    if re.search(ISE_ALIM, s):
        return True
    if re.search(r"maaş|bordro|brüt ücret|net ücret|ortalama ücret|ödenen ücret|ücret toplam|"
                 rf"{KISI}\s+(?:\w+\s+)?ücret|ücret\w*\s+(?:gideri|ödeme)", s):
        return True
    if re.search(KISI, s):
        if re.search(ODEME, s) or re.search(r"kimler|liste|isim|adları|kim var|görev|" + KIDEM, s):
            # "kaç çalışan var / çalışan sayısı" firma bilgisidir (ödeme kelimesi yoksa)
            return not (re.search(r"\bkaç\b|sayı", s) and not re.search(ODEME, s))
    if firma_id and re.search(ODEME + r"|görev|ne iş|işe gir|" + KIDEM, s):
        bulunan = calisan_bul(soru, calistir("calisan_listesi", firma_id))
        if bulunan:  # yalnız SOYAD eşleştiyse (Kaya, Demir...) maaş/çalışan kelimesi de şart
            ad_var = any(_eslesir(_kucuk(c["ad_soyad"]).split()[0], k)
                         for c in bulunan for k in re.findall(r"[a-zçğıöşü'’]+", s))
            return ad_var or bool(re.search(r"maaş|ücret|bordro|net|brüt", s))
    # Görev adı TAM geçiyorsa ("paketleme elemanlarına", "şoförlere") + ödeme fiili. Kısmi eşleşme
    # ("depo kirası", "satış faturası") bordro sayılmaz.
    if firma_id and re.search(r"maaş|ücret|bordro|\bnet\b|brüt|kazan|aldı|alıyor|ödenen|ödedi|ödeme yap", s) \
            and not re.search(r"fatura|kira|kdv|vergi", s):
        if 1.0 in gorev_puanlari(soru, _gorevler(firma_id)).values():
            return True
    if re.search(r"(?:görev|pozisyon|unvan|meslek|departman)\w*|eleman türü", s) and re.search(ODEME, s):
        return True
    return False


# ---------- Zaman seçimi ----------
def _secilen_aylar(s, donemler, varsayilan="son"):
    """Sorudaki zamana göre bordro ayları -> (aylar, hata). varsayilan: 'son' (en son ay) | 'hepsi'."""
    m = re.search(r"son (\d{1,2}|" + "|".join(sorted(_SAYILAR, key=len, reverse=True)) + r") ay", s)
    if m:
        n = int(m.group(1)) if m.group(1).isdigit() else _SAYILAR[m.group(1)]
        bitis = min(_onceki_ay(BUGUN[:7]), donemler[-1])
        bas = _ay_ekle(bitis, -(max(n, 1) - 1))
        return [d for d in donemler if bas <= d <= bitis], None
    if re.search(r"bu yıl|bu sene|yıl içinde|yıllık|\b20\d{2} yılı|tüm aylar|her ay|aylık olarak", s):
        yil = re.search(r"\b(20\d{2})\b", s)
        yil = yil.group(1) if yil else BUGUN[:4]
        return [d for d in donemler if d.startswith(yil)], None
    ay = _soru_ayi(s)
    if ay:
        if ay in donemler:
            return [ay], None
        ek = " (maaşlar ay sonunda ödenir)" if ay >= BUGUN[:7] else ""
        return [], (f"{donem_tr(ay)} bordrosu kayıtlarınızda yok{ek}. Bordro kayıtları "
                    f"{donem_tr(donemler[0])} – {donem_tr(donemler[-1])} arası mevcut.")
    return (donemler[-1:] if varsayilan == "son" else list(donemler)), None


def _aralik_adi(aylar):
    return donem_tr(aylar[0]) if len(aylar) == 1 else f"{donem_tr(aylar[0])} – {donem_tr(aylar[-1])}"


def _kesinti_satirlari(r):
    return (f"- SGK işçi payı (%14): {tl(r['sgk_isci_tl'])}\n"
            f"- İşsizlik sigortası işçi payı (%1): {tl(r['issizlik_isci_tl'])}\n"
            f"- Gelir vergisi: {tl(r['gelir_vergisi_tl'])}\n"
            f"- Damga vergisi: {tl(r['damga_vergisi_tl'])}")


def maas_tahmini(firma_id, gorevler=None, calisan_id=None, ay_sayisi=3):
    """Henüz bordrosu olmayan bir ay için maaş tahmini: son N bordro ayının ortalaması.
    Döner: {"net", "brut", "kisi", "aylar", "en_dusuk", "en_yuksek"} ya da None."""
    if calisan_id:
        satirlar = calistir("calisan_bordrosu", firma_id, calisan_id)[-ay_sayisi:]
    else:
        donemler = [t["donem"] for t in calistir("bordro_aylik_toplam", firma_id)][-ay_sayisi:]
        satirlar = [r for d in donemler for r in calistir("ay_bordrosu", firma_id, d)
                    if not gorevler or r["gorev"] in gorevler]
    aylar = sorted({r["donem"] for r in satirlar})
    if not aylar:
        return None
    aylik_net = [sum(r["net_tl"] for r in satirlar if r["donem"] == d) for d in aylar]
    aylik_brut = [sum(r["brut_tl"] for r in satirlar if r["donem"] == d) for d in aylar]
    return {"net": round(sum(aylik_net) / len(aylar), 2), "brut": round(sum(aylik_brut) / len(aylar), 2),
            "kisi": len({r["calisan_id"] for r in satirlar if r["donem"] == aylar[-1]}), "aylar": aylar,
            "en_dusuk": round(min(aylik_net), 2), "en_yuksek": round(max(aylik_net), 2),
            "kisi_net": round(sum(r["net_tl"] for r in satirlar) / len(satirlar), 2),  # kişi başı aylık ort.
            "kisi_brut": round(sum(r["brut_tl"] for r in satirlar) / len(satirlar), 2),
            "kisi_min": round(min(r["net_tl"] for r in satirlar), 2),
            "kisi_max": round(max(r["net_tl"] for r in satirlar), 2)}


def _tekil(s):
    """Soru TEK kişiyi mi soruyor? 'bir şoföre', 'bir çalışana', 'kişi başı', 'her bir'.
    ('bir ayda ödenen toplam maaş' tekil DEĞİL.)"""
    return bool(re.search(r"\bbir (?!ay\b|ayda|aylık|yıl|sene|hafta|gün|kaç)\w+|kişi başı|başına|her bir|tek bir", s))


def _ay_sonu(ay):
    import calendar
    return f"{ay}-{calendar.monthrange(int(ay[:4]), int(ay[5:]))[1]:02d}"


def _gelecek_maas(s, firma_id, ay, gorevler=None, kisi=None):
    """'Aralıkta ödenecek toplam maaş' -> bordro henüz yok: son 3 ayın ortalamasıyla TAHMİN."""
    t = maas_tahmini(firma_id, gorevler, kisi["id"] if kisi else None)
    if not t:
        return _sonuc("Tahmin için geçmiş bordro kaydı yok.", [])
    if not kisi and _tekil(s):  # "bir şoföre verilecek maaş" -> KİŞİ BAŞI tahmin
        rol = f"bir {gorevler[0]}" if gorevler and len(gorevler) == 1 else "bir çalışan"
        return _sonuc(f"{donem_tr(ay)} maaşları henüz ödenmedi; bordro ay sonunda ({tarih_tr(_ay_sonu(ay))}) oluşur. "
                      f"Son {len(t['aylar'])} aya ({_aralik_adi(t['aylar'])}) göre **{rol} için tahmini maaş**:\n\n"
                      f"- Net (eline geçen): yaklaşık **{tl(t['kisi_net'])}**\n"
                      f"- Brüt: yaklaşık {tl(t['kisi_brut'])}\n"
                      f"- Son {len(t['aylar'])} ayda kişi başı net {tl(t['kisi_min'])} – {tl(t['kisi_max'])} arası "
                      f"({t['kisi']} kişi)\n\n_Bu bir tahmindir: fazla mesai, prim ve zamla değişebilir._",
                      [f"bordro:{d}" for d in t["aylar"]])
    kim = (f"**{kisi['ad_soyad']}** ({kisi['gorev']})" if kisi else
           f"**{', '.join(gorevler)}** görevindeki {t['kisi']} çalışan" if gorevler else f"{t['kisi']} çalışan")
    etiket = "Net (eline geçecek)" if kisi else "Net (çalışanlara ödenecek)"
    satirlar = [f"- {etiket}: yaklaşık **{tl(t['net'])}**", f"- Brüt: yaklaşık {tl(t['brut'])}"]
    if not kisi and t["kisi"] > 1:
        satirlar.append(f"- Kişi başı ortalama net: yaklaşık {tl(round(t['net'] / t['kisi'], 2))}")
    if len(t["aylar"]) > 1:
        satirlar.append(f"- Son {len(t['aylar'])} ayda aylık net en düşük {tl(t['en_dusuk'])}, "
                        f"en yüksek {tl(t['en_yuksek'])}")
    return _sonuc(f"{donem_tr(ay)} maaşları henüz ödenmedi; bordro ay sonunda ({tarih_tr(_ay_sonu(ay))}) oluşur. "
                  f"{kim} için son {len(t['aylar'])} ayın ({_aralik_adi(t['aylar'])}) ortalamasına göre "
                  f"**tahmin**:\n\n" + "\n".join(satirlar)
                  + "\n\n_Bu bir tahmindir: fazla mesai, prim, zam ve işe giriş-çıkışlarla değişebilir._",
                  [f"bordro:{d}" for d in t["aylar"]])


def _gelecek_ay(s, donemler):
    """Soru bordrosu henüz olmayan (son bordro ayından SONRAKİ) bir ayı mı soruyor? -> 'YYYY-AA' ya da None."""
    if re.search(r"son \w+ ay|bu yıl|yıllık", s):
        return None
    ay = _soru_ayi(s)
    if not ay and re.search(r"verilecek|ödenecek|alacak\b|alacağı|verece|ödeyece|olacak", s):
        return _ay_ekle(donemler[-1], 1)  # ay yok ama gelecek zaman: sıradaki (henüz ödenmemiş) maaş
    return ay if ay and ay > donemler[-1] else None


def _sonuc(cevap, kaynaklar, satirlar=None):
    return {"cevap": cevap, "kaynaklar": kaynaklar, "satirlar": satirlar or [], "yontem": "bordro"}


# ---------- Cevaplar ----------
def _kisi_cevabi(s, kisi, firma_id):
    satirlar = calistir("calisan_bordrosu", firma_id, kisi["id"])
    gelecek = _gelecek_ay(s, [r["donem"] for r in satirlar]) if satirlar else None
    if gelecek and re.search(ODEME, s):
        return _gelecek_maas(s, firma_id, gelecek, kisi=kisi)
    aylar, hata = _secilen_aylar(s, [r["donem"] for r in satirlar], varsayilan="hepsi")
    if hata:
        return _sonuc(f"{kisi['ad_soyad']}: {hata}", [])
    secilen = [r for r in satirlar if r["donem"] in aylar]
    bilgi = (f"**{kisi['ad_soyad']}** — {kisi['gorev']}, işe giriş {tarih_tr(kisi['ise_giris'])} "
             f"({_sure(kisi['ise_giris'])}).")
    if re.search(r"görev|ne iş|işe gir|ne zaman başla|" + KIDEM, s) and not re.search(ODEME, s):
        return _sonuc(bilgi, [f"calisan:{kisi['id']}"])
    if re.search(KARSILASTIR, s) and len(satirlar) >= 2:  # "Gamze'nin maaşı son 3 aya göre arttı mı"
        ref = aylar[-1] if len(aylar) == 1 else None
        metin, kullanilan = _karsilastir(s, satirlar, f"{kisi['ad_soyad']} maaşı", ref)
        return _sonuc(f"{bilgi}\n\n{metin}", [r["id"] for r in kullanilan], kullanilan)
    kaynaklar = [r["id"] for r in secilen]
    if len(secilen) == 1:
        r = secilen[0]
        return _sonuc(f"{bilgi}\n\n{donem_tr(r['donem'])} maaşı (ödeme {tarih_tr(r['odeme_tarihi'])}):\n\n"
                      f"- Brüt ücret: {tl(r['brut_tl'])}\n{_kesinti_satirlari(r)}\n"
                      f"- **Net ödenen: {tl(r['net_tl'])}**", kaynaklar, secilen)
    net = round(sum(r["net_tl"] for r in secilen), 2)
    brut = round(sum(r["brut_tl"] for r in secilen), 2)
    liste = "\n".join(f"- {donem_tr(r['donem'])}: net {tl(r['net_tl'])} (brüt {tl(r['brut_tl'])})" for r in secilen)
    return _sonuc(f"{bilgi}\n\n{_aralik_adi(aylar)} arasında ödenen maaşlar:\n\n{liste}\n\n"
                  f"**Toplam net: {tl(net)}** (toplam brüt {tl(brut)})", kaynaklar, secilen)


def _sure(ise_giris):
    """İşe girişten bugüne: '2 yıl 9 ay' (bugün = config.BUGUN)."""
    y1, a1, g1 = map(int, ise_giris.split("-"))
    y2, a2, g2 = map(int, BUGUN.split("-"))
    ay = (y2 - y1) * 12 + (a2 - a1) - (g2 < g1)
    if ay < 0:
        return "henüz başlamadı"
    return " ".join(p for p in (f"{ay // 12} yıl" if ay >= 12 else "", f"{ay % 12} ay" if ay % 12 else "") if p) \
        or "1 aydan az"


def _degisim(etiket, ay1, deger1, ay2, deger2):
    fark = round(deger2 - deger1, 2)
    yuzde = f" (%{abs(fark) / deger1 * 100:.1f})".replace(".", ",") if deger1 else ""
    yon = "arttı" if fark > 0 else "azaldı" if fark < 0 else "değişmedi"
    return (f"- {etiket}: {donem_tr(ay1)} {tl(deger1)} → {donem_tr(ay2)} {tl(deger2)}; "
            f"**{tl(abs(fark))} {yon}**{yuzde if fark else ''}")


def _calisan_listesi(firma_id, gorevler=None):
    calisanlar = [c for c in calistir("calisan_listesi", firma_id) if not gorevler or c["gorev"] in gorevler]
    liste = "\n".join(f"- {c['ad_soyad']} — {c['gorev']} (işe giriş {tarih_tr(c['ise_giris'])}, {_sure(c['ise_giris'])})"
                      for c in calisanlar)
    kim = f"{', '.join(gorevler)} görevinde" if gorevler else "Kayıtlı"
    return _sonuc(f"{kim} {len(calisanlar)} çalışanınız var:\n\n{liste}", [f"calisan:{c['id']}" for c in calisanlar],
                  calisanlar)


def _zaman_araligi(s):
    """'son bir senede', 'son 6 ayda', 'bu yıl', 'geçen yıl', '2025 yılında' -> (başlangıç, bitiş, etiket)."""
    sayi = r"(\d{1,2}|" + "|".join(sorted(_SAYILAR, key=len, reverse=True)) + r")"
    y = int(BUGUN[:4])
    sayiya = lambda x: int(x) if x.isdigit() else _SAYILAR[x]  # noqa: E731
    if m := re.search(rf"son {sayi} (?:yıl|sene)", s):
        n = sayiya(m.group(1))
        return f"{y - n}{BUGUN[4:]}", BUGUN, f"Son {n} yılda ({tarih_tr(f'{y - n}{BUGUN[4:]}')} – {tarih_tr(BUGUN)})"
    if m := re.search(rf"son {sayi} ay", s):
        n = sayiya(m.group(1))
        bas = _ay_ekle(BUGUN[:7], -n) + BUGUN[7:]
        return bas, BUGUN, f"Son {n} ayda ({tarih_tr(bas)} – {tarih_tr(BUGUN)})"
    if re.search(r"bu yıl|bu sene", s):
        return f"{y}-01-01", BUGUN, f"{y} yılında"
    if re.search(r"geçen yıl|geçen sene", s):
        return f"{y - 1}-01-01", f"{y - 1}-12-31", f"{y - 1} yılında"
    if m := re.search(r"\b(20\d{2})\b", s):
        return f"{m.group(1)}-01-01", f"{m.group(1)}-12-31", f"{m.group(1)} yılında"
    return None


def _ise_alim_cevabi(s, firma_id, calisanlar):
    """İşe alımlar: kaç kişi, kimler, ve bunların maaşlarının aylık gidere etkisi (son bordro ayı)."""
    if re.search(r"işten (?:çık|ayrıl)", s):
        return _sonuc(f"Kayıtlarda işten ayrılış bilgisi tutulmuyor; şu an kayıtlı {len(calisanlar)} çalışanın "
                      f"tamamı aktif görünüyor. İşten ayrılışlar için muhasebecinize danışabilirsiniz.",
                      ["calisanlar"])
    sirali = sorted(calisanlar, key=lambda c: c["ise_giris"], reverse=True)
    aralik = _zaman_araligi(s)
    if not aralik:  # zaman yok: yıllara göre özet + en son işe girenler
        yillar = {}
        for c in sirali:
            yillar.setdefault(c["ise_giris"][:4], []).append(c)
        ozet = "\n".join(f"- {y}: {len(cs)} kişi" for y, cs in sorted(yillar.items(), reverse=True))
        son3 = "\n".join(f"- {c['ad_soyad']} — {c['gorev']}, {tarih_tr(c['ise_giris'])}" for c in sirali[:3])
        return _sonuc(f"Kayıtlı {len(calisanlar)} çalışanın işe giriş yıllarına göre dağılımı:\n\n{ozet}\n\n"
                      f"En son işe girenler:\n\n{son3}", ["calisanlar"], sirali)
    bas, bit, etiket = aralik
    secilen = [c for c in sirali if bas <= c["ise_giris"] <= bit]
    if not secilen:
        en_son = sirali[0]
        return _sonuc(f"{etiket} işe alınan çalışan **yok**. En son işe giren: {en_son['ad_soyad']} "
                      f"({en_son['gorev']}, {tarih_tr(en_son['ise_giris'])}). Şu an kayıtlı {len(calisanlar)} "
                      f"çalışanınız var.", ["calisanlar"])
    liste = "\n".join(f"- {c['ad_soyad']} — {c['gorev']}, işe giriş {tarih_tr(c['ise_giris'])}" for c in secilen)
    # Gidere etkisi: bu kişilerin son bordro ayındaki maaşları
    son_ay = calistir("bordro_aylik_toplam", firma_id)[-1]
    idler = {c["id"] for c in secilen}
    maas = [r for r in calistir("ay_bordrosu", firma_id, son_ay["donem"]) if r["calisan_id"] in idler]
    etki = ""
    if maas:
        net, brut = round(sum(r["net_tl"] for r in maas), 2), round(sum(r["brut_tl"] for r in maas), 2)
        oran = f"{net / son_ay['net_tl'] * 100:.1f}".replace(".", ",") if son_ay["net_tl"] else ""
        etki = (f"\n\nBu çalışanların {donem_tr(son_ay['donem'])} maaşları: net **{tl(net)}** (brüt {tl(brut)})"
                + (f"; bu, o ayki toplam net maaş giderinin %{oran}'i." if oran else "."))
    return _sonuc(f"{etiket} işe alınan **{len(secilen)} çalışan**:\n\n{liste}{etki}",
                  [f"calisan:{c['id']}" for c in secilen], secilen)


def _kidem_cevabi(s, firma_id):
    """'en eski çalışan', 'en son işe giren 3 kişi', 'en kıdemli 5 çalışan'."""
    calisanlar = sorted(calistir("calisan_listesi", firma_id), key=lambda c: c["ise_giris"])
    yeni = bool(re.search(r"en yeni|en son işe|yeni başla", s))
    if yeni:
        calisanlar = calisanlar[::-1]
    n = re.search(r"\b(\d{1,2})\b", s)
    cogul = re.search(r"(?:çalışan|personel|eleman|işçi)(?:lar|ler)|kişi", s)  # "en eski çalışanım kim" -> 1 kişi
    secilen = calisanlar[:int(n.group(1)) if n else (3 if cogul else 1)]
    baslik = "En son işe giren" if yeni else "En kıdemli"
    liste = "\n".join(f"- {c['ad_soyad']} — {c['gorev']}, işe giriş {tarih_tr(c['ise_giris'])} ({_sure(c['ise_giris'])})"
                      for c in secilen)
    return _sonuc(f"{baslik} {len(secilen)} çalışan:\n\n{liste}", [f"calisan:{c['id']}" for c in secilen], secilen)


def _gorev_ozeti(satirlar, aylar):
    """Görevlere göre: kişi sayısı, toplam net/brüt, kişi başı aylık ortalama net."""
    gruplar = {}
    for r in satirlar:
        g = gruplar.setdefault(r["gorev"], {"kisiler": set(), "net": 0.0, "brut": 0.0, "satir": 0})
        g["kisiler"].add(r["calisan_id"])
        g["net"] += r["net_tl"]
        g["brut"] += r["brut_tl"]
        g["satir"] += 1
    sirali = sorted(gruplar.items(), key=lambda x: -x[1]["net"])
    liste = "\n".join(f"- **{gorev}** ({len(g['kisiler'])} kişi): toplam net {tl(round(g['net'], 2))} "
                      f"(brüt {tl(round(g['brut'], 2))}) · kişi başı ortalama net {tl(round(g['net'] / g['satir'], 2))}"
                      for gorev, g in sirali)
    net = round(sum(g["net"] for g in gruplar.values()), 2)
    brut = round(sum(g["brut"] for g in gruplar.values()), 2)
    kapsam = f"{_aralik_adi(aylar)} " + ("ayında" if len(aylar) == 1 else "arasında")
    return _sonuc(f"{kapsam} görevlere göre ödenen maaşlar:\n\n{liste}\n\n**Genel toplam net: {tl(net)}** "
                  f"(brüt {tl(brut)})", [f"bordro:{d}" for d in aylar], satirlar)


def _gorev_cevabi(s, gorevler, satirlar, aylar):
    """'paketleme elemanlarına geçen ay ödenen maaş' -> o görevdekiler, kişi kişi + toplam."""
    secilen = [r for r in satirlar if r["gorev"] in gorevler]
    ad = ", ".join(gorevler)
    kisi = len({r["calisan_id"] for r in secilen})
    net = round(sum(r["net_tl"] for r in secilen), 2)
    brut = round(sum(r["brut_tl"] for r in secilen), 2)
    if re.search(r"ortalama|kişi başı|kişi başına", s):
        return _sonuc(f"{_aralik_adi(aylar)} {ad} ({kisi} kişi) kişi başı ortalama maaş: net "
                      f"**{tl(round(net / len(secilen), 2))}**, brüt {tl(round(brut / len(secilen), 2))}.",
                      [f"bordro:{d}" for d in aylar], secilen)
    if len(aylar) == 1 and _tekil(s):  # "bir şoföre ne kadar ödendi" -> kişi başı
        en_az, en_cok = min(secilen, key=lambda r: r["net_tl"]), max(secilen, key=lambda r: r["net_tl"])
        ek = (f" ({kisi} kişi: en düşük {tl(en_az['net_tl'])} {en_az['ad_soyad']}, en yüksek {tl(en_cok['net_tl'])} "
              f"{en_cok['ad_soyad']})" if kisi > 1 else f" ({secilen[0]['ad_soyad']})")
        return _sonuc(f"{donem_tr(aylar[0])} ayında bir **{ad}** çalışanına ödenen maaş: ortalama net "
                      f"**{tl(round(net / len(secilen), 2))}**, brüt {tl(round(brut / len(secilen), 2))}{ek}.",
                      [f"bordro:{aylar[0]}"], secilen)
    if len(aylar) == 1:
        if re.search(r"en (?:düşük|az)", s):
            secilen = secilen[::-1]
        liste = "\n".join(f"- {r['ad_soyad']}: net {tl(r['net_tl'])} (brüt {tl(r['brut_tl'])})" for r in secilen)
        return _sonuc(f"{donem_tr(aylar[0])} ayında **{ad}** görevindeki {kisi} çalışana ödenen maaşlar "
                      f"(ödeme {tarih_tr(secilen[0]['odeme_tarihi'])}):\n\n{liste}\n\n"
                      f"**Toplam net: {tl(net)}** (toplam brüt {tl(brut)}; kişi başı ortalama net "
                      f"{tl(round(net / len(secilen), 2))})", [f"bordro:{aylar[0]}"], secilen)
    aylik = "\n".join(f"- {donem_tr(d)}: net {tl(round(sum(r['net_tl'] for r in secilen if r['donem'] == d), 2))}"
                      for d in aylar)
    return _sonuc(f"{_aralik_adi(aylar)} arasında **{ad}** görevindeki {kisi} çalışana ödenen maaşlar:\n\n{aylik}"
                  f"\n\n**Toplam net: {tl(net)}** (toplam brüt {tl(brut)})", [f"bordro:{d}" for d in aylar], secilen)


def _esik(s):
    """'5000 TL üstü', '3.000 tl'den az', '4000 altında' -> (tutar, 'ust'|'alt') ya da None."""
    m = re.search(r"(\d{1,3}(?:\.\d{3})+|\d{3,})(?:,\d+)?\s*(?:tl|lira|₺)?\s*'?(?:den|dan|ten|tan)?\s*"
                  r"(üstü|üzeri|üzerinde|fazla|yukarı|çok|altı|altında|az|aşağı|düşük)", s)
    if not m:
        return None
    return float(m.group(1).replace(".", "")), ("alt" if m.group(2) in ("altı", "altında", "az", "aşağı", "düşük")
                                              else "ust")


def _esik_cevabi(s, esik, satirlar, ay):
    tutar, yon = esik
    alan = "brut_tl" if "brüt" in s else "net_tl"
    secilen = [r for r in satirlar if (r[alan] > tutar if yon == "ust" else r[alan] < tutar)]
    ifade = f"{'brüt' if alan == 'brut_tl' else 'net'} maaşı {tl(tutar)} {'üstünde' if yon == 'ust' else 'altında'}"
    if not secilen:
        return _sonuc(f"{donem_tr(ay)} ayında {ifade} olan çalışan yok.", [f"bordro:{ay}"])
    liste = "\n".join(f"- {r['ad_soyad']} ({r['gorev']}): net {tl(r['net_tl'])} (brüt {tl(r['brut_tl'])})"
                      for r in secilen)
    return _sonuc(f"{donem_tr(ay)} ayında {ifade} olan {len(secilen)} çalışan:\n\n{liste}", [f"bordro:{ay}"], secilen)


def _yonelme(ad):
    """Ay adına yönelme eki (ünlü uyumu): Eylül'e, Ekim'e, Ağustos'a, Kasım'a."""
    son_unlu = next((h for h in reversed(ad.lower()) if h in "aeıioöuü"), "a")
    return f"{ad}'{'e' if son_unlu in 'eiöü' else 'a'}"


def _fark(eski, yeni):
    """'**24.195,56 TL azaldı** (%24,4)'"""
    fark = round(yeni - eski, 2)
    if not fark:
        return "**değişmedi**"
    yuzde = f" (%{abs(fark) / eski * 100:.1f})".replace(".", ",") if eski else ""
    return f"**{tl(abs(fark))} {'arttı' if fark > 0 else 'azaldı'}**{yuzde}"


def _karsilastir(s, satirlar, baslik, ref=None):
    """Maaş karşılaştırması (firma toplamı ya da tek çalışan). satirlar: donem sırasıyla, net_tl/brut_tl.
      - 'geçen aya göre'                -> bir önceki ay
      - 'geçmiş / son 3 aya göre'       -> son ay vs ÖNCEKİ 3 ayın ORTALAMASI (+ ay ay liste)
      - 'son 3 ayda arttı mı'           -> 3 aylık GİDİŞAT (her ay bir öncekine göre)
      - '3 ay öncesine göre'            -> 3 ay önceki ayla
    (Önceden 'geçmiş 3 aya göre' sorusu da yalnız Eylül → Ekim karşılaştırıyordu.)"""
    sayi = r"(\d{1,2}|" + "|".join(sorted(_SAYILAR, key=len, reverse=True)) + r")"
    m = (re.search(rf"(?:geçmiş|son|önceki|evvelki)\s+{sayi}\s+ay", s)
         or re.search(rf"\b{sayi}\s+ay(?:lık| önce)", s))
    n = (int(m.group(1)) if m.group(1).isdigit() else _SAYILAR[m.group(1)]) if m else 1
    donemler = [r["donem"] for r in satirlar]
    i = donemler.index(ref) if ref in donemler else len(satirlar) - 1
    son = satirlar[i]
    if i == 0:
        return f"{donem_tr(son['donem'])} öncesine ait bordro kaydı yok, karşılaştırılamıyor.", [son]
    ay_ay = lambda rs: " · ".join(f"{donem_tr(r['donem'])} {tl(r['net_tl'])}" for r in rs)  # noqa: E731

    if n > 1 and re.search(rf"{sayi}\s+ay önce", s):  # "3 ay öncesine göre": tek bir ayla
        j = max(0, i - n)
        o = satirlar[j]
        return (f"{baslik}, {donem_tr(o['donem'])} → {donem_tr(son['donem'])}:\n\n"
                f"- Net: {tl(o['net_tl'])} → {tl(son['net_tl'])}; {_fark(o['net_tl'], son['net_tl'])}\n"
                f"- Brüt: {tl(o['brut_tl'])} → {tl(son['brut_tl'])}; {_fark(o['brut_tl'], son['brut_tl'])}"), [o, son]

    if n > 1 and re.search(r"göre|ortalama|kıyasla|nazaran|karşı", s):  # son ay vs önceki n ayın ortalaması
        onceki = satirlar[max(0, i - n):i]
        net_ort = round(sum(r["net_tl"] for r in onceki) / len(onceki), 2)
        brut_ort = round(sum(r["brut_tl"] for r in onceki) / len(onceki), 2)
        eksik = f" (yalnızca {len(onceki)} ayın kaydı var)" if len(onceki) < n else ""
        return (f"{baslik} — {donem_tr(son['donem'])}, önceki {len(onceki)} ayın "
                f"({_aralik_adi([r['donem'] for r in onceki])}) ortalamasıyla{eksik}:\n\n"
                f"- Net: {donem_tr(son['donem'])} {tl(son['net_tl'])}, önceki {len(onceki)} ay ortalaması "
                f"{tl(net_ort)} → {_fark(net_ort, son['net_tl'])}\n"
                f"- Brüt: {donem_tr(son['donem'])} {tl(son['brut_tl'])}, önceki {len(onceki)} ay ortalaması "
                f"{tl(brut_ort)} → {_fark(brut_ort, son['brut_tl'])}\n\n"
                f"Ay ay net: {ay_ay(onceki + [son])}"), onceki + [son]

    if n > 1:  # "son 3 ayda arttı mı": gidişat
        pencere = satirlar[max(0, i - n + 1):i + 1]
        satir = [f"- {donem_tr(pencere[0]['donem'])}: net {tl(pencere[0]['net_tl'])}"]
        for a, b in zip(pencere, pencere[1:]):
            satir.append(f"- {donem_tr(b['donem'])}: net {tl(b['net_tl'])} — {_yonelme(donem_tr(a['donem']).split()[0])} "
                         f"göre {_fark(a['net_tl'], b['net_tl'])}")
        return (f"{baslik} — son {len(pencere)} ayın gidişatı:\n\n" + "\n".join(satir) +
                f"\n\nGenel: {donem_tr(pencere[0]['donem'])} → {donem_tr(son['donem'])} net "
                f"{_fark(pencere[0]['net_tl'], son['net_tl'])}"), pencere

    o = satirlar[i - 1]
    ek = f"\n- Çalışan sayısı: {o['kisi']} → {son['kisi']}" if "kisi" in son else ""
    return (f"{baslik}, {donem_tr(o['donem'])} → {donem_tr(son['donem'])}:\n\n"
            f"- Net: {tl(o['net_tl'])} → {tl(son['net_tl'])}; {_fark(o['net_tl'], son['net_tl'])}\n"
            f"- Brüt: {tl(o['brut_tl'])} → {tl(son['brut_tl'])}; {_fark(o['brut_tl'], son['brut_tl'])}{ek}"), [o, son]


def _karsilastirma(s, secilen, toplamlar):
    """Firma toplamı karşılaştırması (bkz. _karsilastir)."""
    metin, kullanilan = _karsilastir(s, toplamlar, "Çalışanlara ödenen maaşlar", secilen[-1]["donem"])
    return _sonuc(metin, [f"bordro:{r['donem']}" for r in kullanilan], kullanilan)


def _maliyet_cevabi(firma_id, secilen):
    """Toplam personel maliyeti = brüt ücret + işveren SGK/işsizlik payı.
    İşveren payı = o dönemin SGK prim tahakkuku (yukumlulukler) − bordrodaki işçi payları."""
    satirlar, kaynaklar, toplam = [], [], 0.0
    for t in secilen:
        sgk = calistir("durum", firma_id, "SGK primi", t["donem"])
        if not sgk:
            continue
        isveren = round(sgk[0]["tutar_tl"] - t["sgk_isci_tl"] - t["issizlik_isci_tl"], 2)
        maliyet = round(t["brut_tl"] + isveren, 2)
        toplam += maliyet
        satirlar.append(f"- {donem_tr(t['donem'])}: brüt {tl(t['brut_tl'])} + işveren payı {tl(isveren)} = "
                        f"**{tl(maliyet)}** (çalışan başına {tl(round(maliyet / t['kisi'], 2))})")
        kaynaklar += [f"bordro:{t['donem']}", sgk[0]["id"]]
    if not satirlar:
        return _sonuc("Bu dönem için SGK tahakkuku olmadığından personel maliyeti hesaplanamadı.", [])
    alt = f"\n\n**Toplam personel maliyeti: {tl(round(toplam, 2))}**" if len(satirlar) > 1 else ""
    return _sonuc("Personel maliyeti (brüt ücret + işveren SGK ve işsizlik payı):\n\n" + "\n".join(satirlar) + alt
                  + "\n\n_İşveren payı = SGK prim tahakkuku − çalışanlardan kesilen SGK ve işsizlik payları._",
                  kaynaklar, secilen)


def _ay_listesi(firma_id, ay, s):
    """Bir ayda kime ne kadar ödendi; 'en yüksek / en düşük N' istenirse yalnız onlar."""
    satirlar = calistir("ay_bordrosu", firma_id, ay)  # en yüksek netten başlar
    n = re.search(r"en (?:yüksek|çok|fazla|düşük|az)\w*\s+(\d{1,2})", s)
    yon = "en düşük" if re.search(r"en (?:düşük|az)", s) else "en yüksek"
    baslik = f"{donem_tr(ay)} ayında çalışanlara ödenen maaşlar"
    if re.search(r"en (?:yüksek|çok|fazla|düşük|az)", s):
        if yon == "en düşük":
            satirlar = satirlar[::-1]
        satirlar = satirlar[:int(n.group(1)) if n else 1]
        baslik = f"{donem_tr(ay)} ayında {yon} {len(satirlar)} maaş"
    if len(satirlar) == 1:
        r = satirlar[0]
        return _sonuc(f"{donem_tr(ay)} ayında {yon} maaş: **{r['ad_soyad']}** ({r['gorev']}) — net "
                      f"**{tl(r['net_tl'])}** (brüt {tl(r['brut_tl'])}).", [r["id"]], satirlar)
    liste = "\n".join(f"- {r['ad_soyad']} ({r['gorev']}): net {tl(r['net_tl'])} (brüt {tl(r['brut_tl'])})"
                      for r in satirlar)
    net = round(sum(r["net_tl"] for r in satirlar), 2)
    brut = round(sum(r["brut_tl"] for r in satirlar), 2)
    return _sonuc(f"{baslik} ({len(satirlar)} kişi, "
                  f"ödeme {tarih_tr(satirlar[0]['odeme_tarihi'])}):\n\n{liste}\n\n"
                  f"**Toplam net: {tl(net)}** (toplam brüt {tl(brut)})",
                  [r["id"] for r in satirlar] if len(satirlar) <= 5 else [f"bordro:{ay}"], satirlar)


def bordro_cevabi(soru, firma_id):
    """Bordro sorusuysa {"cevap", "kaynaklar", "satirlar", "yontem"} döndürür; değilse None."""
    if not bordro_kalibi(soru, firma_id):
        return None
    s = _norm(soru)
    calisanlar = calistir("calisan_listesi", firma_id)
    toplamlar = calistir("bordro_aylik_toplam", firma_id)
    if not calisanlar or not toplamlar:
        return _sonuc("Bordro kaydı bulunamadı; muhasebecinize iletebilirim.", [])
    donemler = [t["donem"] for t in toplamlar]

    # 1) Belirli bir çalışan
    kisiler = calisan_bul(soru, calisanlar)
    if len(kisiler) > 1:
        adlar = ", ".join(c["ad_soyad"] for c in kisiler)
        return _sonuc(f"Birden fazla çalışan eşleşti: {adlar}. Hangisini kastettiğinizi ad ve soyadla yazar mısınız?",
                      [])
    if kisiler:
        return _kisi_cevabi(s, kisiler[0], firma_id)

    gorevler = gorev_bul(soru, list(dict.fromkeys(c["gorev"] for c in calisanlar)))

    # 2) Kıdem: en eski / en son işe giren çalışanlar
    if re.search(KIDEM, s) and not re.search(r"maaş|ücret|\bnet\b|brüt|öde", s):
        return _kidem_cevabi(s, firma_id)
    # 2b) İşe alımlar ("son bir senede kaç kişi işe alındı", "bu yıl işe alınanlar kimler")
    if re.search(ISE_ALIM, s):
        return _ise_alim_cevabi(s, firma_id, calisanlar)

    # 3) Çalışan listesi (ödeme sorulmuyorsa); görev söylendiyse yalnız o görevdekiler
    if re.search(r"kimler|liste|isim|adları|kim var|görev|kim çalışıyor", s) and not re.search(ODEME, s):
        return _calisan_listesi(firma_id, gorevler)

    # Gelecek ay (bordrosu henüz yok): tahmin
    gelecek = _gelecek_ay(s, donemler)
    if gelecek and not re.search(r"maliyet|işveren", s):
        return _gelecek_maas(s, firma_id, gelecek, gorevler=gorevler or None)

    aylar, hata = _secilen_aylar(s, donemler)
    if hata:
        return _sonuc(hata, [])
    secilen = [t for t in toplamlar if t["donem"] in aylar]

    # 4) Personel maliyeti (brüt + işveren payı)
    if re.search(r"maliyet|işveren pay|işveren yük|personel gider|işçilik gider", s):
        return _maliyet_cevabi(firma_id, secilen)

    satirlar = [r for d in aylar for r in calistir("ay_bordrosu", firma_id, d)]
    # 5) Görevlere göre özet ("eleman türlerine göre maaşlar")
    if re.search(GRUPLA, s):
        return _gorev_ozeti(satirlar, aylar)
    # 6) Belirli görev ("paketleme elemanlarına geçen ay ödenen maaş")
    if gorevler:
        return _gorev_cevabi(s, gorevler, satirlar, aylar)
    # 7) Tutar eşiği ("net maaşı 5000 TL üstü olanlar") — tek ay
    esik = _esik(s)
    if esik:
        return _esik_cevabi(s, esik, [r for r in satirlar if r["donem"] == aylar[-1]], aylar[-1])
    # 8) Karşılaştırma ("maaş giderleri geçen aya göre arttı mı")
    if re.search(KARSILASTIR, s):
        return _karsilastirma(s, secilen, toplamlar)

    # 9) Kişi bazında liste / en yüksek-en düşük maaş (tek ay; birden çok ay istendiyse sonuncusu)
    if re.search(r"en (?:yüksek|çok|fazla|düşük|az)|liste|kime|her (?:bir )?(?:çalışan|personel|eleman)|"
                 r"tek tek|kişi kişi|bazında|isim|tutarları|tutarlar|kim ne kadar|bordrosu|bordroyu|bordro\b", s):
        return _ay_listesi(firma_id, aylar[-1], s)

    # 10) Ortalama maaş (çalışan başına)
    if re.search(r"ortalama|kişi başı|çalışan başı|personel başı|kişi başına", s):
        kisi_ay = sum(t["kisi"] for t in secilen)
        net = round(sum(t["net_tl"] for t in secilen) / kisi_ay, 2)
        brut = round(sum(t["brut_tl"] for t in secilen) / kisi_ay, 2)
        kapsam = f"{_aralik_adi(aylar)} " + ("ayında" if len(aylar) == 1 else "arasında")
        return _sonuc(f"{kapsam} çalışan başına ortalama maaş: net **{tl(net)}**, brüt {tl(brut)} "
                      f"({secilen[-1]['kisi']} çalışan).", [f"bordro:{d}" for d in aylar], secilen)

    # 11) Toplam ödenen maaş (+ kesinti dökümü)
    if len(secilen) == 1:
        t = secilen[0]
        return _sonuc(f"{donem_tr(t['donem'])} ayında {t['kisi']} çalışana ödenen maaşlar "
                      f"(ödeme {tarih_tr(t['odeme_tarihi'])}):\n\n- Brüt ücret toplamı: {tl(t['brut_tl'])}\n"
                      f"{_kesinti_satirlari(t)}\n- **Çalışanlara ödenen net toplam: {tl(t['net_tl'])}**",
                      [f"bordro:{t['donem']}"], secilen)
    net = round(sum(t["net_tl"] for t in secilen), 2)
    brut = round(sum(t["brut_tl"] for t in secilen), 2)
    liste = "\n".join(f"- {donem_tr(t['donem'])}: net {tl(t['net_tl'])} (brüt {tl(t['brut_tl'])}, {t['kisi']} çalışan)"
                      for t in secilen)
    return _sonuc(f"{_aralik_adi(aylar)} arasında çalışanlara ödenen maaşlar:\n\n{liste}\n\n"
                  f"**Toplam net: {tl(net)}** (toplam brüt {tl(brut)}; aylık ortalama net "
                  f"{tl(round(net / len(secilen), 2))})", [f"bordro:{d}" for d in aylar], secilen)


def _kontrol():
    for soru in ["ortalama net maaş ne kadar", "bir ayda ödenen toplam maaş miktarı ne kadar",
                 "elemanlara ödenen tutarlar", "ekim ayında kime ne kadar maaş ödendi",
                 "en yüksek maaşı kim alıyor", "en düşük 3 maaş", "son 3 ayda ödenen maaşlar",
                 "çalışanlarım kimler", "Gamze Karaca'ya ne kadar ödedim", "gamzeye eylülde ne kadar maaş ödendi",
                 "Fatma'nın görevi ne", "bu ay maaşlara ne kadar ödedim", "çalışanlardan kesilen SGK ne kadar",
                 "ev satın alma ücreti ne", "firmamızda kaç personel var", "Kaya Market'e ne kadar ödedim"]:
        r = bordro_cevabi(soru, "F001")
        print(f"\n## {soru}\n{r['cevap'] if r else '(bordro sorusu değil)'}")


if __name__ == "__main__":
    _kontrol()
