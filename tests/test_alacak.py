"""Alacak takibi (öneri #4) testleri: fatura vade/tahsil verisi, eski veritabanının güncellenmesi, nakit akışında
tahsil günü, açık alacaklar ve yaşlandırma, tahsil performansı, uyarı, sağlık puanı, asistan soruları ve ekran.

Model GEREKMEZ. Gerçek veritabanına dokunmaz: data/muhasebe.db'nin geçici KOPYASINDA, 21.11.2026 gününde çalışır.
Çalıştır (proje klasöründen):  python -m pytest -q tests/test_alacak.py
"""
import csv
import shutil
import sqlite3
import sys
from pathlib import Path

import pytest

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import app.db as db  # noqa: E402
from app import alacak, analiz  # noqa: E402
from app.analiz_sorulari import analiz_cevabi, analiz_kalibi  # noqa: E402
from app.nakit import hareketler  # noqa: E402

CSV = list(csv.DictReader(open(KOK / "data" / "csv" / "faturalar.csv", encoding="utf-8", newline="")))
SATIS = [f for f in CSV if f["tip"] == "Satış"]


@pytest.fixture(autouse=True)
def ortam(tmp_path, monkeypatch):
    kopya = tmp_path / "test.db"
    shutil.copy(KOK / "data" / "muhasebe.db", kopya)
    monkeypatch.setattr(db, "DB_YOLU", kopya)
    monkeypatch.setattr(db, "_SEMA_GUNCEL", False)
    monkeypatch.setattr(db, "BUGUN", "2026-11-21")
    db.baglan().execute("DELETE FROM planli_islemler").connection.commit()
    return kopya


# ---------- Veri (scripts/08_alacak_verisi.py) ----------
def test_veri_kurallari():
    assert all(f["vade_tarihi"] >= f["tarih"] for f in SATIS)
    assert all(not f["odeme_tarihi"] or f["odeme_tarihi"] >= f["tarih"] for f in SATIS)
    assert all(f["vade_tarihi"] == f["odeme_tarihi"] == f["tarih"] for f in CSV if f["tip"] == "Alış")
    hic = {"FT036", "FT056", "FT078"}  # bilerek hiç tahsil edilmeyen (yaşlandırmanın ileri kovaları dolsun)
    assert all(not f["odeme_tarihi"] for f in SATIS if f["id"] in hic)
    acilis = [f for f in CSV if f["id"].startswith("FA")]
    assert acilis and all(f["tarih"] < "2026-05-01" <= f["odeme_tarihi"] for f in acilis)  # Mayıs'tan sonra tahsil


def test_csv_satir_sonlari_crlf():
    assert (KOK / "data" / "csv" / "faturalar.csv").read_bytes().count(b"\r\n") == len(CSV) + 1


def test_eski_veritabani_kendiliginden_guncellenir(ortam, monkeypatch):
    con = sqlite3.connect(ortam)
    kolonlar = {r[1] for r in con.execute("PRAGMA table_info(faturalar)")}
    for k in ("vade_tarihi", "odeme_tarihi"):  # eski (kolonsuz) veritabanını taklit et
        if k in kolonlar:
            con.execute(f"ALTER TABLE faturalar DROP COLUMN {k}")
    con.execute("DELETE FROM faturalar WHERE id LIKE 'FA%'")
    con.commit()
    con.close()
    monkeypatch.setattr(db, "_SEMA_GUNCEL", False)
    satir = {r["id"]: dict(r) for r in db.baglan().execute("SELECT * FROM faturalar")}
    assert len(satir) == len(CSV)
    for f in CSV:
        assert satir[f["id"]]["vade_tarihi"] == f["vade_tarihi"]
        assert satir[f["id"]]["odeme_tarihi"] == (f["odeme_tarihi"] or None)


# ---------- Nakit akışı: satış parası tahsil günü girer ----------
def _hareket(firma, fatura_id):
    return next(h for h in hareketler(firma) if h["kaynak"] == fatura_id)


def test_tahsil_edilen_fatura_tahsil_gununde_girer():
    f = next(x for x in SATIS if x["odeme_tarihi"] and x["odeme_tarihi"] <= "2026-11-21" and x["odeme_tarihi"] != x["tarih"])
    h = _hareket(f["firma_id"], f["id"])
    assert (h["tarih"], h["durum"], h["belge_tarihi"], h["vade"]) == (f["odeme_tarihi"], "Gerçekleşti", f["tarih"],
                                                                     f["vade_tarihi"])


