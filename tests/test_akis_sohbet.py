"""Çok adımlı sohbet (atölye 7. gün destek_grafi: interrupt + checkpoint) ve talep sorgulama kolu.
Model GEREKMEZ: niyet kod kurallarıyla belirlenir. Gerçek veritabanına dokunmaz (geçici kopya).
Çalıştır (proje klasöründen):  python -m pytest -q tests/test_akis_sohbet.py
"""
import shutil
import sys
from pathlib import Path

import pytest

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import app.akis as akis  # noqa: E402
import app.db as db  # noqa: E402
import app.niyet as niyet  # noqa: E402
from app.emirler import emir_cikar, emir_kalibi  # noqa: E402


def modelsiz_niyet(soru):
    if emir_kalibi(soru):
        return {"niyet": "islem", "sorgu": None, "parametreler": [], **emir_cikar(soru)}
    return niyet.kural_duzelt(soru, {"niyet": "belge", "sorgu": None, "parametreler": []})


@pytest.fixture(autouse=True)
def ortam(tmp_path, monkeypatch):
    kopya = tmp_path / "test.db"
    shutil.copy(KOK / "data" / "muhasebe.db", kopya)
    monkeypatch.setattr(db, "DB_YOLU", kopya)
    monkeypatch.setattr(db, "_SEMA_GUNCEL", False)
    monkeypatch.setattr(akis, "niyet_belirle", modelsiz_niyet)
    monkeypatch.setattr(akis, "asistan", akis.akis_kur(tmp_path / "checkpoint.sqlite"))


def konus(firma, *mesajlar):
    """İlk mesaj yeni soru, sonrakiler bekleyen sorulara cevap. Her adımın sonucunu döndürür."""
    s = akis.sor(mesajlar[0], firma, 1)
    adimlar = [s]
    for m in mesajlar[1:]:
        assert s["bekleyen"], f"cevap beklenmiyordu: {s['cevap']}"
        s = akis.devam(m, s["thread_id"])
        adimlar.append(s)
    return adimlar


def son_talep():
    return db.baglan().execute("SELECT * FROM talepler ORDER BY id DESC LIMIT 1").fetchone()


def test_eksik_bilgiyi_tek_tek_sorar_sonra_onay_ister():
    a = konus("F001", "Beyannamemi e-postama gönder", "KDV", "Eylül", "evet")
    assert a[0]["bekleyen"]["alan"] == "belge_turu" and "Hangi beyanname" in a[0]["cevap"]
    assert a[1]["bekleyen"]["alan"] == "donem"
    assert a[2]["bekleyen"]["tur"] == "onay" and "F001_KDV_2026-09.txt" in a[2]["cevap"]
    assert a[3]["bekleyen"] is None and a[3]["arac"] == "talep"
    t = son_talep()
    assert t["durum"] == "Onay bekliyor" and t["emir"] == "belge_gonder" and "F001_KDV_2026-09" in t["ozet"]


def test_tek_cevapta_birden_fazla_alan():
    a = konus("F001", "Beyannamemi gönder", "Eylül KDV")
    assert a[1]["bekleyen"]["tur"] == "onay"  # belge türü + dönem aynı cevaptan alındı


def test_onaysiz_kayit_yazilmaz():
    once = son_talep()["id"]
    konus("F001", "Eylül KDV beyannamemi e-postama gönder", "hayır")
    assert son_talep()["id"] == once


def test_vazgec():
    once = son_talep()["id"]
    a = konus("F001", "Beyannamemi gönder", "vazgeç")
    assert a[1]["arac"] == "iptal" and son_talep()["id"] == once


def test_anlasilmayan_cevap_tekrar_sorar_sonra_iptal():
    a = konus("F001", "Beyannamemi gönder", "bilmiyorum", "hmm", "yok")
    assert "Anlayamadım" in a[1]["cevap"] and a[3]["arac"] == "iptal"


def test_planli_kayit_sohbetle():
    a = konus("F001", "kira ödeyeceğim, kaydet", "5 Aralık", "20 bin", "evet")
    assert [x["bekleyen"]["alan"] for x in a[:2]] == ["tarih", "tutar_tl"]
    assert "20.000,00 TL" in a[2]["cevap"] and a[3]["arac"] == "kayit"
    kayit = db.planli_islemler("F001")[-1]
    assert (kayit["tarih"], kayit["tutar_tl"], kayit["yon"]) == ("2026-12-05", 20000.0, "Gider")


def test_belirsiz_emir_once_ne_yapilacagini_sorar():
    a = konus("F001", "Bunu oluştur", "Eylül KDV beyannamemi e-postama gönder", "evet")
    assert a[0]["bekleyen"]["alan"] == "emir" and a[2]["arac"] == "talep"


def test_talep_sorgulama_kolu():
    konus("F001", "Eylül KDV beyannamemi e-postama gönder", "evet")
    no = son_talep()["id"]
    s = akis.sor(f"{no} numaralı talebim ne durumda?", "F001")
    assert s["arac"] == "sorgula" and f"#{no}" in s["cevap"] and "Onay bekliyor" in s["cevap"]
    assert "bulunamadı" in akis.sor(f"{no} numaralı talebim ne durumda?", "F002")["cevap"]  # başka firma
    assert "Son talepleriniz" in akis.sor("Taleplerim ne oldu?", "F001")["cevap"]


def test_bilgi_sorulari_eskisi_gibi_tek_adim():
    s = akis.sor("Ekim faturalarımı göster", "F001")
    assert s["bekleyen"] is None and s["arac"] == "sql" and "73.229,25" in s["cevap"]


def test_model_ulasilamazsa_kurallara_doner(monkeypatch):
    class Kapali:
        def invoke(self, *a, **k):
            raise ConnectionError("Ollama kapalı")
    monkeypatch.setattr(niyet, "llm", lambda temperature=0.0: Kapali())
    n = niyet.niyet_belirle("Ekim SGK primi ödendi mi?")
    assert (n["niyet"], n["sorgu"], n["parametreler"]) == ("kayit", "durum", ["SGK primi", "2026-10"])
    assert "model_ulasilamadi" in n["hata"]
