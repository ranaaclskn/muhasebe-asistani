"""Nakit akış tablosu ve hareket dökümü testleri (app/nakit.py, ui/tablolar.py).

Model GEREKMEZ. Gerçek veritabanına dokunmaz: data/muhasebe.db'nin geçici KOPYASINDA çalışır.
Çalıştır (proje klasöründen):  python -m pytest -q tests/test_nakit.py
"""
import shutil
import sys
from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import load_workbook

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import app.db as db  # noqa: E402
from app import nakit  # noqa: E402
from ui.tablolar import excel_raporu, nakit_html  # noqa: E402

FIRMALAR = ["F001", "F002", "F003"]


@pytest.fixture(autouse=True)
def gecici_db(tmp_path, monkeypatch):
    kopya = tmp_path / "test.db"
    shutil.copy(KOK / "data" / "muhasebe.db", kopya)
    monkeypatch.setattr(db, "DB_YOLU", kopya)
    monkeypatch.setattr(db, "_SEMA_GUNCEL", False)


def tablo(firma, son_n=None):
    liste = nakit.hareketler(firma)
    aylar = nakit.donem_aylari(liste, son_n)
    return liste, aylar, {s["tip"] + (s["ad"] if s["tip"] in ("kalem", "alt") else ""): s
                          for s in nakit.nakit_akis_tablosu(liste, aylar)}


@pytest.mark.parametrize("firma", FIRMALAR)
def test_aylik_net_gelir_gider_grafigiyle_birebir_ayni(firma):
    _, aylar, t = tablo(firma)
    beklenen = {}
    for r in db.aylik_gelir_gider(firma):
        beklenen[r["ay"]] = beklenen.get(r["ay"], 0) + (r["tutar"] if r["yon"] == "Gelir" else -r["tutar"])
    for ay in aylar:
        assert t["net"]["degerler"][ay] == pytest.approx(beklenen.get(ay, 0), abs=0.01)


@pytest.mark.parametrize("firma", FIRMALAR)
def test_toplamlar_ve_kumulatif_tutarli(firma):
    _, aylar, t = tablo(firma, 3)
    for ay in aylar:
        assert t["toplam_giris"]["degerler"][ay] + t["toplam_cikis"]["degerler"][ay] == \
            pytest.approx(t["net"]["degerler"][ay], abs=0.01)
        assert t["toplam_giris"]["degerler"][ay] >= 0 and t["toplam_cikis"]["degerler"][ay] <= 0  # ödemeler eksi
    devir = t["devir"]["degerler"][aylar[0]]
    assert t["kumulatif"]["toplam"] == pytest.approx(devir + t["net"]["toplam"], abs=0.01)


def test_musteri_ve_satici_kirilimi_kalem_toplamina_esit():
    liste, aylar, _ = tablo("F001")
    satirlar = nakit.nakit_akis_tablosu(liste, aylar)
    for kod in nakit.ALT_KIRILIM:
        kalem = next(s for s in satirlar if s["tip"] == "kalem" and s["kod"] == kod)
        altlar = [s for s in satirlar if s["tip"] == "alt" and s["kod"] == kod]
        assert len(altlar) >= 2
        assert sum(s["toplam"] for s in altlar) == pytest.approx(kalem["toplam"], abs=0.01)


def test_hareket_listesi_tum_kaynaklari_icerir_ve_firmaya_ozeldir():
    liste = nakit.hareketler("F001")
    con = db.baglan()
    fatura = con.execute("SELECT COUNT(*) FROM faturalar WHERE firma_id = 'F001'").fetchone()[0]
    maas = con.execute("SELECT COUNT(DISTINCT donem) FROM bordrolar WHERE firma_id = 'F001'").fetchone()[0]
    vergi = con.execute("SELECT COUNT(*) FROM yukumlulukler WHERE firma_id = 'F001'").fetchone()[0]
    plan = con.execute("SELECT COUNT(*) FROM planli_islemler WHERE firma_id = 'F001'").fetchone()[0]
    assert len(liste) == fatura + maas + vergi + plan
    assert not any("Lojistik" in h["karsi_taraf"] or "Butik" in h["karsi_taraf"] for h in liste)  # başka firma yok
    assert [h["tarih"] for h in liste] == sorted(h["tarih"] for h in liste)
    with pytest.raises(ValueError):
        nakit.hareketler("F001' OR 1=1 --")


def test_geciken_vergi_hareketi_gecikti_ve_vade_son_odeme_tarihi(monkeypatch):
    monkeypatch.setattr(db, "BUGUN", "2026-11-21")
    h = next(h for h in nakit.hareketler("F001") if h["kaynak"] == "Y020")
    assert (h["kod"], h["durum"], h["vade"], h["yon"]) == (54, "Gecikti", "2026-11-17", "Çıkış")


def test_excel_raporu_uc_sayfa_ve_net_satiri():
    liste, aylar, t = tablo("F001", 6)
    wb = load_workbook(BytesIO(excel_raporu("Demo Gıda", nakit.nakit_akis_tablosu(liste, aylar), aylar, liste)))
    assert wb.sheetnames == ["Nakit Akış", "Hareket", "Kodlar"]
    net = next(r for r in wb["Nakit Akış"].iter_rows(min_row=5, values_only=True) if r[1] == "NET NAKİT AKIŞI")
    assert net[-1] == pytest.approx(t["net"]["toplam"], abs=0.01)
    hs = wb["Hareket"]
    assert hs.cell(hs.max_row, 8).value.startswith("=SUBTOTAL(9,H4:")  # filtreye duyarlı toplam
    assert hs.max_row - 4 == len(liste)


def test_html_tablo_eksi_tutar_ve_plan_sutunu():
    liste, aylar, _ = tablo("F001")
    h = nakit_html(nakit.nakit_akis_tablosu(liste, aylar), aylar)
    assert "TOPLAM TAHSİLAT" in h and "NET NAKİT AKIŞI" in h and 'class="eksi">−' in h
    assert ("<small>Plan</small>" in h) == any(a > db.BUGUN[:7] for a in aylar)
