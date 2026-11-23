"""Analiz araçları testleri (app/analiz.py): uyarılar, takvim, yaşlandırma, cari hesap, göstergeler, senaryo.

Model GEREKMEZ. Gerçek veritabanına dokunmaz: data/muhasebe.db'nin geçici KOPYASINDA, 21.11.2026 gününde çalışır.
Çalıştır (proje klasöründen):  python -m pytest -q tests/test_analiz.py
"""
import shutil
import sys
from pathlib import Path

import pytest

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import app.db as db  # noqa: E402
from app import analiz  # noqa: E402
from ui.analiz_gorunum import takvim_html  # noqa: E402


@pytest.fixture(autouse=True)
def ortam(tmp_path, monkeypatch):
    kopya = tmp_path / "test.db"
    shutil.copy(KOK / "data" / "muhasebe.db", kopya)
    monkeypatch.setattr(db, "DB_YOLU", kopya)
    monkeypatch.setattr(db, "_SEMA_GUNCEL", False)
    monkeypatch.setattr(db, "BUGUN", "2026-11-21")
    db.baglan().execute("DELETE FROM planli_islemler").connection.commit()  # kullanıcı kayıtları etkilemesin


def test_uyarilar_gecikme_ve_yaklasan_odeme():
    u = analiz.uyarilar("F001")
    assert u[0]["seviye"] == "kritik" and "54.938,65 TL" in u[0]["baslik"] and "Geçici vergi" in u[0]["detay"]
    yakin = next(x for x in u if x["baslik"].startswith("7 gün içinde"))
    assert "2 ödeme" in yakin["baslik"] and "Muhtasar" in yakin["detay"] and "KDV" in yakin["detay"]  # 26 ve 28.11


def test_uyari_yoksa_her_sey_yolunda(monkeypatch):
    monkeypatch.setattr(db, "BUGUN", "2026-07-01")  # temmuz başı: gecikme ve 7 gün içinde son tarih yok
    monkeypatch.setattr(analiz, "cari_ozet", lambda *a, **k: [])
    monkeypatch.setattr(analiz, "_ay_neti", lambda *a: 1)
    assert [u["seviye"] for u in analiz.uyarilar("F001")] == ["iyi"]


def test_yaslandirma_gecikme_gunune_gore():
    k = analiz.yaslandirma("F003")  # SGK primi 31.10 (21 gün), geçici vergi 17.11 (4 gün)
    assert k["1–30 gün gecikmiş"]["adet"] == 2
    assert k["1–30 gün gecikmiş"]["tutar"] == pytest.approx(21306.57 + 17223.80, abs=0.01)
    assert k["Vadesi gelmemiş"]["adet"] == 3 and k["60+ gün gecikmiş"]["adet"] == 0


def test_takvim_olaylari_firmaya_ozel_ve_html():
    olaylar = analiz.takvim_olaylari(["F001"])
    assert {o["firma_id"] for o in olaylar} == {"F001"}
    assert len(olaylar) == len(db.yukumlulukler("F001"))
    kasim = [o for o in olaylar if o["tarih"].startswith("2026-11")]
    h = takvim_html(2026, 11, kasim)
    assert 'class="olay Gecikti"' in h and 'class="olay Bekliyor"' in h and "Geçici vergi" in h


def test_cari_ozet_paylar_ve_ekstre():
    cari = analiz.cari_ozet("F001", 10)
    assert sum(c["pay"] for c in cari) == pytest.approx(1)
    assert [c["toplam"] for c in cari] == sorted((c["toplam"] for c in cari), reverse=True)
    ilk = cari[0]
    ekstre = analiz.cari_ekstre("F001", ilk["karsi_taraf"])
    assert len(ekstre) == ilk["adet"] and ekstre[-1]["bakiye"] == pytest.approx(ilk["toplam"], abs=0.01)


@pytest.mark.parametrize("firma", ["F001", "F002", "F003"])
def test_gostergeler_puan_bilesenlerin_toplami(firma):
    g = analiz.gostergeler(firma)
    assert 0 <= g["puan"] <= 100
    assert g["puan"] == pytest.approx(sum(b[1] for b in g["bilesenler"]), abs=1)
    assert all(0 <= p <= m for _, p, m, _ in g["bilesenler"])
    assert 0 <= g["zamaninda_oran"] <= 1


def test_gecikmesi_cok_olan_firmanin_zamaninda_odeme_orani_dusuk():
    assert analiz.gostergeler("F003")["zamaninda_oran"] < analiz.gostergeler("F001")["zamaninda_oran"] <= 1


def test_senaryo_degisiklik_yoksa_ayni_satis_artarsa_iyi_personel_artarsa_kotu():
    s0 = analiz.senaryo("F001", 0, 0, 0, 6)
    assert s0["fark"] == 0 and all(r["net_mevcut"] == r["net_senaryo"] for r in s0["aylar"])
    assert len(s0["aylar"]) == 6 and s0["aylar"][0]["ay"] == "2026-12"
    assert analiz.senaryo("F001", 10, 0, 0, 6)["fark"] > 0
    assert analiz.senaryo("F001", 0, 0, 3, 6)["fark"] < 0
    assert analiz.senaryo("F001", 0, -20, 0, 6)["fark"] > 0  # satıcı maliyeti düşerse nakit artar
