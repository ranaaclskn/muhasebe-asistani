"""Kayıt cevabı: SQL satırları -> Türkçe cevap.

Kural 1 — Rakamlar SQL'den gelir: Toplamı PYTHON hesaplar; model yalnızca verilen sayıları cümleye döker.
Model cevabındaki her tutar/tarih VERİ'de birebir yoksa model cevabı atılır, şablon cevap kullanılır.
Kural 4 — Satır yoksa model çağrılmaz, çekimser cevap verilir.

Kontrol (proje klasöründen):  python -m app.kayit
"""
import re

from langchain_ollama import ChatOllama

from app.emirler import GORUSME_TEKLIFI
from app.config import BUGUN, GECIKME_ZAMMI_AYLIK, GECIKME_ZAMMI_TARIH, LLM_MODEL, OLLAMA_URL
from app.db import calistir, planli_islemler
from app.dogrulama import lexical_score

CEKIMSER = "Bu bilgi kayıtlarınızda yok, muhasebecinize iletebilirim."
_EKLE = " Panelin altındaki “Planlı ödeme ve tahsilatlar” sekmesinden ekleyebilirsiniz."
# Sonuç boşsa "bilgi yok" yerine söylenecek ANLAMLI cevap (boş sonuç da bilgidir):
BOS_SONUC = {
    "gecikmis": "Kayıtlarınıza göre gecikmiş ödemeniz yok.",
    "odenmemisler": "Kayıtlarınıza göre ödenmemiş vergi/prim borcunuz yok.",
    "gec_odenenler": "Kayıtlarınıza göre geç ödenmiş bir ödemeniz yok; tüm ödemeler son ödeme tarihinde "
                     "ya da öncesinde yapılmış.",
    "planli_odemeler": "Bu dönem için eklediğiniz planlı ödeme yok." + _EKLE,
    "beklenen_tahsilatlar": "Bu dönem için eklediğiniz beklenen tahsilat yok." + _EKLE,
    "nakit_plani": "Bu dönem için eklediğiniz planlı ödeme ya da tahsilat yok." + _EKLE,
    # Gelecek ayların yükümlülükleri beyanname verilince oluşur; "bilgi yok" yerine tahmini öner
    "ay_odemeleri": "Sorduğunuz ay için kayıtlarınızda ödenmemiş bir yükümlülük yok (ileri ayların tutarları "
                    "beyanname verilince oluşur). Tahmin için “gelecek ay ne kadar ödeyeceğimi tahmin et” "
                    "diye sorabilirsiniz.",
}
AYLAR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz",
         "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


# ---------- Türkçe biçimlendirme ----------
def tl(tutar):
    """54364.86 -> '54.364,86 TL'"""
    return f"{tutar:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") + " TL"


def tarih_tr(iso):
    """'2026-11-30' -> '30.11.2026'"""
    if not iso:
        return ""
    y, a, g = iso.split("-")
    return f"{g}.{a}.{y}"


def donem_tr(donem):
    """'2026-10' -> 'Ekim 2026'; geçici vergi dönemi ('2026/3 (Tem–Eyl)') olduğu gibi kalır."""
    if re.fullmatch(r"\d{4}-\d{2}", donem or ""):
        y, a = donem.split("-")
        return f"{AYLAR[int(a) - 1]} {y}"
    return donem


def satir_metni(s):
    """Bir SQL satırını modele verilecek tek satırlık VERİ'ye çevir."""
    if "tip" in s:  # fatura
        return (f"- {s['tarih'] and tarih_tr(s['tarih'])} {s['tip']} faturası, {s['karsi_taraf']}: "
                f"{tl(s['tutar_tl'])} (KDV oranı %{int(s['kdv_orani'] * 100)})")
    if "yon" in s:  # kullanıcının eklediği planlı ödeme / tahsilat
        ne = "ödenecek" if s["yon"] == "Gider" else "tahsil edilecek"
        if s["tarih"] < BUGUN:  # tarihi geçmiş: "tahsil edilecek" demek yanlış; durumu tabloda yok
            fiil = "ödendi" if s["yon"] == "Gider" else "tahsil edildi"
            ne = f"{ne}ti — tarihi geçti, {fiil} mi kontrol edin"
        karsi = f" ({s['karsi_taraf']})" if s.get("karsi_taraf") else ""
        return f"- {tarih_tr(s['tarih'])} · {s['aciklama']}{karsi}: {tl(s['tutar_tl'])} {ne}"
    metin = (f"- {s['tur']}, {donem_tr(s['donem'])} dönemi: {tl(s['tutar_tl'])}, "
             f"son ödeme tarihi {tarih_tr(s['son_odeme_tarihi'])}, durum: {s['durum']}")
    if s.get("odeme_tarihi"):
        metin += f", ödeme tarihi {tarih_tr(s['odeme_tarihi'])}"
    return metin


def veri_hazirla(sorgu, satirlar):
    """VERİ metni + Python'da hesaplanan toplam."""
    satirlar_metin = [satir_metni(s) for s in satirlar]
    toplam = None
    # Faturalar burada YOK: alış (gider) ve satış (gelir) toplanırsa anlamsız bir rakam çıkar;
    # onların ayrı toplamları sablon_cevap'ta hesaplanır.
    if (sorgu in ("ay_odemeleri", "odenmemisler", "odenenler", "yil_odenenler", "odeme_araligi", "gecikmis", "yaklasanlar",
                  "planli_odemeler", "beklenen_tahsilatlar")
            and len(satirlar) > 1):
        toplam = round(sum(s["tutar_tl"] for s in satirlar), 2)
        satirlar_metin.append(f"TOPLAM ({len(satirlar)} kayıt): {tl(toplam)}")
    return "\n".join(satirlar_metin), toplam