def test_tahsil_edilmeyen_fatura_vadesinde_gecikti_ya_da_bekliyor():
    h = _hareket("F003", "FT078")  # Moda Butik, vade 07.09.2026, hiç ödenmedi
    assert h["tarih"] == h["vade"] == "2026-09-07" and h["durum"] == "Gecikti"
    acik = [f for f in SATIS if not f["odeme_tarihi"] and f["vade_tarihi"] > "2026-11-21" and f["tarih"] <= "2026-11-21"]
    assert acik and _hareket(acik[0]["firma_id"], acik[0]["id"])["durum"] == "Bekliyor"


def test_bugune_gore_tahsil_durumu(monkeypatch):
    f = next(x for x in SATIS if "2026-11-12" <= (x["odeme_tarihi"] or "") <= "2026-11-21")
    monkeypatch.setattr(db, "BUGUN", "2026-11-11")  # tahsil gününden önce: henüz açık
    assert _hareket(f["firma_id"], f["id"])["durum"] in ("Bekliyor", "Gecikti")
    assert f["id"] in {a["id"] for a in alacak.acik_alacaklar(f["firma_id"])}
    monkeypatch.setattr(db, "BUGUN", "2026-11-21")  # tahsil gününden sonra: kapandı
    assert _hareket(f["firma_id"], f["id"])["durum"] == "Gerçekleşti"
    assert f["id"] not in {a["id"] for a in alacak.acik_alacaklar(f["firma_id"])}


def test_birikmis_nakit_tahsil_edilmeyeni_saymaz():
    g = analiz.gostergeler("F003")
    beklenen = sum((h["tutar"] if h["yon"] == "Giriş" else -h["tutar"]) for h in hareketler("F003")
                   if h["kod"] in analiz.GERCEK_KODLAR and h["tarih"] <= "2026-11-21"
                   and not (h["kod"] == 10 and h["durum"] != "Gerçekleşti"))
    assert g["birikmis"] == pytest.approx(beklenen, abs=0.01)
    assert g["satis"] > g["tahsilat"]  # büyüyen firmada tahsilat satışın gerisinde
    assert "Kârlılık" in [b[0] for b in g["bilesenler"]]


# ---------- Açık alacaklar, yaşlandırma, performans ----------
def test_acik_alacaklar_ve_yaslandirma_tutarli():
    for firma in ("F001", "F002", "F003"):
        acik = alacak.acik_alacaklar(firma)
        o = alacak.ozet(firma)
        k = alacak.yaslandirma(firma)
        assert o["acik_tutar"] == pytest.approx(sum(a["tutar"] for a in acik), abs=0.01)
        assert sum(v["tutar"] for v in k.values()) == pytest.approx(o["acik_tutar"], abs=0.01)
        assert sum(v["adet"] for v in k.values()) == o["acik_adet"] == len(acik)
        assert [a["gecikme_gun"] for a in acik] == sorted((a["gecikme_gun"] for a in acik), reverse=True)


def test_f003_moda_butik_60_gunu_gecmis():
    acik = alacak.acik_alacaklar("F003")
    assert acik[0]["id"] == "FT078" and acik[0]["musteri"] == "Moda Butik" and acik[0]["gecikme_gun"] == 75
    assert alacak.yaslandirma("F003")["60+ gün gecikmiş"]["adet"] == 1
    assert alacak.kova(0) == "Vadesi gelmemiş" and alacak.kova(31) == "31–60 gün gecikmiş"


def test_tahsil_performansi_elle_hesapla():
    from datetime import date
    bugun = "2026-11-21"
    f = [x for x in SATIS if x["firma_id"] == "F001" and x["odeme_tarihi"] and x["odeme_tarihi"] <= bugun]
    gun = [(date.fromisoformat(x["odeme_tarihi"]) - date.fromisoformat(x["tarih"])).days for x in f]
    o = alacak.ozet("F001")
    assert o["tahsil_adet"] == len(f) and o["ort_tahsil_gun"] == pytest.approx(sum(gun) / len(gun))
    assert 0 <= o["zamaninda_oran"] <= 1 and o["dso_gun"] > 0
    mp = alacak.musteri_performansi("F001")
    assert {m["musteri"] for m in mp} == {x["karsi_taraf"].replace(" (kurgusal)", "") for x in SATIS
                                          if x["firma_id"] == "F001"}
    assert sum(m["acik"] for m in mp) == pytest.approx(o["acik_tutar"], abs=0.01)


