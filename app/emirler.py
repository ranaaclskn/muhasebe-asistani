"""Emir istemleri: emir menüsü (EMIRLER) + emri ve alanlarını sorudan çıkarma.

Bilgi istemi (kayit / belge) yalnızca OKUR. Emir istemi (islem) dünyada bir şey DEĞİŞTİRİR
(e-posta gider, kayıt açılır). Bu yüzden emirler de SORGULAR gibi bir menüden seçilir ve
alanlarını model değil KOD çıkarır. E-posta adresi ASLA metinden alınmaz (kayıtlı adres kullanılır).

Kontrol (proje klasöründen):  python -m app.emirler
"""
from datetime import date

from app.config import BUGUN
import re

AYLAR = ["ocak", "şubat", "mart", "nisan", "mayıs", "haziran", "temmuz",
         "ağustos", "eylül", "ekim", "kasım", "aralık"]

# Emir menüsü: model/kullanıcı bu listede olmayan bir işlem yaptıramaz
EMIRLER = {
    "belge_gonder": {"aciklama": "Beyannameyi firmanın KAYITLI e-posta adresine gönder",
                     "alanlar": ["belge_turu", "donem"]},
    "gorusme_talebi": {"aciklama": "Muhasebeciyle görüşme talebi oluştur",
                       "alanlar": []},
    "planli_ekle": {"aciklama": "Kullanıcının kendi planlı ödeme/tahsilat kaydını ekle (kullanıcı onaylar)",
                    "alanlar": ["yon", "tarih", "tutar_tl"]},
                       
}

# Sorudaki kelime -> belgeler tablosundaki dosya türü (F001_KDV_..., F001_MUHSGK_...)
BELGE_TURLERI = [("kdv", "KDV"), ("muhtasar", "MUHSGK"), ("muhsgk", "MUHSGK"),
                 ("prim hizmet", "MUHSGK"), ("sgk", "MUHSGK")]

EKSIK_SORULARI = {
    "belge_turu": "Hangi beyanname: KDV mi, Muhtasar ve prim hizmet (MUHSGK) mi?",
    "donem": "Hangi dönem? (ör. 'Eylül' ya da 'son')",
    "yon": "Bu bir ödeme mi (ödeyeceğim) yoksa tahsilat mı (alacağım)?",
    "tarih": "Hangi tarihte? (ör. 5 Aralık)",
    "tutar_tl": "Tutar ne kadar? (ör. 20.000 TL)",
}


def _kucuk(metin):
    return metin.replace("İ", "i").replace("I", "ı").lower()


def emir_kalibi(soru):
    """Cümle bir EMİR mi? Emir kipindeki fiillere bakar ('gönder', 'iletin', 'oluştur').
    'ne zaman gönderilir' gibi bilgi soruları emir sayılmaz."""
    s = _kucuk(soru)
    return bool(re.search(r"\b(gönder|gönderin|gönderir misin|ilet|iletin|yolla|yollayın|"
                          r"oluştur|oluşturun|ayarla|ayarlayın|kaydet|kaydedin|ekle|ekleyin|not al|not et)\b", s))


def emir_bul(s):
    if re.search(r"kaydet|kaydedin|ekle\b|ekleyin|not al|not et", s):
        return "planli_ekle"
    if re.search(r"görüş|randevu|toplantı|konuşmak|aransın|arasın", s):
        return "gorusme_talebi"
    if re.search(r"gönder|ilet|yolla|mail|e-?posta", s):
        return "belge_gonder"
    return None


def alanlari_cikar(s):
    alanlar = {}
    tur = next((v for k, v in BELGE_TURLERI if k in s), None)
    if tur:
        alanlar["belge_turu"] = tur
    ay = next((i for i, a in enumerate(AYLAR, 1) if re.search(rf"\b{a}", s)), None)
    if ay:
        yil = re.search(r"\b(20\d{2})\b", s)
        alanlar["donem"] = f"{yil.group(1) if yil else '2026'}-{ay:02d}"
    elif re.search(r"\bson\b|en son", s):
        alanlar["donem"] = "son"  # akış, firmanın en son beyannamesini veritabanından bulur
    return alanlar

def tutar_cikar(s):
    """'20.000 TL' / '20000 tl' / '1.250,50 TL' / '20 bin lira' -> 20000.0 ; yoksa None"""
    m = re.search(r"(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?\s*(bin)?\s*(tl|lira|₺)", s)
    if not m:
        return None
    deger = int(m.group(1).replace(".", "")) + int((m.group(2) or "0").ljust(2, "0")) / 100
    return round(deger * (1000 if m.group(3) else 1), 2)