def firma_cevabi(f):
    return (f"{f['unvan']}: {f['firma_turu']}, {f['sektor']} sektörü, "
            f"kayıtlı çalışan sayısı {f['calisan_sayisi']}, vergi no {f['vergi_no']}.")


def _donem_basligi(sorgu, parametreler):
    """Listenin hangi dönemi kapsadığını başlığa yaz ('Ağustos–Ekim 2026'da'): kullanıcı neye
    baktığını görsün (önceden 'son üç ay' sorusuna yalnız Ağustos geliyor ve bu fark edilmiyordu)."""
    p = parametreler or []
    if sorgu in ("ay_odemeleri", "odenenler", "faturalar") and p:
        return f"{donem_tr(p[0])} için "
    if sorgu in ("planli_odemeler", "beklenen_tahsilatlar", "nakit_plani"):
        return f"{donem_tr(p[0])} için " if p else "Önümüzdeki dönemde "
    if sorgu == "yil_odenenler" and p:
        return f"{p[0]} yılında "
    if sorgu == "odeme_araligi" and len(p) >= 2:
        bas, bit = donem_tr(p[0]), donem_tr(p[1])
        if bas.split()[-1] == bit.split()[-1]:  # aynı yıl: "Ağustos–Ekim 2026"
            bas = bas.split()[0]
        return f"{bas}–{bit} arasında "
    return ""


def sablon_cevap(sorgu, satirlar, toplam, parametreler=None):
    """Modelsiz, her zaman doğru cevap (model cevabı doğrulamadan geçemezse kullanılır)."""
    if sorgu == "firma_bilgisi":
        return firma_cevabi(satirlar[0])
    if sorgu == "durum" and len(satirlar) == 1:
        s = satirlar[0]
        if s["durum"] == "Ödendi":
            return (f"{donem_tr(s['donem'])} {s['tur']}: {tl(s['tutar_tl'])}, "
                    f"{tarih_tr(s['odeme_tarihi'])} tarihinde ödendi.")
        return (f"{donem_tr(s['donem'])} {s['tur']}: {tl(s['tutar_tl'])}, durum: {s['durum']}, "
                f"son ödeme tarihi {tarih_tr(s['son_odeme_tarihi'])}.")
    if sorgu == "siradaki_tur":
        s = satirlar[0]
        if s["durum"] == "Gecikti":
            return (f"**Ödenmedi.** {s['tur']} ({donem_tr(s['donem'])} dönemi, {tl(s['tutar_tl'])}) için son ödeme tarihi "
                    f"**{tarih_tr(s['son_odeme_tarihi'])}** idi; bu tarih geçti, gecikme zammı işliyor. "
                    f"Tutarı için “gecikmiş ödemelerimin faizi ne kadar?” diye sorabilirsiniz.")
        return (f"Henüz ödenmedi: {s['tur']} ({donem_tr(s['donem'])} dönemi) için en geç "
                f"**{tarih_tr(s['son_odeme_tarihi'])}** tarihinde ödemelisiniz; tutar {tl(s['tutar_tl'])}.")
    if sorgu == "en_yakin":
        s = satirlar[0]
        return (f"En yakın ödeme: {s['tur']} ({donem_tr(s['donem'])}), {tl(s['tutar_tl'])}, "
                f"son ödeme tarihi {tarih_tr(s['son_odeme_tarihi'])}.")
    # Birden fazla kayıt: okunaklı olsun diye ALT ALTA liste (Markdown; Streamlit madde olarak çizer)
    n = len(satirlar)
    gecikmis = sum(s.get("durum") == "Gecikti" for s in satirlar)  # son tarihi BUGÜNDEN önce, ödenmemiş
    baslik = {"gecikmis": "Gecikmiş ödemeniz var:",
              "ay_odemeleri": f"{n} ödeme bekliyor" + (f" ({gecikmis} tanesinin son ödeme tarihi geçti, "
                                                       f"gecikmiş)" if gecikmis else "") + ":",
              "odenmemisler": f"Ödenmemiş {n} vergi/prim kaydınız var" + (f" ({gecikmis} tanesinin son ödeme "
                                                                         f"tarihi geçti, gecikmiş)" if gecikmis else "") + ":",
              "odenenler": f"{n} ödeme yapılmış:",
              "yil_odenenler": f"{n} ödeme yapılmış (türe göre özet):",
              "odeme_araligi": f"{n} ödeme yapılmış (türe göre özet):",
              "odeme_gecmisi": "Son ödemeleriniz:",
              "yaklasanlar": f"Sıradaki {n} ödemeniz:",
              "gec_odenenler": f"{n} ödeme son tarihinden sonra (geç) yapılmış:",
              "faturalar": f"{n} fatura:",
              "planli_odemeler": f"{n} planlı ödemeniz var (sizin eklediğiniz kayıtlar):",
              "beklenen_tahsilatlar": f"{n} tahsilat bekleniyor (sizin eklediğiniz kayıtlar):",
              "nakit_plani": f"{n} planlı giriş/çıkış var (sizin eklediğiniz kayıtlar):"}.get(sorgu, "Kayıtlarınız:")
    baslik = _donem_basligi(sorgu, parametreler) + baslik
    baslik = baslik[0].upper() + baslik[1:]
    if sorgu == "odeme_gecmisi":  # "en son ne zaman ödedim" -> asıl cevap ilk satırda, liste altta
        s0 = satirlar[0]
        baslik = (f"En son {s0['tur']} ödemeniz **{tarih_tr(s0['odeme_tarihi'])}** tarihinde yapıldı "
                  f"({donem_tr(s0['donem'])} dönemi, {tl(s0['tutar_tl'])}).\n\n{baslik}")
    # "5 ödeme göster" ama yaklaşan yalnızca 4 kayıt var -> eksik geldiğini AÇIKÇA söyle
    if sorgu == "yaklasanlar" and parametreler and int(parametreler[0]) > n:
        baslik = f"{parametreler[0]} ödeme istediniz; kayıtlarda yaklaşan yalnızca {n} ödeme var:"
    if sorgu in ("yil_odenenler", "odeme_araligi"):  # çok kayıt olur -> türe göre grupla
        gruplar = {}
        for s in satirlar:
            g = gruplar.setdefault(s["tur"], [0, 0.0])
            g[0] += 1
            g[1] += s["tutar_tl"]
        maddeler = [f"- **{tur}**: {tl(round(t, 2))} ({n} ödeme)" for tur, (n, t) in gruplar.items()]
    else:
        maddeler = [satir_metni(s) for s in satirlar]  # satir_metni zaten "- " ile başlıyor
    metin = baslik + "\n\n" + "\n".join(maddeler)
    if sorgu == "faturalar":  # alış ve satış AYRI toplanır
        for tip in ("Alış", "Satış"):
            secili = [s for s in satirlar if s["tip"] == tip]
            if secili:
                metin += f"\n\n**{tip} toplamı: {tl(round(sum(s['tutar_tl'] for s in secili), 2))}** ({len(secili)} fatura)"
    elif sorgu == "nakit_plani":  # giriş ve çıkış AYRI, sonra net (Python hesaplar)
        giris = round(sum(s["tutar_tl"] for s in satirlar if s["yon"] == "Gelir"), 2)
        cikis = round(sum(s["tutar_tl"] for s in satirlar if s["yon"] == "Gider"), 2)
        net = round(giris - cikis, 2)
        metin += (f"\n\n**Beklenen giriş: {tl(giris)}** · **Planlı çıkış: {tl(cikis)}** · "
                  f"**Net: {'+' if net >= 0 else '−'}{tl(abs(net))}**")
    elif sorgu in ("ay_odemeleri", "odenmemisler") and gecikmis and toplam is not None:
        # Gecikmiş borç "gelecek ödeme" değildir: ayrı göster, ay toplamı da kalsın
        gec = round(sum(s["tutar_tl"] for s in satirlar if s["durum"] == "Gecikti"), 2)
        metin += (f"\n\n**Gelecek ödemeler: {tl(round(toplam - gec, 2))}** · "
                  f"**Gecikmiş: {tl(gec)}** (gecikme zammı işliyor) · "
                  f"**{'Ay toplamı' if sorgu == 'ay_odemeleri' else 'Toplam borç'}: {tl(toplam)}**")
    elif toplam is not None:
        metin += f"\n\n**Toplam: {tl(toplam)}**"
    return metin


