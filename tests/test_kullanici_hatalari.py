"""Rana'nın arayüz denemelerinde bulduğu hatalar için kalıcı testler (model GEREKMEZ).
Gerçek veritabanına dokunmaz: data/muhasebe.db'nin geçici KOPYASINDA çalışır.
Çalıştır (proje klasöründen):  python -m pytest -q tests/test_kullanici_hatalari.py
"""
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import app.db as db  # noqa: E402
from app.dogrulama import kanit_eslestir  # noqa: E402
from app.bordro import bordro_cevabi, bordro_kayitlari  # noqa: E402
from app.kayit import cevapla_kayit, planli_aciklama_cevabi, tl  # noqa: E402
from app.niyet import kural_duzelt  # noqa: E402


@pytest.fixture(autouse=True)
def gecici_db(tmp_path, monkeypatch):
    kopya = tmp_path / "test.db"
    shutil.copy(KOK / "data" / "muhasebe.db", kopya)
    monkeypatch.setattr(db, "DB_YOLU", kopya)
    monkeypatch.setattr(db, "_SEMA_GUNCEL", False)
    db.baglan().execute("DELETE FROM planli_islemler").connection.commit()  # kopyada temiz başla


def belge(metin, kaynak="x.txt"):
    return SimpleNamespace(page_content=metin, metadata={"kaynak": kaynak})


# --- A: uydurma yüzde/sayı yakalanır ("ev satın alma ücreti %15" hatası) ---
def test_uydurma_yuzde_yakalanir():
    doc = belge("Brüt ücret toplamı: 143.002,73 TL\nMuhtasar ödenecek tutar: 21.450,41 TL")
    k = kanit_eslestir("Ev satın alma ücreti genellikle %15'lik bir tutardır.", [doc])
    assert "15" in k["uydurma_sayilar"]


def test_dogru_sayilar_gecer():
    doc = belge("KDV beyannamesi dönemi izleyen ayın 28'i akşamına kadar verilir. Ödenecek KDV: 44.307,46 TL")
    assert kanit_eslestir("Ayın 28'ine kadar verilir; ödenecek KDV 44.307,46 TL.", [doc])["uydurma_sayilar"] == []


# --- D/E: niyet kod kuralları (model 'belge' dese bile) ---
@pytest.mark.parametrize("soru, sorgu, parametreler", [
    ("Ekim faturalarımı göster", "faturalar", ["2026-10"]),
    ("eylül ayında kaç tl gecikmiş ödemem vardı", "gec_odenenler", []),
    ("son 1 sene içinde ödediğim gecikmiş ödeme tutarı nedir", "gec_odenenler", []),
    ("Gecikmiş ödemem var mı?", "gecikmis", []),
    # Yaklaşan ödemeler: kaç tane istenirse o kadar (rakam ya da yazıyla)
    ("önümüzdeki en yakın 3 ödemeyi göster", "yaklasanlar", ["3"]),
    ("en yakın 4 ödememi göster", "yaklasanlar", ["4"]),
    ("sıradaki beş ödemem ne", "yaklasanlar", ["5"]),
    ("önümüzdeki 6 tane ödemeyi listele", "yaklasanlar", ["6"]),
    ("2 yaklaşan ödememi göster", "yaklasanlar", ["2"]),
    ("en yakın on iki ödeme", "yaklasanlar", ["12"]),
    ("önümüzeki 4 ödeme ne kadar", "yaklasanlar", ["4"]),  # yazım hatası (model Temmuz uydurmuştu)
    ("siradaki 2 odeme", "yaklasanlar", ["2"]),
    ("gelecek 3 ödemem ne", "yaklasanlar", ["3"]),
    # Ay toplamı: bu ay/gelecek -> ödenecekler, geçmiş ay -> o ay ödenenler
    ("kasım ayında gelen toplam ödeme ne kadar", "ay_odemeleri", ["2026-11"]),
    ("ekim ayında toplam ödeme ne kadar", "odenenler", ["2026-10"]),
])
def test_niyet_kurallari(soru, sorgu, parametreler):
    n = kural_duzelt(soru, {"niyet": "belge", "sorgu": None, "parametreler": []})
    assert (n["niyet"], n["sorgu"], n["parametreler"]) == ("kayit", sorgu, parametreler)


@pytest.mark.parametrize("adet", ["3", "4"])
def test_yaklasanlar_istenen_adet_kadar(adet):
    r = cevapla_kayit("en yakın ödemeler", "F001", {"sorgu": "yaklasanlar", "parametreler": [adet]})
    assert len(r["satirlar"]) == int(adet)
    assert r["cevap"].startswith(f"Sıradaki {adet} ödemeniz")


def test_yaklasanlar_az_kayit_varsa_soyler():
    r = cevapla_kayit("en yakın 10 ödeme", "F001", {"sorgu": "yaklasanlar", "parametreler": ["10"]})
    assert len(r["satirlar"]) < 10 and "10 ödeme istediniz" in r["cevap"]


@pytest.mark.parametrize("soru", ["SGK primini geç ödersem ne olur?", "Geçici vergi ne zaman ödenir?"])
def test_genel_sorular_belge_kalir(soru):
    assert kural_duzelt(soru, {"niyet": "belge", "sorgu": None, "parametreler": []})["niyet"] == "belge"


def test_fatura_odeme_plani_fatura_sorgusu_degil():
    n = kural_duzelt("elektrik faturası 10 Aralık ödeyeceğim", {"niyet": "belge", "sorgu": None, "parametreler": []})
    assert n.get("sorgu") != "faturalar"