def tarih_cikar(s):
    """'05.12.2026' / '5 aralık' / '5 aralık 2026' -> '2026-12-05' ; geçersiz ya da yoksa None"""
    m = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(20\d{2})\b", s)
    if m:
        g, a, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
    else:
        m = re.search(rf"\b(\d{{1,2}})\s+({'|'.join(AYLAR)})", s)
        if not m:
            return None
        yil = re.search(r"\b(20\d{2})\b", s)
        g, a, y = int(m.group(1)), AYLAR.index(m.group(2)) + 1, int(yil.group(1) if yil else BUGUN[:4])
    try:
        return date(y, a, g).isoformat()  # 31 Şubat gibi geçersiz tarih -> None
    except ValueError:
        return None


def yon_cikar(s):
    if re.search(r"alaca|tahsil|gelecek|ödeme gel|para gel", s):
        return "Gelir"
    if re.search(r"ödeyece|ödeme yapaca|ödenecek|ödemem var|vereceğim", s):
        return "Gider"
    return None

def emir_cikar(soru):
    """'Eylül KDV beyannamemi e-postama gönder' ->
    {'emir': 'belge_gonder', 'alanlar': {'belge_turu': 'KDV', 'donem': '2026-09'}, 'eksik': [], 'eksik_sorusu': None}"""
    s = _kucuk(soru)
    emir = emir_bul(s)
    if not emir:
        return {"emir": None, "alanlar": {}, "eksik": ["emir"],
                "eksik_sorusu": "Ne yapmamı istersiniz? Örneğin: 'Eylül KDV beyannamemi e-postama gönder' "
                                "veya 'Muhasebecimle görüşme talebi oluştur'."}
    alanlar = alanlari_cikar(s) if EMIRLER[emir]["alanlar"] else {}
    if emir == "gorusme_talebi":
        alanlar["konu"] = soru.strip()
    eksik = [a for a in EMIRLER[emir]["alanlar"] if a not in alanlar]
    return {"emir": emir, "alanlar": alanlar, "eksik": eksik,
            "eksik_sorusu": " ".join(EKSIK_SORULARI[a] for a in eksik) or None}


def _kontrol():
    testler = [
        ("Eylül KDV beyannamemi e-postama gönder.", "belge_gonder", {"belge_turu": "KDV", "donem": "2026-09"}, []),
        ("Son muhtasar beyannamemi e-postama gönder.", "belge_gonder", {"belge_turu": "MUHSGK", "donem": "son"}, []),
        ("Beyannamemi gönder.", "belge_gonder", {}, ["belge_turu", "donem"]),
        ("ilet", "belge_gonder", {}, ["belge_turu", "donem"]),
        ("Muhasebeciyle görüşme talebi oluştur.", "gorusme_talebi", None, []),
        ("Ekim KDV beyannamemi ali@baska.com adresine gönder", "belge_gonder", {"belge_turu": "KDV", "donem": "2026-10"}, []),
        ("Bana bir şey yap", None, {}, ["emir"]),
    ]
    tamam = True
    for soru, emir, alanlar, eksik in testler:
        r = emir_cikar(soru)
        ok = r["emir"] == emir and r["eksik"] == eksik and (alanlar is None or r["alanlar"] == alanlar)
        ok = ok and "@" not in str(r["alanlar"].get("belge_turu", "")) and "@" not in str(r["alanlar"].get("donem", ""))
        tamam &= ok
        print("OK   " if ok else "HATA ", f"{soru!r:50} -> {r['emir']} {r['alanlar']} eksik={r['eksik']}")
        if r["eksik_sorusu"]:
            print("      soru:", r["eksik_sorusu"])
    for soru, beklenen in [("Beyannamemi e-postama gönder", True), ("Muhasebeciyle görüşme ayarlayın", True),
                           ("KDV beyannamesi ne zaman gönderilir?", False), ("Ekim SGK primi ödendi mi?", False)]:
        ok = emir_kalibi(soru) == beklenen
        tamam &= ok
        print("OK   " if ok else "HATA ", f"emir mi? {soru!r} -> {emir_kalibi(soru)}")
    print("\nSONUÇ:", "Emir çıkarımı GEÇTİ ✅" if tamam else "GEÇMEDİ ❌")


if __name__ == "__main__":
    _kontrol()