# ---------- Model ----------
SISTEM = """Sen Türkçe konuşan bir muhasebe asistanısın. Kullanıcı bir firma sahibidir.
Aşağıdaki VERİ, kullanıcının kendi kayıtlarından gelir ve kesin doğrudur.
Kullanıcının sorusunu YALNIZCA VERİ'yi kullanarak 1-2 kısa cümleyle cevapla.
- Tutarları ve tarihleri VERİ'de yazdığı gibi AYNEN yaz (ör. 54.364,86 TL, 30.11.2026).
- Hesap yapma, yeni sayı üretme. TOPLAM satırı varsa toplamı oradan al.
- VERİ dışında bilgi ekleme, tavsiye verme."""

_LLM = None


def llm():
    global _LLM
    if _LLM is None:
        _LLM = ChatOllama(model=LLM_MODEL, base_url=OLLAMA_URL, temperature=0, keep_alive="30m")
    return _LLM


SAYI_DESENI = re.compile(r"\d{1,3}(?:\.\d{3})*,\d{2}|\d{2}\.\d{2}\.\d{4}")


def cevap_dogrula(cevap, veri, satirlar, toplam=None):
    """Model cevabını VERİ'ye karşı denetle:
    1) Cevaptaki her tutar/tarih VERİ'de birebir geçmeli (uydurma sayı yok).
    2) Ana rakam cevapta olmalı: toplam varsa toplam, tek kayıtsa o kaydın tutarı.
    3) Hiçbir kayıt ödenmemişken cevap 'ödendi' dememeli (durum çelişkisi).
    4) VERİ'de olmayan bir KAVRAM uydurulmamalı: "gecikmiş ödemelerimin faizi" sorusunda model ana borcu
       (54.938,65 TL) "faiz" diye sunmuştu; rakam doğru, etiket uydurma."""
    sayilar = SAYI_DESENI.findall(cevap)
    uydurma = [s for s in sayilar if s not in veri]
    ana = toplam if toplam is not None else (satirlar[0]["tutar_tl"] if len(satirlar) == 1 else None)
    if ana is not None and tl(ana).replace(" TL", "") not in cevap:
        uydurma.append(f"ana rakam eksik ({tl(ana)})")
    kucuk = cevap.lower()
    odenmemis = all(s.get("durum", "Ödendi") != "Ödendi" for s in satirlar)
    celiski = (odenmemis and re.search(r"ödendi|ödediniz|ödenmiş", kucuk)
               and not re.search(r"ödenmedi|ödenmemiş|bekliyor|gecik", kucuk))
    veri_kucuk = veri.lower()
    kavram = [k for k in KAVRAMLAR if re.search(k, kucuk) and not re.search(k, veri_kucuk)]
    return {"gecerli": bool(sayilar) and not uydurma and not celiski and not kavram,
            "uydurma": uydurma + (["durum çelişkisi"] if celiski else []) + [f"uydurma kavram: {k}" for k in kavram]}


# Kayıt cevabında yalnızca VERİ'de geçiyorsa kullanılabilecek kavramlar
KAVRAMLAR = [r"faiz", r"ceza", r"gecikme zamm", r"\bzam\b", r"indirim", r"iade", r"taksit", r"kredi"]