# --- E: geç ödenenler, şu anki gecikmişten AYRI ---
def test_gec_odenenler():
    assert cevapla_kayit("x", "F001", {"sorgu": "gec_odenenler", "parametreler": []})["cevap"].startswith(
        "Kayıtlarınıza göre geç ödenmiş bir ödemeniz yok")
    con = db.baglan()  # Eylül SGK'yı (son tarih 31.10) 03.11'de ödenmiş gibi yap
    con.execute("UPDATE yukumlulukler SET odeme_tarihi = '2026-11-03' WHERE id = 'Y015'")
    con.commit()
    satirlar = db.calistir("gec_odenenler", "F001")
    assert [s["id"] for s in satirlar] == ["Y015"]
    assert db.calistir("gecikmis", "F001") == []  # ödenmiş olduğu için "şu an gecikmiş" DEĞİL


# --- C: kendi kayıtlarında açıklamaya göre arama ---
def test_aciklama_aramasi():
    db.planli_islem_ekle("F001", 1, "Gelir", "2026-11-11", 450000, "Ev satın alma ücreti")
    db.planli_islem_ekle("F002", 2, "Gelir", "2026-11-11", 999, "Ev satın alma ücreti başka firma")
    r = planli_aciklama_cevabi("ev satın alma ücreti ne", "F001")
    assert r and "450.000,00 TL" in r["cevap"] and "999" not in r["cevap"]
    assert planli_aciklama_cevabi("Geçici vergi ne zaman ödenir?", "F001") is None


# --- Model soruda olmayan bir ay uydurursa soru kazanır ---
@pytest.mark.parametrize("soru, sorgu, parametreler", [
    ("önümüzeki 4 ödeme ne kadar", "yaklasanlar", ["4"]),
    ("gelecek ay ödemelerim", "ay_odemeleri", ["2026-12"]),
    ("önümüzeki ay ödemelerim", "ay_odemeleri", ["2026-12"]),
])
def test_uydurulan_ay_duzeltilir(soru, sorgu, parametreler):
    model = {"niyet": "kayit", "sorgu": "odenenler", "parametreler": ["2026-07"]}  # arayüzde görülen
    n = kural_duzelt(soru, model)
    assert (n["sorgu"], n["parametreler"]) == (sorgu, parametreler)


# --- Tahmin: "önümüzdeki ay SGK primini tahmin et" RAG'a gidip alakasız cevap veriyordu ---
@pytest.mark.parametrize("soru, parametreler", [
    ("önümüzdeki ay sgk primini tahmin eder misin", ["2026-12", "SGK primi"]),
    ("gelecek ay ne kadar vergi ödeyeceğimi tahmin et", ["2026-12"]),
    ("aralık KDV tahmini", ["2026-12", "KDV"]),
])
def test_tahmin_niyeti(soru, parametreler):
    n = kural_duzelt(soru, {"niyet": "belge", "sorgu": None, "parametreler": []})
    assert (n["niyet"], n["sorgu"], n["parametreler"]) == ("kayit", "tahmin", parametreler)


def test_tahmin_son_3_donem_ortalamasi():
    r = cevapla_kayit("x", "F001", {"sorgu": "tahmin", "parametreler": ["2026-12", "SGK primi"]})
    gecmis = db.calistir("donem_gecmisi", "F001", "SGK primi")
    ort = round(sum(g["tutar_tl"] for g in gecmis) / len(gecmis), 2)
    assert len(gecmis) == 3 and tl(ort) in r["cevap"] and "tahmindir" in r["cevap"]


def test_tahmin_kayit_varsa_gercek_tutar():
    r = cevapla_kayit("x", "F001", {"sorgu": "tahmin", "parametreler": ["2026-11", "KDV"]})
    assert "tahmin değil, kayıtta var" in r["cevap"] and "tahmindir" not in r["cevap"]


# --- Maaş soruları RAG'da "kayıtlarınızda yok" diyordu; beyannamedeki brüt ücretten hesaplanır ---
def test_bordro_toplam_ve_ortalama():
    kayitlar = bordro_kayitlari("F001")
    son = kayitlar[-1]
    toplam = bordro_cevabi("bir ayda ödenen toplam maaş miktarı ne kadar", "F001")
    assert tl(son["brut"]) in toplam["cevap"] and toplam["kaynaklar"] == [son["kaynak"]]
    ort = bordro_cevabi("ortalama net maaş ne kadar", "F001")
    assert "Net maaş tutarı kayıtlarınızda yok" in ort["cevap"]  # net UYDURULMAZ
    assert tl(round(son["brut"] / son["calisan"], 2)) in ort["cevap"]


def test_bordro_birkac_ay_ve_olmayan_ay():
    r = bordro_cevabi("son 3 ayda ödenen maaşlar", "F001")
    assert len(r["kaynaklar"]) == 3 and "Toplam" in r["cevap"]
    assert "kayıtlarınızda yok" in bordro_cevabi("ocak ayı maaşları", "F001")["cevap"]


@pytest.mark.parametrize("soru", ["ev satın alma ücreti ne", "KDV ne zaman ödenir?"])
def test_bordro_disindaki_sorular_ragda_kalir(soru):
    assert bordro_cevabi(soru, "F001") is None


def test_bordro_firma_izolasyonu():
    assert all(k["kaynak"].startswith("F002_") for k in bordro_kayitlari("F002"))
