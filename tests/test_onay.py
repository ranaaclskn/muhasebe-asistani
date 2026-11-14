"""İnsan onayı güvenlik testleri (atölye d7_07_guvenlik.py + testler/test_store.py karşılığı).

Model/Ollama GEREKMEZ, saniyeler içinde biter. Gerçek veritabanına dokunmaz: her test
data/muhasebe.db'nin geçici bir KOPYASINDA çalışır.
Çalıştır (proje klasöründen):  python -m pytest -q tests/test_onay.py
"""
import json
import shutil
import sys
from pathlib import Path

import pytest

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import app.db as db  # noqa: E402
from app import onay  # noqa: E402

MUHASEBECI_ID = 4  # kullanicilar.csv sırası: 1 gida, 2 yazilim, 3 tekstil, 4 muhasebe
FIRMA_KULLANICI_ID = 1


@pytest.fixture(autouse=True)
def gecici_db(tmp_path, monkeypatch):
    kopya = tmp_path / "test.db"
    shutil.copy(KOK / "data" / "muhasebe.db", kopya)
    monkeypatch.setattr(db, "DB_YOLU", kopya)
    yield kopya


def yeni_talep(firma_id="F001"):
    return db.talep_ekle(firma_id, "Eylül KDV beyannamemi e-postama gönder.", emir="belge_gonder",
                         detay={"belge_turu": "KDV", "donem": "2026-09",
                                "dosya": f"{firma_id}_KDV_2026-09.txt", "eposta": "gida@demo.local"},
                         ozet="Eylül 2026 KDV beyannamesi kayıtlı e-postanıza gönderilecek.")


def durum(talep_id):
    return db.baglan().execute("SELECT durum FROM talepler WHERE id = ?", (talep_id,)).fetchone()["durum"]


def test_onaysiz_gonderim_engellenir():
    t = yeni_talep()
    r = onay.talep_gonder(t, "sahte-token")
    assert r == {"ok": False, "hata": "Geçerli insan onayı bulunamadı"}
    assert durum(t) == "Onay bekliyor"


def test_onayli_gonderim_bir_kez_yapilir():
    t = yeni_talep()
    token = onay.onay_ver(t, MUHASEBECI_ID)
    assert durum(t) == "Onaylandı"
    r1 = onay.talep_gonder(t, token)
    assert r1["ok"] and not r1["tekrar"] and r1["gonderim"]["dosya"] == "F001_KDV_2026-09.txt"
    assert durum(t) == "İşleme alındı"
    r2 = onay.talep_gonder(t, token)  # aynı istek tekrar -> yeni gönderim YOK
    assert r2["ok"] and r2["tekrar"]
    sayi = db.baglan().execute("SELECT COUNT(*) FROM gonderimler WHERE talep_id = ?", (t,)).fetchone()[0]
    assert sayi == 1


def test_token_baska_talep_icin_kullanilamaz():
    t1, t2 = yeni_talep(), yeni_talep()
    token1 = onay.onay_ver(t1, MUHASEBECI_ID)
    onay.onay_ver(t2, MUHASEBECI_ID)
    assert onay.talep_gonder(t2, token1)["ok"] is False


def test_firma_kullanicisi_onay_veremez():
    t = yeni_talep()
    with pytest.raises(PermissionError):
        onay.onay_ver(t, FIRMA_KULLANICI_ID)
    assert durum(t) == "Onay bekliyor"


def test_ayni_talep_iki_kez_onaylanamaz():
    t = yeni_talep()
    onay.onay_ver(t, MUHASEBECI_ID)
    with pytest.raises(ValueError):
        onay.onay_ver(t, MUHASEBECI_ID)


def test_baska_firmanin_talebi_gonderilemez():
    t = yeni_talep("F002")
    token = onay.onay_ver(t, MUHASEBECI_ID)
    r = onay.talep_gonder(t, token, firma_id="F001")  # F001 oturumu, F002'nin talebi
    assert r == {"ok": False, "hata": "Talep bulunamadı"}
    assert durum(t) == "Onaylandı"  # gönderilmedi


def test_mcp_araci_firma_oturumunu_kullanir(monkeypatch):
    from app import mcp_sunucu
    t = yeni_talep("F002")
    token = onay.onay_ver(t, MUHASEBECI_ID)
    monkeypatch.setenv("MUHASEBE_FIRMA_ID", "F001")
    assert json.loads(mcp_sunucu.talep_gonder(t, token))["ok"] is False  # başka firma
    monkeypatch.setenv("MUHASEBE_FIRMA_ID", "F002")
    assert json.loads(mcp_sunucu.talep_gonder(t, token))["ok"] is True   # kendi firması
    assert json.loads(mcp_sunucu.talep_gonder(t, "sahte"))["tekrar"] is True


def test_denetim_kaydi_tutulur():
    t = yeni_talep()
    onay.talep_gonder(t, "sahte")
    token = onay.onay_ver(t, MUHASEBECI_ID)
    onay.talep_gonder(t, token)
    olaylar = [d["olay"] for d in onay.son_denetim() if d["talep_id"] == t]
    assert olaylar == ["gonderildi", "onay_verildi", "gonderim_reddedildi"]