def gecikme_zammi(tutar, gun, aylik_oran=None):
    """Vergi borcu için TAHMİNİ gecikme zammı (6183 s. Kanun md. 51): her gecikme günü için aylık oranın
    1/30'u. 54.938,65 TL, 4 gün, %3,7 -> 271,03 TL. Oran .env'deki GECIKME_ZAMMI_AYLIK'tan gelir (uydurulmaz)."""
    oran = GECIKME_ZAMMI_AYLIK if aylik_oran is None else aylik_oran
    return round(tutar * oran / 100 / 30 * max(gun, 0), 2)


def gecikme_orani_cevabi(firma_id=None):
    """'Gecikme zammı oranı nedir / nasıl hesaplanır?' -> config'teki resmî oran + yöntem + örnek.
    Oran belgelerde yok; uydurulmaz, .env'deki GECIKME_ZAMMI_AYLIK kullanılır (rakamı Python hesaplar)."""
    yuzde = lambda x: f"%{x:.4g}".replace(".", ",")  # noqa: E731  3.7 -> %3,7 ; 0.12333 -> %0,1233
    gunluk = GECIKME_ZAMMI_AYLIK / 30
    ornek = gecikme_zammi(10000, 30)
    metin = (f"**Gecikme zammı oranı aylık {yuzde(GECIKME_ZAMMI_AYLIK)}** (6183 sayılı Kanun md. 51; "
             f"{GECIKME_ZAMMI_TARIH} tarihinden beri geçerli). Vergi Usul Kanunu'ndaki gecikme faizi de aynı "
             "orandadır.\n\n"
             "**Nasıl hesaplanır:** Son ödeme tarihini izleyen günden ödeme gününe kadar her ay için aylık oran "
             f"uygulanır; ay kesirlerinde günlük oran = aylık oran / 30 = **{yuzde(gunluk)}**.\n\n"
             f"Örnek: 10.000 TL vergi borcu 30 gün gecikirse gecikme zammı {tl(ornek)} olur; ödenecek toplam "
             f"{tl(10000 + ornek)}.\n\n"
             "**SGK primleri:** Geciken prime gecikme cezası ve gecikme zammı birlikte uygulanır; tutarı SGK kendi "
             "yöntemiyle hesaplar.\n\n"
             "Oran Cumhurbaşkanı kararıyla değişebilir; güncelliğini muhasebecinize teyit ettirebilirsiniz. "
             "Kendi geciken borcunuzun tutarı için “gecikmiş ödemelerimin faizi ne kadar?” diye sorabilirsiniz.")
    return {"cevap": metin, "kaynaklar": [f"6183 md.51 (oran: {yuzde(GECIKME_ZAMMI_AYLIK)}/ay)"], "satirlar": [],
            "yontem": "gecikme_orani"}


def gecikme_faizi_cevabi(firma_id, ay=None, tur=None):
    """'Gecikmiş ödemelerimin faizi ne kadar?' / 'faizleriyle toplam ödenecek tutar' -> gecikmiş borçlar,
    kaç gündür gecikmiş, BUGÜNE kadarki TAHMİNİ gecikme zammı ve toplam (hepsini Python hesaplar).
    - Vergi kalemleri: ana borç × aylık oran/30 × gün (oran config'ten; cevapta açıkça yazılır).
    - SGK primi: gecikme cezası + zammı farklı yöntemle hesaplanır -> tahmin VERİLMEZ, SGK hesaplar.
    Ana borç asla 'faiz' diye sunulmaz."""
    from datetime import date
    bugun = date.fromisoformat(BUGUN)
    satirlar = [s for s in calistir("gecikmis", firma_id)
                if (not ay or s["son_odeme_tarihi"][:7] == ay) and (not tur or s["tur"] == tur)]
    kapsam = f"{donem_tr(ay)} içinde son tarihi geçmiş" if ay else "Son ödeme tarihi geçmiş"
    if not satirlar:
        return {"cevap": f"{kapsam} ödenmemiş borcunuz yok; bu yüzden gecikme faizi / zammı da doğmaz.",
                "kaynaklar": [], "satirlar": [], "yontem": "gecikme_faizi"}
    oran_tr = f"%{GECIKME_ZAMMI_AYLIK:g}".replace(".", ",")
    maddeler, zam_toplam, sgk_var = [], 0.0, False
    for s in satirlar:
        gun = (bugun - date.fromisoformat(s["son_odeme_tarihi"])).days
        bas = (f"- **{s['tur']}** ({donem_tr(s['donem'])} dönemi): ana borç **{tl(s['tutar_tl'])}**, son ödeme "
               f"{tarih_tr(s['son_odeme_tarihi'])} — {gun} gündür gecikmiş")
        if s["tur"] == "SGK primi":
            sgk_var = True
            maddeler.append(bas + "\n  - Gecikme cezası ve zammı: SGK hesaplar (aşağıdaki nota bakın)")
        else:
            zam = gecikme_zammi(s["tutar_tl"], gun)
            zam_toplam += zam
            maddeler.append(bas + f"\n  - Tahmini gecikme zammı: **{tl(zam)}** → bugün ödenirse yaklaşık "
                                  f"**{tl(round(s['tutar_tl'] + zam, 2))}**")
    ana = round(sum(s["tutar_tl"] for s in satirlar), 2)
    zam_toplam = round(zam_toplam, 2)
    metin = f"{kapsam} {len(satirlar)} ödemeniz var:\n\n" + "\n".join(maddeler) + "\n\n"
    if zam_toplam:
        metin += (f"**Toplam:** ana borç {tl(ana)} + tahmini gecikme zammı {tl(zam_toplam)} = "
                  f"**{tl(round(ana + zam_toplam, 2))}**" + (" (SGK priminin cezası/zammı hariç)" if sgk_var else "")
                  + "\n\n")
    elif len(satirlar) > 1:
        metin += f"Toplam ana borç: **{tl(ana)}**\n\n"
    metin += ("**Nasıl hesaplandı:** Gecikme zammı aylık " + oran_tr + " (6183 sayılı Kanun md. 51), son ödeme "
              "tarihinden sonraki her gün için bu oranın 1/30'u. Rakam **tahminidir** ve bugüne kadarki tutardır; "
              "ödeme günü ilerledikçe artar. Ana borç faiz değildir, zam onun üstüne eklenir.")
    if sgk_var:
        metin += ("\n\n**SGK primi:** Geciken prime gecikme cezası ve gecikme zammı birlikte uygulanır ve SGK kendi "
                  "yöntemiyle hesaplar; bu tutar kayıtlarınızda yok, tahmin vermiyorum.")
    metin += f"\n\nKesin tutar için muhasebecinize danışın; isterseniz bir {GORUSME_TEKLIFI}."
    return {"cevap": metin, "kaynaklar": [s["id"] for s in satirlar] + ["6183 md.51 (oran: " + oran_tr + "/ay)"],
            "satirlar": satirlar, "yontem": "gecikme_faizi"}


