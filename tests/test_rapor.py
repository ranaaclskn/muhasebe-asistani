"""Aylık yönetici raporu testleri (app/rapor.py): rakamlar paneldeki fonksiyonlarla birebir aynı mı, PDF üretiliyor mu.

Model GEREKMEZ. Gerçek veritabanına dokunmaz: data/muhasebe.db'nin geçici KOPYASINDA, 21.11.2026 gününde çalışır.
Çalıştır (proje klasöründen):  python -m pytest -q tests/test_rapor.py
"""
import re
import shutil
import sys
from pathlib import Path

import pytest

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import app.db as db  # noqa: E402
from app import analiz, rapor  # noqa: E402
from app.nakit import hareketler, nakit_akis_tablosu  # noqa: E402


@pytest.fixture(autouse=True)
def ortam(tmp_path, monkeypatch):
    kopya = tmp_path / "test.db"
    shutil.copy(KOK / "data" / "muhasebe.db", kopya)
    monkeypatch.setattr(db, "DB_YOLU", kopya)
    monkeypatch.setattr(db, "_SEMA_GUNCEL", False)
    monkeypatch.setattr(db, "BUGUN", "2026-11-21")
    db.baglan().execute("DELETE FROM planli_islemler").connection.commit()  # kullanıcı kayıtları etkilemesin


def test_varsayilan_ay_gecen_ay_ve_yil_donumu(monkeypatch):
    assert rapor.varsayilan_ay() == "2026-10"
    assert rapor.secilebilir_aylar(3) == ["2026-10", "2026-09", "2026-08"]
    monkeypatch.setattr(db, "BUGUN", "2027-01-05")
    assert rapor.varsayilan_ay() == "2026-12"


@pytest.mark.parametrize("firma", ["F001", "F002", "F003"])
def test_ay_ozeti_nakit_akis_tablosuyla_ayni(firma):
    v = rapor.rapor_verisi(firma, "2026-10")
    tablo = {s["tip"]: s for s in nakit_akis_tablosu(hareketler(firma), ["2026-10"])}
    assert v["ozet"]["giris"] == pytest.approx(tablo["toplam_giris"]["toplam"], abs=0.01)
    assert v["ozet"]["cikis"] == pytest.approx(-tablo["toplam_cikis"]["toplam"], abs=0.01)
    assert v["ozet"]["net"] == pytest.approx(tablo["net"]["toplam"], abs=0.01)
    # kalem dökümü ve grafiğin son çubuğu aynı toplamı verir
    assert sum(k["tutar"] for k in v["kalemler"] if k["yon"] == "Giriş") == pytest.approx(v["ozet"]["giris"], abs=0.01)
    assert sum(k["tutar"] for k in v["kalemler"] if k["yon"] == "Çıkış") == pytest.approx(v["ozet"]["cikis"], abs=0.01)
    assert v["grafik"][-1]["ay"] == "2026-10" and v["grafik"][-1]["net"] == pytest.approx(v["ozet"]["net"], abs=0.01)
    assert len(v["grafik"]) == len(v["aylar"]) == rapor.AY_SAYISI


def test_onceki_ay_degisimi_ve_musteri_paylari():
    v = rapor.rapor_verisi("F001", "2026-10")
    eylul = rapor.rapor_verisi("F001", "2026-09")["ozet"]
    assert v["ozet"]["onceki_net"] == pytest.approx(eylul["net"], abs=0.01)
    assert v["ozet"]["giris_degisim"] == pytest.approx((v["ozet"]["giris"] - eylul["giris"]) / eylul["giris"])
    m = v["musteriler"]
    assert 0 < len(m) <= 5 and m == sorted(m, key=lambda x: -x["tutar"])
    assert all(0 < x["pay"] <= 1 for x in m + v["saticilar"])


def test_guncel_durum_panelle_ayni():
    v = rapor.rapor_verisi("F001")
    assert v["saglik"]["puan"] == analiz.gostergeler("F001")["puan"]
    assert v["uyarilar"] == analiz.uyarilar("F001")
    gecikti = [o for o in v["odemeler"] if o["durum"] == "Gecikti"]
    assert gecikti and gecikti[0]["ad"] == "Geçici vergi" and gecikti[0]["gun"] < 0  # 17.11.2026
    assert all(o["gun"] <= 30 for o in v["odemeler"]) and v["odemeler"] == sorted(v["odemeler"], key=lambda o: o["tarih"])


def test_planli_odeme_30_gun_icindeyse_listede():
    db.planli_islem_ekle("F001", 1, "Gider", "2026-12-05", 12000, "Bilgisayar alımı")
    db.planli_islem_ekle("F001", 1, "Gider", "2027-02-01", 5000, "Uzak plan")
    adlar = [o["ad"] for o in rapor.rapor_verisi("F001")["odemeler"]]
    assert "Bilgisayar alımı" in adlar and "Uzak plan" not in adlar


def test_pdf_iki_sayfa_ve_gecerli():
    b = rapor.rapor_pdf("F002", "2026-10")
    assert b.startswith(b"%PDF") and b.rstrip().endswith(b"%%EOF")
    assert len(re.findall(rb"/Type /Page\b", b)) == 2
    assert rapor.dosya_adi("F002", "2026-10") == "aylik_rapor_F002_2026-10.pdf"


def test_hareketsiz_ay_da_pdf_uretir():
    b = rapor.rapor_pdf("F001", "2025-01")  # verinin başlangıcından önce: tablolar "hareket yok" der
    assert b.startswith(b"%PDF")


def test_bilinmeyen_firma_reddedilir():
    with pytest.raises(ValueError):
        rapor.rapor_verisi("../F001")
