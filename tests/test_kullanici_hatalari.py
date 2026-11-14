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
from app.kayit import cevapla_kayit, planli_aciklama_cevabi  # noqa: E402
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
])
def test_niyet_kurallari(soru, sorgu, parametreler):
    n = kural_duzelt(soru, {"niyet": "belge", "sorgu": None, "parametreler": []})
    assert (n["niyet"], n["sorgu"], n["parametreler"]) == ("kayit", sorgu, parametreler)


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
