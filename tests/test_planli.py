"""Kullanıcının eklediği planlı ödeme/tahsilat kayıtları: ekleme, doğrulama, firma izolasyonu,
sorgular ve cevap biçimi. Model GEREKMEZ (niyet kod kurallarıyla test edilir).
Gerçek veritabanına dokunmaz: data/muhasebe.db'nin geçici KOPYASINDA çalışır.
Çalıştır (proje klasöründen):  python -m pytest -q tests/test_planli.py
"""
import shutil
import sys
from pathlib import Path

import pytest

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import app.db as db  # noqa: E402
from app.kayit import cevapla_kayit  # noqa: E402
from app.niyet import kural_duzelt  # noqa: E402


@pytest.fixture(autouse=True)
def gecici_db(tmp_path, monkeypatch):
    kopya = tmp_path / "test.db"
    shutil.copy(KOK / "data" / "muhasebe.db", kopya)
    monkeypatch.setattr(db, "DB_YOLU", kopya)
    monkeypatch.setattr(db, "_SEMA_GUNCEL", False)  # yeni tablo kopyada da oluşsun
    # Kullanıcının gerçek DB'ye eklediği kayıtlar testleri etkilemesin: kopyada temiz başla
    db.baglan().execute("DELETE FROM planli_islemler").connection.commit()


@pytest.fixture
def ornek_kayitlar():
    db.planli_islem_ekle("F001", 1, "Gider", "2026-12-05", 20000, "Aralık kirası", "Ev sahibi")
    db.planli_islem_ekle("F001", 1, "Gider", "2026-12-20", 7500.5, "Ambalaj tedarikçisi")
    db.planli_islem_ekle("F001", 1, "Gelir", "2026-12-15", 45000, "Kent Market faturası", "Kent Market")
    db.planli_islem_ekle("F002", 2, "Gider", "2026-12-05", 99999, "Başka firmanın kirası")


def test_ekleme_ve_dogrulama():
    no = db.planli_islem_ekle("F001", 1, "Gider", "2026-12-05", "1234.567", "  Kira  ")
    r = db.planli_islemler("F001")[0]
    assert r["id"] == no and r["tutar_tl"] == 1234.57 and r["aciklama"] == "Kira"
    for hatali in [dict(yon="Borç"), dict(tarih="05.12.2026"), dict(tutar_tl=0), dict(tutar_tl=-5),
                   dict(aciklama="")]:
        args = dict(yon="Gider", tarih="2026-12-05", tutar_tl=100, aciklama="Kira") | hatali
        with pytest.raises(ValueError):
            db.planli_islem_ekle("F001", 1, **args)
    with pytest.raises(ValueError):  # firma_id biçimi de denetlenir
        db.planli_islem_ekle("F001' OR 1=1", 1, "Gider", "2026-12-05", 100, "Kira")


def test_firma_izolasyonu(ornek_kayitlar):
    assert all("Başka firmanın" not in r["aciklama"] for r in db.planli_islemler("F001"))
    f2 = db.planli_islemler("F002")[0]["id"]
    assert db.planli_islem_sil(f2, "F001") is False  # F001 başka firmanın kaydını silemez
    assert len(db.planli_islemler("F002")) == 1


def test_sorgular(ornek_kayitlar):
    odeme = db.calistir("planli_odemeler", "F001", "2026-12")
    assert [r["aciklama"] for r in odeme] == ["Aralık kirası", "Ambalaj tedarikçisi"]
    assert [r["aciklama"] for r in db.calistir("beklenen_tahsilatlar", "F001")] == ["Kent Market faturası"]
    assert len(db.calistir("nakit_plani", "F001", "2026-12")) == 3
    assert db.calistir("planli_odemeler", "F001", "2027-01") == []


def test_resmi_kayitlar_etkilenmez(ornek_kayitlar):
    # "Bu ay ne ödeyeceğim" yalnız muhasebecinin resmî kayıtlarından gelir (T02 değişmez)
    satirlar = db.calistir("ay_odemeleri", "F001", "2026-11")
    assert round(sum(s["tutar_tl"] for s in satirlar), 2) == 165469.58


@pytest.mark.parametrize("soru, sorgu, parametreler", [
    ("Aralıkta planladığım ödemeler neler?", "planli_odemeler", ["2026-12"]),
    ("Müşterilerden ne kadar tahsilat bekliyorum?", "beklenen_tahsilatlar", []),
    ("Gelecek ay alacaklarım ne kadar?", "beklenen_tahsilatlar", ["2026-12"]),
    ("Aralık nakit planım nasıl?", "nakit_plani", ["2026-12"]),
    ("Eklediğim ödemeler", "planli_odemeler", []),
])
def test_niyet_kod_kurallari(soru, sorgu, parametreler):
    # Model "belge" dese bile kesin kalıp kayıt yoluna çevirir
    n = kural_duzelt(soru, {"niyet": "belge", "sorgu": None, "parametreler": []})
    assert (n["niyet"], n["sorgu"], n["parametreler"]) == ("kayit", sorgu, parametreler)


def test_cevap_bicimi(ornek_kayitlar):
    c = cevapla_kayit("x", "F001", {"sorgu": "planli_odemeler", "parametreler": ["2026-12"]})["cevap"]
    assert "Aralık 2026 için 2 planlı ödemeniz var" in c and "05.12.2026 · Aralık kirası (Ev sahibi)" in c
    assert "**Toplam: 27.500,50 TL**" in c
    c = cevapla_kayit("x", "F001", {"sorgu": "nakit_plani", "parametreler": ["2026-12"]})["cevap"]
    assert "Beklenen giriş: 45.000,00 TL" in c and "Planlı çıkış: 27.500,50 TL" in c and "Net: +17.499,50 TL" in c
    c = cevapla_kayit("x", "F001", {"sorgu": "beklenen_tahsilatlar", "parametreler": ["2027-01"]})["cevap"]
    assert "eklediğiniz beklenen tahsilat yok" in c  # boş sonuç da anlamlı cevap
