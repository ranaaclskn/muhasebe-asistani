"""Kayıt cevabı: SQL satırları -> Türkçe cevap.

Kural 1 — Rakamlar SQL'den gelir: Toplamı PYTHON hesaplar; model yalnızca verilen sayıları cümleye döker.
Model cevabındaki her tutar/tarih VERİ'de birebir yoksa model cevabı atılır, şablon cevap kullanılır.
Kural 4 — Satır yoksa model çağrılmaz, çekimser cevap verilir.

Kontrol (proje klasöründen):  python -m app.kayit
"""
import re

from langchain_ollama import ChatOllama

from app.config import LLM_MODEL, OLLAMA_URL
from app.db import calistir

CEKIMSER = "Bu bilgi kayıtlarınızda yok, muhasebecinize iletebilirim."
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
    metin = (f"- {s['tur']}, {donem_tr(s['donem'])} dönemi: {tl(s['tutar_tl'])}, "
             f"son ödeme tarihi {tarih_tr(s['son_odeme_tarihi'])}, durum: {s['durum']}")
    if s.get("odeme_tarihi"):
        metin += f", ödeme tarihi {tarih_tr(s['odeme_tarihi'])}"
    return metin


def veri_hazirla(sorgu, satirlar):
    """VERİ metni + Python'da hesaplanan toplam."""
    satirlar_metin = [satir_metni(s) for s in satirlar]
    toplam = None
    if sorgu in ("ay_odemeleri", "odenenler", "yil_odenenler", "gecikmis", "faturalar") and len(satirlar) > 1:
        toplam = round(sum(s["tutar_tl"] for s in satirlar), 2)
        satirlar_metin.append(f"TOPLAM ({len(satirlar)} kayıt): {tl(toplam)}")
    return "\n".join(satirlar_metin), toplam


def sablon_cevap(sorgu, satirlar, toplam):
    """Modelsiz, her zaman doğru cevap (model cevabı doğrulamadan geçemezse kullanılır)."""
    if sorgu == "durum" and len(satirlar) == 1:
        s = satirlar[0]
        if s["durum"] == "Ödendi":
            return (f"{donem_tr(s['donem'])} {s['tur']}: {tl(s['tutar_tl'])}, "
                    f"{tarih_tr(s['odeme_tarihi'])} tarihinde ödendi.")
        return (f"{donem_tr(s['donem'])} {s['tur']}: {tl(s['tutar_tl'])}, durum: {s['durum']}, "
                f"son ödeme tarihi {tarih_tr(s['son_odeme_tarihi'])}.")
    if sorgu == "en_yakin":
        s = satirlar[0]
        return (f"En yakın ödeme: {s['tur']} ({donem_tr(s['donem'])}), {tl(s['tutar_tl'])}, "
                f"son ödeme tarihi {tarih_tr(s['son_odeme_tarihi'])}.")
    # Birden fazla kayıt: okunaklı olsun diye ALT ALTA liste (Markdown; Streamlit madde olarak çizer)
    baslik = {"gecikmis": "Gecikmiş ödemeniz var:",
              "ay_odemeleri": f"{len(satirlar)} ödeme bekliyor:",
              "odenenler": f"{len(satirlar)} ödeme yapılmış:",
              "yil_odenenler": f"{len(satirlar)} ödeme yapılmış (türe göre özet):",
              "odeme_gecmisi": "Son ödemeleriniz:",
              "faturalar": f"{len(satirlar)} fatura:"}.get(sorgu, "Kayıtlarınız:")
    if sorgu == "yil_odenenler":  # yıl boyunca çok kayıt olur -> türe göre grupla
        gruplar = {}
        for s in satirlar:
            g = gruplar.setdefault(s["tur"], [0, 0.0])
            g[0] += 1
            g[1] += s["tutar_tl"]
        maddeler = [f"- **{tur}**: {tl(round(t, 2))} ({n} ödeme)" for tur, (n, t) in gruplar.items()]
    else:
        maddeler = [satir_metni(s) for s in satirlar]  # satir_metni zaten "- " ile başlıyor
    metin = baslik + "\n\n" + "\n".join(maddeler)
    if toplam is not None:
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
    3) Hiçbir kayıt ödenmemişken cevap 'ödendi' dememeli (durum çelişkisi)."""
    sayilar = SAYI_DESENI.findall(cevap)
    uydurma = [s for s in sayilar if s not in veri]
    ana = toplam if toplam is not None else (satirlar[0]["tutar_tl"] if len(satirlar) == 1 else None)
    if ana is not None and tl(ana).replace(" TL", "") not in cevap:
        uydurma.append(f"ana rakam eksik ({tl(ana)})")
    kucuk = cevap.lower()
    odenmemis = all(s.get("durum", "Ödendi") != "Ödendi" for s in satirlar)
    celiski = (odenmemis and re.search(r"ödendi|ödediniz|ödenmiş", kucuk)
               and not re.search(r"ödenmedi|ödenmemiş|bekliyor|gecik", kucuk))
    return {"gecerli": bool(sayilar) and not uydurma and not celiski,
            "uydurma": uydurma + (["durum çelişkisi"] if celiski else [])}


def cevapla_kayit(soru, firma_id, niyet):
    """niyet: niyet_belirle() çıktısı ({'sorgu', 'parametreler'}).
    Döner: {"cevap", "kaynaklar" (kayıt id'leri), "satirlar", "yontem": model|sablon|cekimser}"""
    sorgu, parametreler = niyet["sorgu"], niyet["parametreler"]
    satirlar = calistir(sorgu, firma_id, *parametreler)
    if not satirlar:  # Kural 4: model çağrılmaz
        return {"cevap": CEKIMSER, "kaynaklar": [], "satirlar": [], "yontem": "cekimser"}

    veri, toplam = veri_hazirla(sorgu, satirlar)
    kaynaklar = [s["id"] for s in satirlar]
    if len(satirlar) > 1:
        # Liste cevaplarında model değer katmıyor (küçük model satırları tek cümleye sıkıştırıyor);
        # alt alta liste + Python toplamı hem daha okunaklı hem kesin doğru, hem de daha hızlı.
        return {"cevap": sablon_cevap(sorgu, satirlar, toplam), "kaynaklar": kaynaklar,
                "satirlar": satirlar, "yontem": "liste"}
    mesajlar = [("system", SISTEM), ("human", f"VERİ:\n{veri}\n\nSORU: {soru}")]
    cevap = llm().invoke(mesajlar).content.strip()

    kontrol = cevap_dogrula(cevap, veri, satirlar, toplam)
    if kontrol["gecerli"]:
        return {"cevap": cevap, "kaynaklar": kaynaklar, "satirlar": satirlar, "yontem": "model"}
    return {"cevap": sablon_cevap(sorgu, satirlar, toplam), "kaynaklar": kaynaklar, "satirlar": satirlar,
            "yontem": "sablon", "reddedilen_model_cevabi": cevap, "uydurma": kontrol["uydurma"]}


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
