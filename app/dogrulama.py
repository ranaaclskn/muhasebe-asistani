"""Model gerektirmeyen kalite yardımcıları: lexical rerank ve atıf doğrulama.

Atölye karşılığı: quality_utils.py (tokens, lexical_score, rerank_candidates, validate_citations)
ve d6_00_lexical_rerank.py (anlamsal sıra + lexical puan birleşimi).
Farklar: Türkçe İ/I düzeltmesi; atıf biçimi [K1] yerine [kaynak: dosya_adı].
"""
import re

STOP = {"ve", "ile", "için", "mi", "mı", "mu", "mü", "bir", "ne", "nerede", "nasıl", "hangi", "kadar",
        "kaç", "ben", "benim", "nedir", "bu", "de", "da", "olan", "olarak", "var", "mıydı", "olur",
        "yapılır", "zaman", "neydi", "ise", "gibi", "daha", "çok"}


def kucuk_harf(metin):
    """Türkçe doğru küçük harf: 'İ'->'i', 'I'->'ı' (Python lower() 'İ'yi 'i̇' yapar)."""
    return metin.replace("İ", "i").replace("I", "ı").lower()


def tokens(metin):
    return {x for x in re.findall(r"[a-z0-9çğıöşü]+", kucuk_harf(metin)) if len(x) > 2 and x not in STOP}


def kok(kelime, n=5):
    """Çok basit Türkçe 'kök': ilk n harf. 'beyannamemde' ve 'beyannamesi' -> 'beyan'."""
    return kelime[:n]


def lexical_score(soru, icerik):
    """Sorudaki kelimelerin (kökleriyle) parçada geçme oranı: 0..1"""
    qs = {kok(t) for t in tokens(soru)}
    if not qs:
        return 0.0
    ds = {kok(t) for t in tokens(icerik)}
    return len(qs & ds) / len(qs)


def rerank(soru, adaylar, top_n=3, lexical_agirlik=0.5):
    """Chroma adaylarını (doc, mesafe) yeniden sırala.
    birleşik = (1-w) * 1/anlamsal_sıra + w * lexical  (d6_00_lexical_rerank.py ile aynı fikir)
    Döner: [(doc, birlesik, lexical), ...] ilk top_n"""
    puanli = []
    for sira, (doc, _mesafe) in enumerate(adaylar, 1):
        lex = lexical_score(soru, doc.page_content)
        birlesik = (1 - lexical_agirlik) * (1 / sira) + lexical_agirlik * lex
        puanli.append((doc, birlesik, lex, sira))
    puanli.sort(key=lambda x: (-x[1], x[3]))
    return [(d, b, l) for d, b, l, _ in puanli[:top_n]]


AYLAR = ["ocak", "şubat", "mart", "nisan", "mayıs", "haziran", "temmuz",
         "ağustos", "eylül", "ekim", "kasım", "aralık"]


def soru_donemi(soru, varsayilan_yil=None):
    """Soruda açıkça ay geçiyorsa 'YYYY-AA' döndür ('2025 Mart' -> '2025-03'), yoksa None.
    Yıl yazılmamışsa bugünün yılı (config.BUGUN)."""
    from app.config import BUGUN
    varsayilan_yil = varsayilan_yil or BUGUN[:4]
    s = kucuk_harf(soru)
    ay = next((i for i, a in enumerate(AYLAR, 1) if re.search(rf"\b{a}", s)), None)
    if not ay:
        return None
    yil = re.search(r"\b(20\d{2})\b", s)
    return f"{yil.group(1) if yil else varsayilan_yil}-{ay:02d}"


# Türk biçimli tutar (44.307,46) ve tarih (28.10.2026)
SAYI_DESENI = re.compile(r"\d{1,3}(?:\.\d{3})*,\d{2}|\d{2}\.\d{2}\.\d{4}")


def kanit_eslestir(cevap, parcalar, soru=None):
    """Kanıt eşleştirme: cevaptaki her tutar/tarih, getirilen parçalardan birinde BİREBİR geçmeli.
    En çok kanıtı (sayı eşleşmesi + kelime örtüşmesi) içeren parçanın dosyası kaynak sayılır.
    Döner: {"kaynak", "uydurma_sayilar", "puan"}"""
    sayilar = set(SAYI_DESENI.findall(cevap))
    tum_metin = " ".join(d.page_content for d in parcalar)
    uydurma = sorted(s for s in sayilar if s not in tum_metin)
    # Yüzde ve düz sayılar da kanıt ister ("%15", "28'i"): önceden yalnız TL/tarih bakılıyordu ve
    # bağlamda olmayan "%15" uydurması geçmişti. Tutar/tarihlerin içindeki parçalar ayrıca sayılmaz.
    kalan = SAYI_DESENI.sub(" ", cevap)
    for n in set(re.findall(r"\d+(?:[.,]\d+)?", kalan)):
        if not re.search(rf"(?<![\d.,]){re.escape(n)}(?![\d]|[.,]\d)", tum_metin):
            uydurma.append(n)
    # Yüzde, SORUYLA ilgili bir satırda geçmeli: "gecikme zammı oranı nedir" sorusuna model beyannamedeki
    # "SGK işçi payı kesintisi (%14)" satırını alıp "gecikme zammı oranı %14" demişti (sayı bağlamda var,
    # anlamı yanlış). Satırda sorunun kelimelerinden (kökleriyle) en az biri yoksa yüzde uydurma sayılır.
    if soru:
        soru_kokleri = {kok(t) for t in tokens(soru)} - {"oranı", "oran", "yüzde"}
        satirlar = [x for d in parcalar for x in d.page_content.splitlines()]
        for n in set(re.findall(r"%\s*(\d+(?:[.,]\d+)?)", cevap)):
            ilgili = [x for x in satirlar if re.search(rf"%\s*{re.escape(n)}(?!\d)", x)
                      and soru_kokleri & {kok(t) for t in tokens(x)}]
            if not ilgili:
                uydurma.append(f"%{n} (soruyla ilgisiz satırdan)")
    en_iyi, en_puan = None, -1.0
    for d in parcalar:
        puan = 2 * sum(s in d.page_content for s in sayilar) + lexical_score(cevap, d.page_content)
        if puan > en_puan:
            en_iyi, en_puan = d.metadata["kaynak"], puan
    return {"kaynak": en_iyi, "uydurma_sayilar": uydurma, "puan": round(en_puan, 3)}


ATIF_DESENI = re.compile(r"\[kaynak:\s*([^\]]+)\]", re.IGNORECASE)


def atiflar(cevap):
    """'[kaynak: a.txt, b.txt]' -> {'a.txt', 'b.txt'}"""
    bulunan = set()
    for grup in ATIF_DESENI.findall(cevap):
        for parca in re.split(r"[,;]", grup):
            parca = parca.strip()
            if parca:
                bulunan.add(parca if parca.endswith(".txt") else parca + ".txt")
    return bulunan


def validate_citations(cevap, bilinen_kaynaklar):
    """Cevapta anılan her kaynak, getirilen kaynaklar içinde mi?
    DİKKAT: Geçerli atıf, cevabın DOĞRU olduğunu kanıtlamaz; yalnızca uydurma kaynak olmadığını gösterir."""
    got = atiflar(cevap)
    bilinen = set(bilinen_kaynaklar)
    return {"valid": bool(got) and got <= bilinen, "used": sorted(got),
            "invalid": sorted(got - bilinen), "missing": not got}
