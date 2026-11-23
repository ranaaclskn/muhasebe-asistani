"""Asistanın analiz soruları testleri (app/analiz_sorulari.py): yönlendirme, senaryo parametreleri, cevaplar.

Model GEREKMEZ. Gerçek veritabanına dokunmaz: data/muhasebe.db'nin geçici KOPYASINDA, 21.11.2026 gününde çalışır.
Çalıştır (proje klasöründen):  python -m pytest -q tests/test_analiz_sorulari.py
"""
import csv
import shutil
import sys
from pathlib import Path

import pytest

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import app.db as db  # noqa: E402
from app import akis  # noqa: E402
from app.analiz_sorulari import analiz_cevabi, analiz_kalibi, senaryo_parametreleri  # noqa: E402
from app.kayit import cevapla_kayit  # noqa: E402
from app.niyet import kural_duzelt  # noqa: E402


@pytest.fixture(autouse=True)
def ortam(tmp_path, monkeypatch):
    kopya = tmp_path / "test.db"
    shutil.copy(KOK / "data" / "muhasebe.db", kopya)
    monkeypatch.setattr(db, "DB_YOLU", kopya)
    monkeypatch.setattr(db, "_SEMA_GUNCEL", False)
    monkeypatch.setattr(db, "BUGUN", "2026-11-21")
    db.baglan().execute("DELETE FROM planli_islemler").connection.commit()


@pytest.mark.parametrize("soru, sorgu", [
    ("Finansal sağlık puanım kaç?", "saglik"), ("Şirketim nasıl gidiyor?", "saglik"),
    ("En çok satış yaptığım müşteri kim?", "cari"), ("En büyük tedarikçim hangisi?", "cari"),
    ("Ege Otel Grubu ekstresi", "cari"),
    ("Satışlar %10 düşerse 6 ay sonra durumum ne olur?", "senaryo"), ("2 kişi işe alırsam ne olur?", "senaryo"),
    ("Nelere dikkat etmeliyim?", "uyarilar"),
])
def test_analiz_sorulari_tanınır(soru, sorgu):
    assert analiz_kalibi(soru)["sorgu"] == sorgu
    # model ne derse desin (ör. "ne olur" -> belge) kod kuralı analiz yoluna çevirir
    assert kural_duzelt(soru, {"niyet": "belge", "sorgu": None, "parametreler": []})["sorgu"] == sorgu


ESKI = ["SGK primini geç ödersem ne olur?", "son bir senede kaç kişi işe alındı", "bu yıl işe alınanlar kimler",
        "müşterilerden ne kadar tahsilat bekliyorum", "satış faturalarım ne kadar", "Ekim faturalarımı göster",
        "kaç kişi çalışıyor", "maaş giderleri geçen aya göre arttı mı", "gecikmiş ödemelerimin faizi ne kadar",
        "gecikme zammı oranı nedir", "önümüzdeki ay SGK primini tahmin et", "elektrik faturası 10 Aralık ödeyeceğim",
        "kira ödeyeceğim, kaydet", "Aralık nakit planım"]


@pytest.mark.parametrize("soru", ESKI + [r["soru"] for r in csv.DictReader(
    open(KOK / "data" / "csv" / "test_seti.csv", encoding="utf-8"))])
def test_eski_sorular_analiz_yoluna_kaymaz(soru):
    assert analiz_kalibi(soru) is None


@pytest.mark.parametrize("soru, beklenen", [
    ("Satışlar %10 düşerse 6 ay sonra durumum ne olur?", {"satis": -10, "alis": 0, "kisi": 0, "ay": 6}),
    ("2 kişi işe alırsam ne olur?", {"satis": 0, "alis": 0, "kisi": 2, "ay": 6}),
    ("Satıcı maliyetleri %5 artarsa 1 yıl sonra?", {"satis": 0, "alis": 5, "kisi": 0, "ay": 12}),
    ("satışlar yüzde 20 artarsa ve üç kişi işten çıkarırsam 3 ay sonra", {"satis": 20, "alis": 0, "kisi": -3, "ay": 3}),
    ("ciro %80 düşerse", {"satis": -50, "alis": 0, "kisi": 0, "ay": 6}),  # panel sınırı ±50
])
def test_senaryo_parametreleri(soru, beklenen):
    assert senaryo_parametreleri(soru) == beklenen


def test_saglik_cevabi_puan_ve_en_zayif_alanlar():
    c = analiz_cevabi("puanım", "F001", "saglik", [])["cevap"]
    assert "/ 100" in c and "Puanı en çok düşüren iki alan" in c and "resmî bir derecelendirme değildir" in c
    assert "23,5 / 25" in c and "23.5" not in c  # Türkçe ondalık


def test_cari_cevabi_liste_ve_ekstre():
    liste = analiz_cevabi("en çok satış yaptığım müşteri kim", "F001", "cari", ["musteri"])
    assert "En büyük müşteri" in liste["cevap"] and liste["satirlar"][0]["pay"] >= liste["satirlar"][-1]["pay"]
    ekstre = analiz_cevabi("Ege Otel Grubu ekstresi", "F001", "cari", ["musteri"])
    assert ekstre["cevap"].startswith("**Ege Otel Grubu** ile") and "Son işlemler" in ekstre["cevap"]
    satici = analiz_cevabi("Marmara Ambalaj cari hesabım", "F001", "cari", ["musteri"])  # satıcılarda bulunur
    assert satici["cevap"].startswith("**Marmara Ambalaj** ile") and "satıcı" in satici["cevap"]


def test_senaryo_cevabi_rakamlari_senaryo_fonksiyonuyla_ayni():
    from app.analiz import senaryo
    from app.kayit import tl
    r = analiz_cevabi("Satışlar %10 düşerse 6 ay sonra?", "F003", "senaryo", [])
    s = senaryo("F003", -10, 0, 0, 6)
    assert tl(s["aylar"][-1]["kumulatif_senaryo"]) in r["cevap"] and "satışlar %10 azalır" in r["cevap"]
    assert "−" + tl(abs(s["fark"])) in r["cevap"]  # eksi fark düzgün eksi işaretiyle


def test_senaryo_anlasilamazsa_ornek_verir():
    assert "anlayamadım" in analiz_cevabi("senaryo", "F001", "senaryo", [])["cevap"]


def test_uyari_cevabi_gecikmeyi_once_soyler():
    c = analiz_cevabi("nelere dikkat etmeliyim", "F001", "uyarilar", [])["cevap"]
    assert c.index("Acil") < c.index("Dikkat:") and "54.938,65 TL" in c


def test_sohbet_akisi_isealim_senaryosunu_bordroya_gondermez(monkeypatch, tmp_path):
    monkeypatch.setattr(akis, "niyet_belirle", lambda s: pytest.fail("modele gitmemeli"))
    monkeypatch.setattr(akis, "asistan", akis.akis_kur(tmp_path / "cp.sqlite"))
    s = akis.sor("2 kişi işe alırsam 6 ay sonra durumum ne olur?", "F001")
    assert s["arac"] == "sql" and "2 kişi işe alınır" in s["cevap"] and "24 → 26 çalışan" in s["cevap"]


def test_kayit_dagiticisi_analiz_sorgularini_cevaplar():
    r = cevapla_kayit("Finansal sağlık puanım kaç?", "F002", {"sorgu": "saglik", "parametreler": []})
    assert r["yontem"] == "analiz" and "Finansal sağlık puanınız" in r["cevap"]
