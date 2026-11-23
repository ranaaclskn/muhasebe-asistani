"""Muhasebecinin firmaya "girmesi" testleri: yetki (app/db.erisilebilir_firma), denetim kaydı
(app/onay.firma_dosyasi_ac) ve salt okunur ekran (Streamlit AppTest ile; tarayıcı gerekmez).

Model GEREKMEZ. Gerçek veritabanına dokunmaz: data/muhasebe.db'nin geçici KOPYASINDA çalışır.
Çalıştır (proje klasöründen):  python -m pytest -q tests/test_firma_dosyasi.py
"""
import shutil
import sys
from pathlib import Path

import pytest

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import app.db as db  # noqa: E402
from app.onay import firma_dosyasi_ac, son_denetim  # noqa: E402

MUHASEBECI = {"id": 4, "rol": "muhasebeci", "firma_id": None, "ad": "Demo Muhasebe Bürosu",
              "eposta": "muhasebe@demo.local", "unvan": None}
GIDA = {"id": 1, "rol": "firma", "firma_id": "F001", "ad": "Demo Gıda yetkilisi", "eposta": "gida@demo.local",
        "unvan": "Demo Gıda Ltd. Şti."}


@pytest.fixture(autouse=True)
def ortam(tmp_path, monkeypatch):
    kopya = tmp_path / "test.db"
    shutil.copy(KOK / "data" / "muhasebe.db", kopya)
    monkeypatch.setattr(db, "DB_YOLU", kopya)
    monkeypatch.setattr(db, "_SEMA_GUNCEL", False)


def _acilislar():
    return [d for d in son_denetim(100) if d["olay"] == "firma_dosyasi_acildi"]


def test_firma_yetkilisi_yalnizca_kendi_firmasini_gorur():
    assert db.erisilebilir_firma(GIDA, "F001")
    assert not db.erisilebilir_firma(GIDA, "F002")


def test_muhasebeci_kayitli_her_firmayi_gorur():
    assert all(db.erisilebilir_firma(MUHASEBECI, f) for f in db.firmalar())
    assert not db.erisilebilir_firma(MUHASEBECI, "F999")  # kayıtlı değil


@pytest.mark.parametrize("kotu", ["../F001", "F1", "", None, "F001; DROP TABLE firmalar"])
def test_gecersiz_firma_kimligi_reddedilir(kotu):
    assert not db.erisilebilir_firma(MUHASEBECI, kotu)
    assert not db.erisilebilir_firma(None, kotu)


def test_dosya_acilisi_denetime_yazilir():
    bilgi = firma_dosyasi_ac(MUHASEBECI, "F002")
    assert bilgi["unvan"] == "Demo Yazılım A.Ş."
    kayit = _acilislar()
    assert len(kayit) == 1 and kayit[0]["talep_id"] is None
    assert "F002" in kayit[0]["detay"] and "Demo Muhasebe Bürosu" in kayit[0]["detay"]


@pytest.mark.parametrize("kullanici, firma", [(GIDA, "F001"), (GIDA, "F002"), (MUHASEBECI, "F999"),
                                              (MUHASEBECI, "../F001"), ({}, "F001")])
def test_yetkisiz_acilis_reddedilir_ve_kayit_yazilmaz(kullanici, firma):
    # firma yetkilisi kendi firmasını bile "muhasebeci görünümünde" açamaz: bu akış yalnızca muhasebeci içindir
    with pytest.raises(PermissionError):
        firma_dosyasi_ac(kullanici, firma)
    assert _acilislar() == []


# ---------- Arayüz (Streamlit AppTest: betiği tarayıcısız çalıştırır) ----------
def _uygulama(kullanici, acik_firma=None):
    from streamlit.testing.v1 import AppTest
    at = AppTest.from_file(str(KOK / "ui" / "streamlit_app.py"), default_timeout=60)
    at.session_state["kullanici"] = kullanici
    at.session_state["mesajlar"] = []
    if acik_firma:
        at.session_state["acik_firma"] = acik_firma
    return at.run()


def _metin(at):
    return " ".join(str(e.value) for e in list(at.markdown) + list(at.caption))


def test_ekran_muhasebeci_salt_okunur_gorunum():
    at = _uygulama(MUHASEBECI, "F003")
    assert not at.exception
    metin = _metin(at)
    assert "Muhasebeci görünümü · salt okunur" in metin and "Demo Tekstil" in metin
    assert len(at.chat_input) == 0                         # asistan kapalı
    assert not any(f.label == "Kaydı ekle" for f in at.button)  # planlı kayıt formu yok
    assert not any(b.label == "Sil" for b in at.button)
    assert any(b.label == "Portföye dön" for b in at.button)


def test_ekran_paneli_ac_ve_portfoye_don():
    at = _uygulama(MUHASEBECI)
    assert "Firma portföyü" in _metin(at)
    at.selectbox(key="muh_rapor_firma").set_value("F002")
    at.button(key="firma_ac").click().run()
    assert at.session_state["acik_firma"] == "F002" and "Demo Yazılım" in _metin(at)
    assert len(_acilislar()) == 1
    at.button(key="portfoye_don").click().run()
    assert "acik_firma" not in at.session_state and "Firma portföyü" in _metin(at)


def test_ekran_firma_yetkilisi_baska_firmayi_acamaz():
    at = _uygulama(GIDA, "F002")  # oturuma elle yazılmış olsa bile firma yetkilisi kendi panelini görür
    assert not at.exception
    metin = _metin(at)
    assert "Muhasebeci görünümü" not in metin and "Demo Yazılım" not in metin
    assert len(at.chat_input) == 1
