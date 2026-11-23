"""n8n e-posta köprüsü testleri (app/bildirim.py, Adım 10).

n8n de Ollama da GEREKMEZ: n8n'e giden HTTP isteği sahte bir fonksiyonla yakalanır (ne gönderildiği
kontrol edilir). Gerçek veritabanına dokunmaz: data/muhasebe.db'nin geçici KOPYASINDA çalışır.
Çalıştır (proje klasöründen):  python -m pytest -q tests/test_bildirim.py
"""
import shutil
import sys
from pathlib import Path

import pytest
import requests

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import app.db as db  # noqa: E402
from app import bildirim, onay  # noqa: E402

MUHASEBECI_ID = 4


class SahteN8n:
    """requests.post yerine geçer: gelen istekleri saklar; `calisiyor=False` iken bağlantı hatası verir."""
    def __init__(self):
        self.istekler, self.calisiyor, self.durum_kodu = [], True, 200

    def __call__(self, url, json=None, data=None, files=None, timeout=None):
        if not self.calisiyor:
            raise requests.ConnectionError("bağlantı reddedildi")
        self.istekler.append({"url": url, "veri": json or data, "ek": (files or {}).get("ek")})
        yanit = requests.Response()
        yanit.status_code = self.durum_kodu
        return yanit


@pytest.fixture(autouse=True)
def ortam(tmp_path, monkeypatch):
    kopya = tmp_path / "test.db"
    shutil.copy(KOK / "data" / "muhasebe.db", kopya)
    monkeypatch.setattr(db, "DB_YOLU", kopya)
    onay.tablolari_kur()
    con = db.baglan()  # kullanıcının gerçek kuyruğundaki kayıtlar testleri etkilemesin
    con.execute("DELETE FROM gonderimler")
    con.commit()
    sahte = SahteN8n()
    monkeypatch.setattr(bildirim.requests, "post", sahte)
    monkeypatch.setattr(bildirim, "BUGUN", "2026-11-21")
    monkeypatch.setattr(db, "BUGUN", "2026-11-21")
    return sahte


def onaylanmis_talep(emir="belge_gonder", firma_id="F001"):
    if emir == "belge_gonder":
        t = db.talep_ekle(firma_id, "Eylül KDV beyannamemi e-postama gönder.", emir=emir,
                          detay={"belge_turu": "KDV", "donem": "2026-09", "dosya": f"{firma_id}_KDV_2026-09.txt",
                                 "eposta": "gida@demo.local"},
                          ozet="Eylül 2026 KDV beyannamesi (F001_KDV_2026-09.txt) kayıtlı e-posta adresinize "
                               "(gida@demo.local) gönderilecek.")  # akis.py'nin onay sorusundaki biçim
    else:
        t = db.talep_ekle(firma_id, "Muhasebeciyle görüşme talebi oluştur", emir="gorusme_talebi",
                          detay={"konu": "Muhasebeciyle görüşme"}, ozet="Görüşme talebi “Muhasebeciyle görüşme”")
    assert onay.talep_gonder(t, onay.onay_ver(t, MUHASEBECI_ID))["ok"]
    return t


def satir(sql, *p):
    return db.baglan().execute(sql, p).fetchone()


def test_onaylanan_belge_ekiyle_n8ne_gider(ortam):
    t = onaylanmis_talep()
    r = bildirim.kuyrugu_isle(t)
    assert r == [{"talep_id": t, "ok": True, "eposta": "gida@demo.local"}]
    istek = ortam.istekler[0]
    assert istek["url"].endswith("/webhook/talep-onay") and istek["veri"]["eposta"] == "gida@demo.local"
    # giden e-postada gelecek zamanlı onay cümlesi kalmaz, yalnız NE gönderildiği yazar
    assert "Talep: Eylül 2026 KDV beyannamesi (F001_KDV_2026-09.txt)\n" in istek["veri"]["metin"]
    assert "gönderilecek" not in istek["veri"]["metin"]
    ad, icerik, _ = istek["ek"]
    assert ad == "F001_KDV_2026-09.txt" and "KDV BEYANNAMESİ" in icerik.decode("utf-8")
    assert satir("SELECT durum FROM gonderimler WHERE talep_id = ?", t)["durum"] == "Gönderildi"
    assert satir("SELECT durum FROM talepler WHERE id = ?", t)["durum"] == "Tamamlandı"
    assert satir("SELECT olay FROM denetim WHERE talep_id = ? ORDER BY id DESC", t)["olay"] == "eposta_gonderildi"