def test_baska_firma_reddedilir():
    with pytest.raises(ValueError):
        alacak.acik_alacaklar("../F001")


# ---------- Uyarı ----------
def test_vadesi_gecmis_alacak_uyarisi_ve_onem_sirasi():
    u = analiz.uyarilar("F003")
    alacak_u = next(x for x in u if x["baslik"].startswith("Vadesi geçmiş"))
    assert alacak_u["seviye"] == "kritik" and "Moda Butik" in alacak_u["detay"]  # 60+ gün -> kritik
    sira = ["kritik", "uyari", "bilgi", "iyi"]
    assert [sira.index(x["seviye"]) for x in u] == sorted(sira.index(x["seviye"]) for x in u)


# ---------- Asistan ----------
@pytest.mark.parametrize("soru, sorgu", [
    ("Vadesi geçmiş alacaklarım neler?", "alacak"), ("Hangi müşteri borçlu?", "alacak"),
    ("Tahsil edilmemiş faturalarım", "alacak"), ("Müşterilerim kaç günde ödüyor?", "alacak"),
    ("Hangi müşteri geç ödüyor?", "alacak"), ("Açık faturalarım", "alacak"),
    ("En çok satış yaptığım müşteri kim?", "cari"), ("Hangi tedarikçiye borcum var?", "cari"),
    ("Müşterilerden ne kadar tahsilat bekliyorum?", None),  # kullanıcının PLANLI tahsilatları (niyet.py)
    ("Gelecek ay alacaklarım ne kadar?", None), ("Gecikmiş ödemem var mı?", None)])
def test_alacak_kalibi(soru, sorgu):
    r = analiz_kalibi(soru)
    assert (r["sorgu"] if r else None) == sorgu


def test_alacak_cevabi_rakamlari_panelle_ayni():
    from app.kayit import tl
    o = alacak.ozet("F003")
    r = analiz_cevabi("Vadesi geçmiş alacaklarım neler?", "F003", "alacak", [])
    assert tl(o["acik_tutar"]) in r["cevap"] and tl(o["vadesi_gecen_tutar"]) in r["cevap"]
    assert "FT078" in r["cevap"] and r["kaynaklar"] == [a["id"] for a in alacak.acik_alacaklar("F003")]
    r = analiz_cevabi("Müşterilerim kaç günde ödüyor?", "F003", "alacak", [])
    assert f"ortalama {o['ort_tahsil_gun']:.0f} gün" in r["cevap"] and r["cevap"].index("Moda Butik") < 300


def test_alacak_yoksa_soyler(monkeypatch):
    monkeypatch.setattr(db, "BUGUN", "2026-02-01")  # henüz fatura kesilmemiş
    assert "Tahsil edilmemiş satış faturanız yok." in analiz_cevabi("açık faturalarım", "F001", "alacak", [])["cevap"]
    monkeypatch.setattr(db, "BUGUN", "2026-04-01")  # yalnızca açılış faturası var, hiç tahsilat yok
    c = analiz_cevabi("açık faturalarım", "F001", "alacak", [])["cevap"]
    assert "Tahsil edilmemiş **1 satış faturanız**" in c and "ortalama —" not in c


# ---------- Rapor ve ekran ----------
def test_rapor_alacak_bolumu():
    from app import rapor
    v = rapor.rapor_verisi("F003", "2026-10")
    assert v["alacak"]["ozet"] == alacak.ozet("F003") and v["alacak"]["acik"][0]["id"] == "FT078"


def test_ekran_alacaklar_sekmesi():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(KOK / "ui" / "streamlit_app.py"), default_timeout=60)
    at.session_state["kullanici"] = {"id": 3, "rol": "firma", "firma_id": "F003", "ad": "Demo Tekstil sahibi",
                                     "eposta": "tekstil@demo.local", "unvan": "Demo Tekstil (Şahıs)"}
    at.session_state["mesajlar"] = []
    at.run()
    assert not at.exception
    metin = " ".join(str(e.value) for e in list(at.markdown) + list(at.caption))
    assert "Açık alacak" in metin and "Alacak yaşlandırması" in metin and "Moda Butik" in metin