def bugun_odersem_cevabi(firma_id, tur=None):
    """'Geçici vergiyi bugün ödersem toplam ne kadar öderim?' Gecikmişse ana borç + tahmini zam
    (gecikme_faizi_cevabi); gecikmemişse zam yoktur, ödenecek tutar ana borçtur."""
    if calistir("gecikmis", firma_id) and (not tur or any(s["tur"] == tur for s in calistir("gecikmis", firma_id))):
        return gecikme_faizi_cevabi(firma_id, tur=tur)
    if not tur:
        return {"cevap": "Gecikmiş borcunuz yok; bugün öderseniz gecikme zammı eklenmez, kayıttaki tutarı ödersiniz. "
                         "Hangi ödemeyi sorduğunuzu yazarsanız (ör. KDV) tutarını söyleyebilirim.",
                "kaynaklar": [], "satirlar": [], "yontem": "bugun_odersem"}
    s = calistir("siradaki_tur", firma_id, tur)
    if not s:
        return {"cevap": f"Ödenmemiş {tur} kaydınız yok.", "kaynaklar": [], "satirlar": [], "yontem": "bugun_odersem"}
    s = s[0]
    return {"cevap": f"{s['tur']} ({donem_tr(s['donem'])} dönemi) henüz gecikmedi, son ödeme tarihi "
                     f"{tarih_tr(s['son_odeme_tarihi'])}. Bugün öderseniz gecikme zammı yoktur; ödeyeceğiniz tutar "
                     f"**{tl(s['tutar_tl'])}**.",
            "kaynaklar": [s["id"]], "satirlar": [s], "yontem": "bugun_odersem"}


def planli_aciklama_cevabi(soru, firma_id, esik=0.6):
    """Kullanıcının KENDİ eklediği kayıtlarda açıklamaya göre ara ('ev satın alma ücreti ne' ->
    'Ev satın alma ücreti' kaydı). Sorunun anahtar kelimelerinin çoğu açıklamada geçmeli.
    Eşleşme yoksa None (akış belge aramasına devam eder). Rakam SQL'den, model çağrılmaz."""
    eslesen = [r for r in planli_islemler(firma_id) if lexical_score(soru, r["aciklama"]) >= esik]
    if not eslesen:
        return None
    metin = "Eklediğiniz kayıtlarda bulduklarım:\n\n" + "\n".join(satir_metni(r) for r in eslesen)
    return {"cevap": metin, "kaynaklar": [f"plan#{r['id']}" for r in eslesen], "satirlar": eslesen,
            "yontem": "aciklama_arama"}


AYLIK_TURLER = ["KDV", "Muhtasar", "SGK primi"]  # her ay ödenenler (geçici vergi 3 ayda bir)


def tahmin_cevabi(firma_id, ay, tur=None):
    """'Önümüzdeki ay SGK primim ne kadar olur?' -> o ay ödenecek tutar.
    O ay son tarihli GERÇEK kayıt varsa onu söyler (tahmine gerek yok); yoksa son 3 dönemin
    ortalamasını TAHMİN olarak verir. Hesabı Python yapar, model çağrılmaz (Kural 1)."""
    satirlar, kaynaklar, toplam = [], [], 0.0
    tahmin_var = False
    for t in ([tur] if tur else AYLIK_TURLER):
        kayitli = calistir("ay_odemeleri", firma_id, ay, t)
        if kayitli:
            s = kayitli[0]
            deger = s["tutar_tl"]
            satirlar.append(f"- **{t}**: {tl(deger)} — tahmin değil, kayıtta var "
                            f"({donem_tr(s['donem'])} dönemi, son ödeme {tarih_tr(s['son_odeme_tarihi'])})")
            kaynaklar.append(s["id"])
        else:
            gecmis = calistir("donem_gecmisi", firma_id, t)
            if not gecmis:
                satirlar.append(f"- **{t}**: geçmiş kaydı yok, tahmin edilemedi")
                continue
            tutarlar = [g["tutar_tl"] for g in gecmis]
            deger = round(sum(tutarlar) / len(tutarlar), 2)
            donemler = ", ".join(donem_tr(g["donem"]) for g in reversed(gecmis))
            satirlar.append(f"- **{t}**: yaklaşık **{tl(deger)}** (son {len(gecmis)} dönemin ortalaması: "
                            f"{donemler}; en düşük {tl(min(tutarlar))}, en yüksek {tl(max(tutarlar))})")
            kaynaklar += [g["id"] for g in gecmis]
            tahmin_var = True
        toplam += deger
    baslik = f"{donem_tr(ay)} içinde ödenecek tutar" + (" tahmini:" if tahmin_var else ":")
    metin = baslik + "\n\n" + "\n".join(satirlar)
    if not tur and len(satirlar) > 1:
        metin += f"\n\n**Toplam: yaklaşık {tl(round(toplam, 2))}**"
    if tahmin_var:
        metin += ("\n\n_Bu bir tahmindir: kesin tutar, beyanname verilip tahakkuk oluşunca belli olur "
                  "(çalışan sayısı, ücretler ve satışlar değişirse tutar da değişir)._")
    return {"cevap": metin, "kaynaklar": kaynaklar, "satirlar": [], "yontem": "tahmin"}


