"""Zamanlayıcı (öneri #7) testleri: aylık rapor e-postası (app/bildirim.aylik_rapor_gonder), n8n akış dosyası
(her sabah 09:00 hatırlatma, her ayın 1'i aylık rapor) ve n8n/gorev.sh izin listesi.

Model ve n8n GEREKMEZ: n8n'e giden istek sahte bir requests.post ile yakalanır. Gerçek veritabanına dokunmaz.
Çalıştır (proje klasöründen):  python -m pytest -q tests/test_zamanlayici.py
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import app.db as db  # noqa: E402
from app import bildirim  # noqa: E402
from tests.test_bildirim import SahteN8n  # noqa: E402

AKISLAR = json.loads((KOK / "n8n" / "akislar.json").read_text(encoding="utf-8"))


@pytest.fixture()
def n8n(tmp_path, monkeypatch):
    kopya = tmp_path / "test.db"
    shutil.copy(KOK / "data" / "muhasebe.db", kopya)
    monkeypatch.setattr(db, "DB_YOLU", kopya)
    monkeypatch.setattr(db, "_SEMA_GUNCEL", False)
    monkeypatch.setattr(db, "BUGUN", "2026-11-21")
    sahte = SahteN8n()
    monkeypatch.setattr(bildirim.requests, "post", sahte)
    return sahte


# ---------- Aylık rapor e-postası ----------
def test_aylik_rapor_pdf_ekiyle_kayitli_adrese_muhasebeci_cc(n8n):
    r = bildirim.aylik_rapor_gonder("F002", "2026-10")
    assert r["ok"] and r["eposta"] == "yazilim@demo.local" and r["cc"] == "muhasebe@demo.local"
    istek = n8n.istekler[0]
    assert istek["url"].endswith("/webhook/aylik-rapor")
    ad, icerik, tur = istek["ek"]
    assert ad == "aylik_rapor_F002_2026-10.pdf" and tur == "application/pdf" and icerik.startswith(b"%PDF")
    v = istek["veri"]
    assert v["eposta"] == "yazilim@demo.local" and v["cc"] == "muhasebe@demo.local"
    assert "Ekim 2026" in v["konu"] and "Demo Yazılım" in v["konu"]
    assert "Finansal sağlık puanı" in v["metin"] and "TL" in v["metin"]


def test_rapor_metnindeki_rakamlar_raporla_ayni(n8n):
    from app.kayit import tl
    from app.rapor import rapor_verisi
    bildirim.aylik_rapor_gonder("F001", "2026-10")
    o = rapor_verisi("F001", "2026-10")["ozet"]
    metin = n8n.istekler[0]["veri"]["metin"]
    assert f"Tahsilat: {tl(o['giris'])}" in metin and f"Ödeme: {tl(o['cikis'])}" in metin


def test_varsayilan_ay_gecen_ay(n8n):
    assert bildirim.aylik_rapor_gonder("F003")["ay"] == "2026-10"


def test_n8n_kapaliysa_hata_doner_ve_patlamaz(n8n):
    n8n.calisiyor = False
    r = bildirim.aylik_rapor_gonder("F001", "2026-10")
    assert not r["ok"] and "ulaşılamadı" in r["hata"]


# ---------- n8n akış dosyası ----------
def _akis(kimlik):
    return next(a for a in AKISLAR if a["id"] == kimlik)


def test_bes_akis_ve_kimlikler_16_karakter():
    assert [a["id"] for a in AKISLAR] == ["MuhasebeTalepOn1", "MuhasebeHatirla1", "MuhasebeAylikRp1",
                                          "MuhasebeSabah091", "MuhasebeAyBasi01"]
    assert all(len(a["id"]) == 16 for a in AKISLAR)  # n8n iş akışı kimliği biçimi
    kur = (KOK / "n8n" / "kur.sh").read_text(encoding="utf-8")
    assert all(a["id"] in kur for a in AKISLAR)  # hepsi yayınlanıyor


@pytest.mark.parametrize("kimlik, cron, gorev", [("MuhasebeSabah091", "0 9 * * *", "hatirlatma"),
                                                 ("MuhasebeAyBasi01", "30 8 1 * *", "aylik-rapor")])
def test_zamanlayici_cron_ve_komut(kimlik, cron, gorev):
    a = _akis(kimlik)
    tetik, komut = a["nodes"]
    assert tetik["type"] == "n8n-nodes-base.scheduleTrigger"
    assert tetik["parameters"]["rule"]["interval"] == [{"field": "cronExpression", "expression": cron}]
    assert a["settings"]["timezone"] == "Europe/Istanbul"
    assert komut["type"] == "n8n-nodes-base.executeCommand"
    assert komut["parameters"]["command"] == f'bash "__PROJE__/n8n/gorev.sh" {gorev}'  # yalnızca gorev.sh
    assert a["connections"][tetik["name"]]["main"][0][0]["node"] == komut["name"]


def test_aylik_rapor_webhooku_ekli_ve_cc_li():
    a = _akis("MuhasebeAylikRp1")
    webhook, eposta = a["nodes"]
    assert webhook["parameters"]["path"] == "aylik-rapor"
    assert eposta["parameters"]["options"]["fileAttachments"] == "ek"
    assert eposta["parameters"]["options"]["ccEmail"] == "={{ $json.body.cc }}"
    assert eposta["credentials"]["smtp"]["id"] == "MuhasebeSmtpYrl1"


@pytest.mark.parametrize("betik", ["baslat.sh", "kur.sh"])  # kur.sh'de yoksa yayınlama düğümü tanımaz
def test_execute_command_n8n_betiklerinde_acilir_localfiletrigger_kapali(betik):
    metin = (KOK / "n8n" / betik).read_text(encoding="utf-8")
    assert """export NODES_EXCLUDE='["n8n-nodes-base.localFileTrigger"]'""" in metin


def test_n8n_yalnizca_yerelde_dinler():
    assert "N8N_LISTEN_ADDRESS=127.0.0.1" in (KOK / "n8n" / "baslat.sh").read_text(encoding="utf-8")


# ---------- n8n/gorev.sh izin listesi ----------
@pytest.mark.parametrize("gorev", ["", "yok", "hatirlatma; ls", "../hatirlatma", "aylik-rapor --ay 2020-01"])
def test_gorev_betigi_izinsiz_gorevi_reddeder(gorev):
    r = subprocess.run(["bash", str(KOK / "n8n" / "gorev.sh"), gorev], capture_output=True, text=True, timeout=30)
    assert r.returncode == 2 and "Bilinmeyen görev" in r.stderr
