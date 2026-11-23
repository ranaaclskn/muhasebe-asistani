"""Güvenlik (öneri #8) testleri: girişte deneme sınırı (app/db.kullanici_dogrula) ve n8n webhook anahtarı
(app/bildirim._n8n -> X-Muhasebe-Anahtar başlığı; n8n akışlarında headerAuth).

Model ve n8n GEREKMEZ. Gerçek veritabanına dokunmaz: data/muhasebe.db'nin geçici KOPYASINDA çalışır.
Zaman `simdi` parametresiyle verilir: kilidin dolması için gerçekten 15 dakika beklenmez.
Çalıştır (proje klasöründen):  python -m pytest -q tests/test_guvenlik.py
"""
import json
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import app.db as db  # noqa: E402

SIFRE = "Demo2026!"
T0 = datetime(2026, 11, 23, 10, 0, 0)


@pytest.fixture(autouse=True)
def ortam(tmp_path, monkeypatch):
    kopya = tmp_path / "test.db"
    shutil.copy(KOK / "data" / "muhasebe.db", kopya)
    monkeypatch.setattr(db, "DB_YOLU", kopya)
    monkeypatch.setattr(db, "_SEMA_GUNCEL", False)
    con = db.baglan()
    con.executescript(db.GIRIS_SEMA + "DELETE FROM giris_denemeleri;")
    con.close()


def _yanlis(eposta, n, bas=T0, aralik=10):
    for i in range(n):
        assert db.kullanici_dogrula(eposta, "yanlis", simdi=bas + timedelta(seconds=i * aralik)) is None


# ---------- Girişte deneme sınırı ----------
def test_dogru_sifre_girer_hash_donmez():
    k = db.kullanici_dogrula("  Gida@Demo.local ", SIFRE, simdi=T0)
    assert k["firma_id"] == "F001" and "sifre_hash" not in k


def test_kalan_hak_azalir():
    _yanlis("gida@demo.local", 3)
    assert db.giris_durumu("gida@demo.local", T0 + timedelta(minutes=1)) == (2, None)


def test_bes_hatadan_sonra_dogru_sifre_bile_reddedilir():
    _yanlis("gida@demo.local", 5)
    with pytest.raises(db.GirisKilitli) as e:
        db.kullanici_dogrula("gida@demo.local", SIFRE, simdi=T0 + timedelta(minutes=1))
    assert e.value.dakika == 15 and "15 dakika" in str(e.value)  # 5. hata 10:00:40 -> kilit 10:15:40


def test_kilit_suresi_dolunca_giris_acilir():
    _yanlis("gida@demo.local", 5)
    assert db.kullanici_dogrula("gida@demo.local", SIFRE, simdi=T0 + timedelta(minutes=16))["firma_id"] == "F001"


def test_kilit_sirasindaki_denemeler_sureyi_uzatmaz():
    _yanlis("gida@demo.local", 5)
    for dk in (2, 5, 9):
        with pytest.raises(db.GirisKilitli):
            db.kullanici_dogrula("gida@demo.local", "yanlis", simdi=T0 + timedelta(minutes=dk))
    assert db.kullanici_dogrula("gida@demo.local", SIFRE, simdi=T0 + timedelta(minutes=16)) is not None


def test_basarili_giris_sayaci_sifirlar():
    _yanlis("gida@demo.local", 4)
    assert db.kullanici_dogrula("gida@demo.local", SIFRE, simdi=T0 + timedelta(minutes=1))
    _yanlis("gida@demo.local", 4, bas=T0 + timedelta(minutes=2))
    assert db.giris_durumu("gida@demo.local", T0 + timedelta(minutes=3)) == (1, None)


def test_pencere_disindaki_eski_hatalar_sayilmaz():
    _yanlis("gida@demo.local", 4)
    _yanlis("gida@demo.local", 1, bas=T0 + timedelta(minutes=20))
    assert db.giris_durumu("gida@demo.local", T0 + timedelta(minutes=21)) == (4, None)


def test_kilit_hesaba_ozel_buyuk_kucuk_harf_ayni_hesap():
    _yanlis("GIDA@demo.local", 5)
    with pytest.raises(db.GirisKilitli):
        db.kullanici_dogrula("gida@demo.local", SIFRE, simdi=T0 + timedelta(minutes=1))
    assert db.kullanici_dogrula("yazilim@demo.local", SIFRE, simdi=T0 + timedelta(minutes=1))  # başka hesap açık


def test_kayitli_olmayan_eposta_da_sayilir_ve_ayni_cevabi_alir():
    _yanlis("yok@demo.local", 5)
    with pytest.raises(db.GirisKilitli):
        db.kullanici_dogrula("yok@demo.local", "yanlis", simdi=T0 + timedelta(minutes=1))


