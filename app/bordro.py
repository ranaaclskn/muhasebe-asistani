"""Maaş / ücret soruları: MUHSGK beyannamelerindeki "Brüt ücret toplamı" ve "Çalışan sayısı"ndan.

Neden ayrı modül? Ücret tutarları veritabanında YOK, yalnızca beyanname metinlerinde var. RAG bu soruları
cevaplayamıyordu ("ortalama net maaş", "bir ayda ödenen toplam maaş" -> "kayıtlarınızda yok"), çünkü
cevap tek bir parçada yazmıyor, HESAP gerektiriyor (toplam, çalışan başına ortalama, birkaç ay toplamı).
Burada sayılar belgeden düzenli ifadeyle (regex) okunur, hesabı Python yapar, model çağrılmaz (Kural 1).
Firma yalnızca KENDİ beyannamelerini görür: dosya adı oturumdaki firma_id ile başlar (Kural 2).

Kontrol (proje klasöründen):  python -m app.bordro
"""
import re

from app.config import BELGE_DIR, BUGUN
from app.kayit import donem_tr, tl
from app.niyet import _kucuk, _son_n_ay, _soru_ayi

NET_YOK = ("Net maaş tutarı kayıtlarınızda yok: beyannamelerde yalnızca **brüt** ücret var "
           "(net için gelir vergisi, SGK işçi payı ve damga vergisi kesintileri gerekir).")


def bordro_kalibi(soru):
    """Maaş/ücret TUTARI mı soruluyor? 'ev satın alma ücreti' gibi sorular buraya girmez."""
    s = _kucuk(soru)
    return bool(re.search(r"maaş|bordro|brüt ücret|net ücret|ortalama ücret|ödenen ücret|ücret toplam|"
                          r"(çalışan|personel|işçi)\w*\s+(?:\w+\s+)?ücret|ücret\w*\s+(?:gideri|ödeme)", s))


def _sayi(metin):
    """'108.058,73' -> 108058.73"""
    return float(metin.replace(".", "").replace(",", "."))


def bordro_kayitlari(firma_id):
    """Firmanın MUHSGK beyannamelerinden aylık ücret bilgisi: [{donem, brut, calisan, kaynak}], eskiden yeniye."""
    kayitlar = []
    for yol in sorted(BELGE_DIR.glob(f"{firma_id}_MUHSGK_*.txt")):
        metin = yol.read_text(encoding="utf-8")
        brut = re.search(r"Brüt ücret toplamı:\s*([\d.,]+)\s*TL", metin)
        calisan = re.search(r"Çalışan sayısı:\s*(\d+)", metin)
        donem = re.search(r"_(\d{4}-\d{2})\.txt$", yol.name)
        if brut and calisan and donem:
            kayitlar.append({"donem": donem.group(1), "brut": _sayi(brut.group(1)),
                             "calisan": int(calisan.group(1)), "kaynak": yol.name})
    return kayitlar


def _secilen_aylar(s, kayitlar):
    """Sorudaki zamana göre hangi ayların kullanılacağı: (aylar, açıklama ya da hata)."""
    if (aralik := _son_n_ay(s)) or re.search(r"son \d+ ay|son (?:altı|üç|iki) ay", s):
        bas, bit = aralik or (kayitlar[0]["donem"], kayitlar[-1]["donem"])
        return [k for k in kayitlar if bas <= k["donem"] <= bit], None
    if re.search(r"bu yıl|yıl içinde|yıllık|\b20\d{2} yılı", s):
        yil = (re.search(r"\b(20\d{2})\b", s) or re.search(r"(\d{4})", BUGUN)).group(1)
        return [k for k in kayitlar if k["donem"].startswith(yil)], None
    ay = _soru_ayi(s)
    if ay:
        secilen = [k for k in kayitlar if k["donem"] == ay]
        if not secilen:
            ilk, son = donem_tr(kayitlar[0]["donem"]), donem_tr(kayitlar[-1]["donem"])
            return [], (f"{donem_tr(ay)} için ücret bilgisi kayıtlarınızda yok "
                        f"(beyannameler {ilk} – {son} arası mevcut).")
        return secilen, None
    return [kayitlar[-1]], None  # zaman söylenmezse: en son beyanname


def bordro_cevabi(soru, firma_id):
    """Maaş sorusuysa {"cevap", "kaynaklar"} döndürür; değilse None (soru RAG'a devam eder)."""
    if not bordro_kalibi(soru):
        return None
    kayitlar = bordro_kayitlari(firma_id)
    if not kayitlar:
        return None
    s = _kucuk(soru)
    aylar, hata = _secilen_aylar(s, kayitlar)
    if hata or not aylar:
        return {"cevap": hata or "Bu dönem için ücret bilgisi kayıtlarınızda yok.", "kaynaklar": []}

    on_ek = NET_YOK + "\n\n" if re.search(r"\bnet\b", s) else ""
    kaynaklar = [k["kaynak"] for k in aylar]
    toplam = round(sum(k["brut"] for k in aylar), 2)
    donem = donem_tr(aylar[0]["donem"]) if len(aylar) == 1 else \
        f"{donem_tr(aylar[0]['donem'])} – {donem_tr(aylar[-1]['donem'])}"

    # "ortalama maaş / kişi başı / çalışan başına" -> çalışan başına aylık ortalama BRÜT ücret
    if re.search(r"ortalama|kişi başı|çalışan başı|personel başı|kişi başına", s):
        kisi_ay = sum(k["calisan"] for k in aylar)
        ort = round(toplam / kisi_ay, 2)
        if len(aylar) == 1:
            k = aylar[0]
            cevap = (f"{donem} beyannamesine göre {k['calisan']} çalışana toplam {tl(k['brut'])} brüt ücret "
                     f"ödenmiş; çalışan başına ortalama brüt ücret **{tl(ort)}**.")
        else:
            cevap = (f"{donem} arasında ({len(aylar)} ay) çalışan başına aylık ortalama brüt ücret "
                     f"**{tl(ort)}** (toplam {tl(toplam)} brüt ücret).")
        return {"cevap": on_ek + cevap, "kaynaklar": kaynaklar}

    # Toplam ücret: tek ay -> o ayın toplamı; birkaç ay -> ay ay liste + genel toplam
    if len(aylar) == 1:
        k = aylar[0]
        cevap = (f"{donem} beyannamesine göre {k['calisan']} çalışana ödenen brüt ücret toplamı "
                 f"**{tl(k['brut'])}**.")
    else:
        satirlar = [f"- {donem_tr(k['donem'])}: {tl(k['brut'])} ({k['calisan']} çalışan)" for k in aylar]
        cevap = (f"{donem} arasında ödenen brüt ücretler:\n\n" + "\n".join(satirlar)
                 + f"\n\n**Toplam: {tl(toplam)}** (aylık ortalama {tl(round(toplam / len(aylar), 2))})")
    return {"cevap": on_ek + cevap, "kaynaklar": kaynaklar}


def _kontrol():
    for soru in ["ortalama net maaş ne kadar", "bir ayda ödenen toplam maaş miktarı ne kadar",
                 "eylül ayında çalışanlara ödenen ücret toplamı", "son 3 ayda ödenen maaşlar",
                 "bu yıl ödenen toplam maaş", "ocak ayı maaşları", "ev satın alma ücreti ne"]:
        r = bordro_cevabi(soru, "F001")
        print(f"\n## {soru}\n{r['cevap'] if r else '(bordro sorusu değil -> RAG)'}")


if __name__ == "__main__":
    _kontrol()
