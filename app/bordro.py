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
ODEME = r"öde|maaş|ücret|net|brüt|kesinti|kesil|ne kadar|aldı|alıyor|kazan|bordro|para"
_EKLER = {"", "e", "a", "ye", "ya", "i", "ı", "u", "ü", "yi", "yı", "yu", "yü", "in", "ın", "un", "ün",
          "nin", "nın", "nun", "nün", "de", "da", "te", "ta", "den", "dan", "ten", "tan", "le", "la",
          "yle", "yla", "ne", "na", "nde", "nda"}


# ---------- Soruyu tanıma ----------
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


def bordro_kalibi(soru, firma_id=None):
    """Çalışan/maaş sorusu mu? Beyannamedeki ÜCRET rakamları da buradan cevaplanır: belge bu tablodan
    üretiliyor ve RAG'da küçük model 'net ücret toplamı' ile 'ortalama net ücret' satırlarını karıştırıyordu.
    Ücretle ilgisiz beyanname soruları ('beyannamede ödenecek muhtasar') RAG'da kalır."""
    s = _kucuk(soru)
    if "beyan" in s and not re.search(r"ücret|maaş|\bnet\b|brüt|kesinti", s):
        return False
    if re.search(r"maaş|bordro|brüt ücret|net ücret|ortalama ücret|ödenen ücret|ücret toplam|"
                 rf"{KISI}\s+(?:\w+\s+)?ücret|ücret\w*\s+(?:gideri|ödeme)", s):
        return True
    if re.search(KISI, s):
        if re.search(ODEME, s) or re.search(r"kimler|liste|isim|adları|kim var|görev", s):
            # "kaç çalışan var / çalışan sayısı" firma bilgisidir (ödeme kelimesi yoksa)
            return not (re.search(r"\bkaç\b|sayı", s) and not re.search(ODEME, s))
    if firma_id and re.search(ODEME + r"|görev|ne iş|işe gir", s):
        bulunan = calisan_bul(soru, calistir("calisan_listesi", firma_id))
        if bulunan:  # yalnız SOYAD eşleştiyse (Kaya, Demir...) maaş/çalışan kelimesi de şart
            ad_var = any(_eslesir(_kucuk(c["ad_soyad"]).split()[0], k)
                         for c in bulunan for k in re.findall(r"[a-zçğıöşü'’]+", s))
            return ad_var or bool(re.search(r"maaş|ücret|bordro|net|brüt", s))
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


def _sonuc(cevap, kaynaklar, satirlar=None):
    return {"cevap": cevap, "kaynaklar": kaynaklar, "satirlar": satirlar or [], "yontem": "bordro"}


# ---------- Cevaplar ----------
def _kisi_cevabi(s, kisi, firma_id):
    satirlar = calistir("calisan_bordrosu", firma_id, kisi["id"])
    aylar, hata = _secilen_aylar(s, [r["donem"] for r in satirlar], varsayilan="hepsi")
    if hata:
        return _sonuc(f"{kisi['ad_soyad']}: {hata}", [])
    secilen = [r for r in satirlar if r["donem"] in aylar]
    bilgi = (f"**{kisi['ad_soyad']}** — {kisi['gorev']}, işe giriş {tarih_tr(kisi['ise_giris'])}.")
    if re.search(r"görev|ne iş|işe gir|ne zaman başla", s) and not re.search(ODEME, s):
        return _sonuc(bilgi, [f"calisan:{kisi['id']}"])
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


def _calisan_listesi(firma_id):
    calisanlar = calistir("calisan_listesi", firma_id)
    liste = "\n".join(f"- {c['ad_soyad']} — {c['gorev']} (işe giriş {tarih_tr(c['ise_giris'])})" for c in calisanlar)
    return _sonuc(f"Kayıtlı {len(calisanlar)} çalışanınız var:\n\n{liste}", [f"calisan:{c['id']}" for c in calisanlar],
                  calisanlar)


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
    s = _kucuk(soru)
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

    # 2) Çalışan listesi (ödeme sorulmuyorsa)
    if re.search(r"kimler|liste|isim|adları|kim var|görev", s) and not re.search(ODEME, s):
        return _calisan_listesi(firma_id)

    aylar, hata = _secilen_aylar(s, donemler)
    if hata:
        return _sonuc(hata, [])
    secilen = [t for t in toplamlar if t["donem"] in aylar]

    # 3) Kişi bazında liste / en yüksek-en düşük maaş (tek ay; birden çok ay istendiyse sonuncusu)
    if re.search(r"en (?:yüksek|çok|fazla|düşük|az)|liste|kime|her (?:bir )?(?:çalışan|personel|eleman)|"
                 r"tek tek|kişi kişi|bazında|isim|tutarları|tutarlar|kim ne kadar|bordrosu|bordroyu|bordro\b", s):
        return _ay_listesi(firma_id, aylar[-1], s)

    # 4) Ortalama maaş (çalışan başına)
    if re.search(r"ortalama|kişi başı|çalışan başı|personel başı|kişi başına", s):
        kisi_ay = sum(t["kisi"] for t in secilen)
        net = round(sum(t["net_tl"] for t in secilen) / kisi_ay, 2)
        brut = round(sum(t["brut_tl"] for t in secilen) / kisi_ay, 2)
        kapsam = f"{_aralik_adi(aylar)} " + ("ayında" if len(aylar) == 1 else "arasında")
        return _sonuc(f"{kapsam} çalışan başına ortalama maaş: net **{tl(net)}**, brüt {tl(brut)} "
                      f"({secilen[-1]['kisi']} çalışan).", [f"bordro:{d}" for d in aylar], secilen)

    # 5) Toplam ödenen maaş (+ kesinti dökümü)
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