def test_bos_alanlar_patlamaz():
    assert db.kullanici_dogrula("", "", simdi=T0) is None
    assert db.kullanici_dogrula(None, None, simdi=T0) is None


def test_bir_gunden_eski_kayitlar_temizlenir():
    _yanlis("gida@demo.local", 2)
    db.kullanici_dogrula("yazilim@demo.local", "yanlis", simdi=T0 + timedelta(days=2))
    sayi = db.baglan().execute("SELECT COUNT(*) FROM giris_denemeleri").fetchone()[0]
    assert sayi == 1


# ---------- n8n webhook anahtarı ----------
@pytest.fixture()
def n8n(monkeypatch):
    from app import bildirim
    from tests.test_bildirim import SahteN8n
    sahte = SahteN8n()
    monkeypatch.setattr(bildirim.requests, "post", sahte)
    return bildirim, sahte


def test_anahtar_her_istekte_baslikta_gider(n8n, monkeypatch):
    bildirim, sahte = n8n
    monkeypatch.setattr(bildirim, "N8N_WEBHOOK_ANAHTARI", "gizli-anahtar_123")
    bildirim._n8n("hatirlatma", {"konu": "x"})
    bildirim._n8n("talep-onay", {"konu": "x"}, ek=("a.txt", b"x", "text/plain"))  # ekli (multipart) istek de
    assert [i["basliklar"] for i in sahte.istekler] == [{"X-Muhasebe-Anahtar": "gizli-anahtar_123"}] * 2


def test_anahtar_tanimli_degilse_baslik_gonderilmez(n8n, monkeypatch):
    bildirim, sahte = n8n
    monkeypatch.setattr(bildirim, "N8N_WEBHOOK_ANAHTARI", "")
    bildirim._n8n("hatirlatma", {"konu": "x"})
    assert sahte.istekler[0]["basliklar"] == {}


@pytest.mark.parametrize("kod, ipucu", [(403, "anahtarı eşleşmiyor"), (401, "anahtarı eksik"),
                                       (404, "yayında (aktif) değil")])
def test_reddedilen_istek_anlasilir_hata_verir(n8n, kod, ipucu):
    bildirim, sahte = n8n
    sahte.durum_kodu = kod
    with pytest.raises(RuntimeError) as e:
        bildirim._n8n("hatirlatma", {"konu": "x"})
    assert f"HTTP {kod}" in str(e.value) and ipucu in str(e.value)


def test_tum_webhooklar_baslik_dogrulamali():
    akislar = json.loads((KOK / "n8n" / "akislar.json").read_text(encoding="utf-8"))
    webhooklar = [d for a in akislar for d in a["nodes"] if d["type"] == "n8n-nodes-base.webhook"]
    assert {d["parameters"]["path"] for d in webhooklar} == {"talep-onay", "hatirlatma", "aylik-rapor"}
    for d in webhooklar:
        assert d["parameters"]["authentication"] == "headerAuth"
        assert d["credentials"] == {"httpHeaderAuth": {"id": "MuhasebeWebhAnh1", "name": "Muhasebe webhook anahtarı"}}


def test_anahtar_depoda_yok_yalnizca_yer_tutucu():
    ornek = json.loads((KOK / "n8n" / "webhook_anahtari.json.ornek").read_text(encoding="utf-8"))[0]
    assert ornek["id"] == "MuhasebeWebhAnh1" and ornek["type"] == "httpHeaderAuth"
    assert ornek["data"] == {"name": "X-Muhasebe-Anahtar", "value": "__ANAHTAR__"}
    assert ".env" in (KOK / ".gitignore").read_text(encoding="utf-8").split()


# ---------- Giriş ekranı (Streamlit AppTest: tarayıcısız) ----------
def test_ekran_kalan_hak_ve_kilit_mesaji():
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(KOK / "ui" / "streamlit_app.py"), default_timeout=60).run()

    def dene(sifre):
        at.text_input[0].input("gida@demo.local")  # E-posta
        at.text_input[1].input(sifre)              # Şifre
        at.button[0].click().run()                 # "Giriş yap" (form gönderme düğmesi)
        return " ".join(e.value for e in at.error)

    assert dene("yanlis") == "E-posta veya şifre hatalı."   # 1. hata: 4 hak kaldı, uyarı yok
    assert dene("yanlis") == "E-posta veya şifre hatalı."   # 2. hata
    assert "2 deneme hakkınız kaldı" in dene("yanlis")      # 3. hata
    assert "1 deneme hakkınız kaldı" in dene("yanlis")      # 4. hata
    dene("yanlis")                                          # 5. hata: hesap kilitlendi
    assert "Çok fazla hatalı deneme" in dene(SIFRE)         # kilitliyken doğru şifre de girmez
    assert "kullanici" not in at.session_state