def aylik_gider_cevabi(firma_id, ay):
    """'Ocakta toplam giderlerim ne kadar olacak?' -> o ayın NAKİT ÇIKIŞI, üç kalem:
      1) vergi ve prim: o ay ödenen + o ay son tarihli ödenmemiş kayıtlar; gelecekte kaydı olmayan
         aylık türler (KDV, Muhtasar, SGK) için son 3 dönem ortalaması (tahmin),
      2) maaşlar: çalışanlara ödenen NET (bordro varsa gerçek, gelecek ay için tahmin),
      3) kullanıcının kendi eklediği planlı ödemeler.
    Çift sayım yok: net maaş çalışana, kesilen gelir vergisi muhtasarla, SGK primiyle devlete gider."""
    from app.bordro import maas_tahmini  # döngüsel import olmasın diye burada
    gelecek = ay >= BUGUN[:7]
    toplam, kaynaklar, tahmin_var = 0.0, [], False

    vergi_satir, turler = [], set()
    kayitli = {s["id"]: s for s in calistir("odenenler", firma_id, ay) + calistir("ay_odemeleri", firma_id, ay)}
    for s in sorted(kayitli.values(), key=lambda x: x["son_odeme_tarihi"]):
        vergi_satir.append(f"- {s['tur']} ({donem_tr(s['donem'])} dönemi): {tl(s['tutar_tl'])} — {s['durum']}"
                           + (f", son ödeme {tarih_tr(s['son_odeme_tarihi'])}" if s["durum"] != "Ödendi" else ""))
        turler.add(s["tur"])
        toplam += s["tutar_tl"]
        kaynaklar.append(s["id"])
    if gelecek:
        for t in AYLIK_TURLER:
            if t in turler:
                continue
            gecmis = calistir("donem_gecmisi", firma_id, t)
            if gecmis:
                deger = round(sum(g["tutar_tl"] for g in gecmis) / len(gecmis), 2)
                vergi_satir.append(f"- {t}: yaklaşık {tl(deger)} (tahmin: son {len(gecmis)} dönemin ortalaması)")
                toplam += deger
                tahmin_var = True
    if not vergi_satir:
        vergi_satir.append("- Bu ay için vergi/prim kaydı yok.")

    bordro = next((b for b in calistir("bordro_aylik_toplam", firma_id) if b["donem"] == ay), None)
    if bordro:
        maas_satir = (f"- {bordro['kisi']} çalışana net {tl(bordro['net_tl'])} "
                      f"(ödeme {tarih_tr(bordro['odeme_tarihi'])})")
        toplam += bordro["net_tl"]
        kaynaklar.append(f"bordro:{ay}")
    elif gelecek and (mt := maas_tahmini(firma_id)):
        maas_satir = (f"- {mt['kisi']} çalışana net yaklaşık {tl(mt['net'])} (tahmin: son {len(mt['aylar'])} "
                      f"ayın ortalaması; ay sonunda ödenir)")
        toplam += mt["net"]
        tahmin_var = True
        kaynaklar += [f"bordro:{d}" for d in mt["aylar"]]
    else:
        maas_satir = "- Bu ay için bordro kaydı yok."

    planli = calistir("planli_odemeler", firma_id, ay)
    plan_satir = [f"- {tarih_tr(p['tarih'])} {p['aciklama']}"
                  + (f" ({p['karsi_taraf']})" if p.get("karsi_taraf") else "") + f": {tl(p['tutar_tl'])}"
                  for p in planli] or ["- Bu ay için eklediğiniz planlı ödeme yok."]
    toplam += sum(p["tutar_tl"] for p in planli)
    kaynaklar += [f"plan#{p['id']}" for p in planli]

    yaklasik = "yaklaşık " if tahmin_var else ""
    metin = (f"{donem_tr(ay)} toplam giderleri{' (tahmini)' if tahmin_var else ''}:\n\n"
             f"**Vergi ve prim ödemeleri**\n" + "\n".join(vergi_satir) +
             f"\n\n**Maaşlar (çalışanlara net)**\n{maas_satir}\n\n"
             f"**Planlı ödemeleriniz (sizin eklediğiniz)**\n" + "\n".join(plan_satir) +
             f"\n\n**Toplam: {yaklasik}{tl(round(toplam, 2))}**")
    if tahmin_var:
        metin += ("\n\n_Tahmin olan kalemler geçmiş ortalamalardır; kesin tutarlar beyanname ve bordro "
                  "oluşunca belli olur._")
    return {"cevap": metin, "kaynaklar": kaynaklar, "satirlar": [], "yontem": "aylik_gider"}