def test_ayni_talep_iki_kez_gonderilmez(ortam):
    t = onaylanmis_talep()
    bildirim.kuyrugu_isle(t)
    assert bildirim.kuyrugu_isle(t) == [] and bildirim.kuyrugu_isle() == []
    assert len(ortam.istekler) == 1


def test_n8n_kapaliysa_kuyrukta_kalir_sonra_gonderilir(ortam):
    t = onaylanmis_talep()
    ortam.calisiyor = False
    r = bildirim.kuyrugu_isle(t)
    assert not r[0]["ok"] and "ulaşılamadı" in r[0]["hata"]
    assert satir("SELECT durum FROM gonderimler WHERE talep_id = ?", t)["durum"] == "Kuyrukta"
    assert [k["talep_id"] for k in bildirim.kuyrukta_bekleyenler()] == [t]
    ortam.calisiyor = True  # n8n açıldı -> "Tekrar dene"
    assert bildirim.kuyrugu_isle()[0]["ok"]
    assert bildirim.kuyrukta_bekleyenler() == []


def test_n8n_hata_kodu_donerse_gonderilmis_sayilmaz(ortam):
    t = onaylanmis_talep()
    ortam.durum_kodu = 404  # akış yayında değil
    r = bildirim.kuyrugu_isle(t)
    assert not r[0]["ok"] and "404" in r[0]["hata"] and "yayında" in r[0]["hata"]
    assert satir("SELECT durum FROM gonderimler WHERE talep_id = ?", t)["durum"] == "Kuyrukta"


def test_gorusme_talebi_eksiz_kayitli_adrese_gider(ortam):
    t = onaylanmis_talep(emir="gorusme_talebi")
    assert bildirim.kuyrugu_isle(t)[0]["ok"]
    istek = ortam.istekler[0]
    assert istek["ek"] is None and istek["veri"]["eposta"] == "gida@demo.local"  # kayıtlı adres
    assert "onaylandı" in istek["veri"]["konu"]


def test_belge_adi_klasor_disina_cikamaz():
    assert bildirim._belge("../../.env") is None  # yalnızca data/belgeler içindeki dosya adı
    assert bildirim._belge("F001_KDV_2026-09.txt")[0] == "F001_KDV_2026-09.txt"


def test_hatirlatma_geciken_ve_yaklasan_odemeler(ortam):
    # 21.11.2026: F001'in geçici vergisi gecikmiş (17.11), muhtasar 26.11'de (5 gün) -> 3 günde yalnız gecikmiş
    assert [s["tur"] for s in bildirim.hatirlatilacaklar("F001", 3)] == ["Geçici vergi"]
    assert [s["tur"] for s in bildirim.hatirlatilacaklar("F001", 5)] == ["Geçici vergi", "Muhtasar"]
    r = bildirim.hatirlatma_gonder("F001", 5)
    assert r["gonderildi"] and r["adet"] == 2 and r["eposta"] == "gida@demo.local"
    metin = ortam.istekler[0]["veri"]["metin"]
    assert ortam.istekler[0]["url"].endswith("/webhook/hatirlatma")
    assert "4 gün gecikti" in metin and "5 gün kaldı" in metin and "54.938,65 TL" in metin


def test_hatirlatilacak_odeme_yoksa_eposta_gitmez(ortam, monkeypatch):
    monkeypatch.setattr(bildirim, "BUGUN", "2026-07-01")
    monkeypatch.setattr(db, "BUGUN", "2026-07-01")
    r = bildirim.hatirlatma_gonder("F001", 3)
    assert r["ok"] and not r["gonderildi"] and ortam.istekler == []