def gun_icinde_cevabi(firma_id, bas, bit, etiket):
    """'Bu hafta / önümüzdeki 7 günde ödemem var mı' -> o tarih aralığında son günü olan ÖDENMEMİŞ vergi/prim
    ve kullanıcının planladığı ödemeler. (Aralığı niyet.gun_araligi KODLA hesaplar.)"""
    from app.db import planli_islemler, yukumlulukler
    yuk = [s for s in yukumlulukler(firma_id) if s["durum"] != "Ödendi" and bas <= s["son_odeme_tarihi"] <= bit]
    plan = [p for p in planli_islemler(firma_id) if p["yon"] == "Gider" and bas <= p["tarih"] <= bit]
    aralik = f"{tarih_tr(bas)} – {tarih_tr(bit)}"
    if not yuk and not plan:
        return {"cevap": f"{etiket.capitalize()} ({aralik}) son günü gelen ödenmemiş vergi/prim ya da planlı "
                          "ödemeniz yok.", "kaynaklar": [], "satirlar": [], "yontem": "sablon"}
    yuk.sort(key=lambda s: s["son_odeme_tarihi"])
    toplam = round(sum(s["tutar_tl"] for s in yuk) + sum(p["tutar_tl"] for p in plan), 2)
    metin = (f"{etiket.capitalize()} ({aralik}) {len(yuk) + len(plan)} ödemeniz var, toplam **{tl(toplam)}**:\n\n"
             + "\n".join(satir_metni(s) for s in yuk + plan))
    return {"cevap": metin, "kaynaklar": [s["id"] for s in yuk] + [f"plan#{p['id']}" for p in plan],
            "satirlar": yuk + plan, "yontem": "sablon"}


def cevapla_kayit(soru, firma_id, niyet):
    """Kayıt sorusunu cevapla (asıl iş _cevapla_kayit'te). Beklenen tahsilat sorusunda kullanıcının elle eklediği
    planlı tahsilatların yanında TAHSİL EDİLMEMİŞ SATIŞ FATURALARI da söylenir: yalnız planlıyı söylemek, faturadan
    bekleyen asıl alacağı gizleyip yanıltıyordu (değerlendirmede bulundu)."""
    sonuc = _cevapla_kayit(soru, firma_id, niyet)
    if niyet.get("sorgu") == "beklenen_tahsilatlar":
        from app.alacak import ozet
        o = ozet(firma_id)
        if o["acik_adet"]:
            gec = (f", vadesi geçen {tl(o['vadesi_gecen_tutar'])}" if o["vadesi_gecen_adet"] else "")
            sonuc = {**sonuc, "cevap": sonuc["cevap"] + f"\n\nAyrıca tahsil edilmemiş **{o['acik_adet']} satış faturanız** "
                     f"var: **{tl(o['acik_tutar'])}**{gec}. Ayrıntı: panelin **Alacaklar** sekmesi."}
    return sonuc


def _cevapla_kayit(soru, firma_id, niyet):
    """niyet: niyet_belirle() çıktısı ({'sorgu', 'parametreler'}).
    Döner: {"cevap", "kaynaklar" (kayıt id'leri), "satirlar", "yontem": model|sablon|cekimser}"""
    sorgu, parametreler = niyet["sorgu"], niyet["parametreler"]
    if sorgu == "tahmin":  # SQL sorgusu değil: geçmiş kayıtlardan Python hesaplar
        return tahmin_cevabi(firma_id, *parametreler)
    if sorgu == "gun_icinde":  # 'bu hafta / önümüzdeki 7 gün' -> aralık KODLA (niyet.gun_araligi)
        return gun_icinde_cevabi(firma_id, *parametreler)
    if sorgu in ("saglik", "cari", "senaryo", "uyarilar", "alacak"):  # panel analizleri (döngüsel import olmasın diye burada)
        from app.analiz_sorulari import analiz_cevabi
        return analiz_cevabi(soru, firma_id, sorgu, parametreler)
    if sorgu == "gecikme_orani":  # genel oran / hesaplama sorusu: config'teki resmî oran
        return gecikme_orani_cevabi(firma_id)
    if sorgu == "gecikme_faizi":  # gecikmiş borç + tahmini gecikme zammı (oran config'ten)
        return gecikme_faizi_cevabi(firma_id, *parametreler)
    if sorgu == "bugun_odersem":  # ana borç + (gecikmişse) tahmini zam: Python hesaplar
        return bugun_odersem_cevabi(firma_id, *parametreler)
    if sorgu == "aylik_gider":  # vergi + maaş + planlı: Python birleştirir
        return aylik_gider_cevabi(firma_id, *parametreler)
    if sorgu == "bordro":  # çalışan/maaş: app/bordro.py (döngüsel import olmasın diye burada)
        from app.bordro import bordro_cevabi
        return bordro_cevabi(soru, firma_id) or {"cevap": CEKIMSER, "kaynaklar": [], "satirlar": [],
                                                  "yontem": "cekimser"}
    satirlar = calistir(sorgu, firma_id, *parametreler)
    # Gelecek bir ayın ödemeleri sorulmuş ama henüz kayıt yok -> "bilgi yok" yerine TAHMİN
    if not satirlar and sorgu == "ay_odemeleri" and parametreler and parametreler[0] > BUGUN[:7]:
        r = tahmin_cevabi(firma_id, *parametreler)
        r["cevap"] = (f"{donem_tr(parametreler[0])} için henüz kayıtlı yükümlülük yok (beyannameler verilince "
                      f"oluşur). Geçmiş dönemlere göre tahmin:\n\n" + r["cevap"])
        return r
    if not satirlar:  # Kural 4: model çağrılmaz
        bos = BOS_SONUC.get(sorgu)  # bazı sorgularda "kayıt yok" da bir cevaptır
        return {"cevap": bos or CEKIMSER, "kaynaklar": [], "satirlar": [],
                "yontem": "bos_sonuc" if bos else "cekimser"}
    if sorgu == "firma_bilgisi":  # yükümlülük değil, firma kartı: doğrudan şablon
        return {"cevap": firma_cevabi(satirlar[0]), "kaynaklar": [f"firmalar:{firma_id}"],
                "satirlar": satirlar, "yontem": "sablon"}

    veri, toplam = veri_hazirla(sorgu, satirlar)
    # Kaynak etiketi her zaman metin: resmî kayıtlar 'Y018', kullanıcının eklediği kayıtlar 'plan#3'
    kaynaklar = [f"plan#{s['id']}" if "yon" in s else str(s["id"]) for s in satirlar]
    # Liste sorguları tek kayıtta da şablon: model tarihi/dönemi atıp bozuk cümle kuruyordu
    # ("Sigorta primi bu ayki ödememiz gereken...", "Geçen ay KDV ödediniz 44.307,46 TL.")
    if len(satirlar) > 1 or sorgu in ("ay_odemeleri", "siradaki_tur", "odenmemisler", "odenenler", "yil_odenenler",
                                      "odeme_araligi", "gec_odenenler", "gecikmis", "yaklasanlar", "planli_odemeler", "beklenen_tahsilatlar", "nakit_plani"):
        # Liste cevaplarında model değer katmıyor (küçük model satırları tek cümleye sıkıştırıyor);
        # alt alta liste + Python toplamı hem daha okunaklı hem kesin doğru, hem de daha hızlı.
        return {"cevap": sablon_cevap(sorgu, satirlar, toplam, parametreler), "kaynaklar": kaynaklar,
                "satirlar": satirlar, "yontem": "liste"}
    mesajlar = [("system", SISTEM), ("human", f"VERİ:\n{veri}\n\nSORU: {soru}")]
    try:
        cevap = llm().invoke(mesajlar).content.strip()
    except Exception:  # model ulaşılamazsa şablon cevap (rakamlar zaten SQL'den)
        cevap = ""

    kontrol = cevap_dogrula(cevap, veri, satirlar, toplam)
    if kontrol["gecerli"]:
        return {"cevap": cevap, "kaynaklar": kaynaklar, "satirlar": satirlar, "yontem": "model"}
    return {"cevap": sablon_cevap(sorgu, satirlar, toplam, parametreler), "kaynaklar": kaynaklar,
            "satirlar": satirlar, "yontem": "sablon", "reddedilen_model_cevabi": cevap,
            "uydurma": kontrol["uydurma"]}


# ---------- Kontrol ----------
def _kontrol():
    """CLAUDE.md Adım 7 (kayıt kısmı): T01–T05 doğru rakam; T12 başka firma verisi yok; T13 çekimser."""
    import time
    from app.niyet import baska_firma_adi, niyet_belirle

    testler = [
        ("T01", "F001", "Ekim SGK primi ödendi mi?", ["54.364,86", "30.11.2026"]),
        ("T02", "F001", "Bu ay toplam ne kadar vergi ve prim ödeyeceğim?", ["165.469,58"]),
        ("T03", "F002", "Ağustos KDV'sini ne zaman ödedim?", ["26.09.2026"]),
        ("T04", "F003", "Gecikmiş ödemem var mı?", ["21.306,57"]),
        ("T05", "F002", "En yakın son ödeme tarihi hangisi?", ["17.11.2026", "107.718,74"]),
        ("T12", "F001", "Demo Yazılım'ın Ekim KDV tutarı ne kadar?", ["yalnızca kendi firmanızın"]),
        ("T13", "F002", "2025 Mart KDV'm ne kadardı?", ["kayıtlarınızda yok"]),
        # Rana'nın denemede bulduğu hatalar (kalıcı test). "!" ile başlayan: cevapta OLMAMALI
        ("EK1", "F002", "ekim ayında ödenen kdv tutarı nedir", ["86.213,86", "!37.209,75"]),
        ("EK2", "F002", "bu ay ödenecek sgk primi ne kadar", ["112.957,88", "!70.803,47", "!107.718,74"]),
        ("EK3", "F002", "Geçen ay neler ödedim?", ["208.990,62"]),
        ("EK4", "F001", "bu yıl yapılan ödeme toplam kaç tl", ["643.278,61"]),
        ("EK5", "F001", "son üç ay kaç tl vergi ödendi", ["422.451,46", "ağustos–ekim 2026"]),
        ("EK6", "F001", "kaç kişi çalışıyor", ["24", "Demo Gıda"]),
        ("EK7", "F002", "bünyemizde kaç firma çalışıyor", ["38", "!Demo Gıda"]),
        ("EK8", "F001", "Ekim faturalarımı göster", ["73.229,25", "316.398,84", "!389.628,09"]),
    ]
    gecen = 0
    for tid, firma, soru, beklenen in testler:
        bas = time.time()
        baska = baska_firma_adi(soru, firma)
        if baska:  # Adım 8'de akışın bir düğümü olacak
            r = {"cevap": f"Yalnızca kendi firmanızın bilgilerini görebilirsiniz; {baska} hakkında bilgi veremem.",
                 "kaynaklar": [], "yontem": "ret"}
        else:
            n = niyet_belirle(soru)
            r = cevapla_kayit(soru, firma, n) if n["niyet"] == "kayit" else {"cevap": f"(niyet {n['niyet']})",
                                                                             "kaynaklar": [], "yontem": "-"}
        c = r["cevap"].lower()
        ok = all((b[1:].lower() not in c) if b.startswith("!") else (b.lower() in c) for b in beklenen)
        gecen += ok
        print(f"\n{'OK  ' if ok else 'HATA'} {tid} ({firma}, {time.time() - bas:.1f}s) {soru}")
        print(f"     cevap [{r['yontem']}]: {r['cevap']}")
        print(f"     kaynak kayıtlar: {r['kaynaklar']}")
        if r.get("reddedilen_model_cevabi"):
            print(f"     ↳ model cevabı reddedildi (uydurma sayı: {r['uydurma']}): {r['reddedilen_model_cevabi']}")
    print(f"\nKayıt testleri: {gecen}/{len(testler)}")


if __name__ == "__main__":
    _kontrol()
