"""Geniş değerlendirmede (scripts/09_yuz_soru.py: 110 soru + 4 kör set) bulunan hataların kalıcı testleri.
Her satır, asistanın bir zamanlar YANLIŞ yola gönderdiği gerçek bir soru. Model GEREKMEZ: yönlendirme kuralları,
cevap şablonları ve güvenlik ağı doğrudan denenir. Veritabanının geçici kopyasında, 23.11.2026 gününde çalışır.

Çalıştır (proje klasöründen):  python -m pytest -q tests/test_degerlendirme_hatalari.py
Asıl ölçüm (modelle):         python scripts/09_yuz_soru.py --set kor4
"""
import shutil
import sys
from pathlib import Path

import pytest

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import app.db as db  # noqa: E402
import app.niyet as niyet  # noqa: E402
from app.analiz_sorulari import analiz_kalibi  # noqa: E402


@pytest.fixture(autouse=True)
def ortam(tmp_path, monkeypatch):
    kopya = tmp_path / "test.db"
    shutil.copy(KOK / "data" / "muhasebe.db", kopya)
    monkeypatch.setattr(db, "DB_YOLU", kopya)
    monkeypatch.setattr(db, "_SEMA_GUNCEL", False)
    monkeypatch.setattr(db, "BUGUN", "2026-11-23")
    monkeypatch.setattr(niyet, "BUGUN", "2026-11-23")
    db.baglan().execute("DELETE FROM planli_islemler").connection.commit()


def _yol(soru):
    """Kural katmanının vereceği (sorgu, parametreler); model 'belge' dese bile."""
    s = niyet._kucuk(niyet.yazim_duzelt(soru))
    a = analiz_kalibi(soru)
    if a:
        return a["sorgu"], a["parametreler"]
    r = niyet.kural_duzelt(niyet.yazim_duzelt(soru), {"niyet": "belge", "sorgu": None, "parametreler": []})
    return (r.get("sorgu") if r["niyet"] == "kayit" else r["niyet"]), r.get("parametreler"), s


@pytest.mark.parametrize("soru, sorgu, parametreler", [
    ("Ekim KDV'si ne kadar?", "durum", ["KDV", "2026-10"]),                       # yıllık toplam veriyordu
    ("Ekim muhtasarımın son ödeme günü ne?", "durum", ["Muhtasar", "2026-10"]),   # ödeme geçmişi veriyordu
    ("Temmuz SGK primini hangi tarihte yatırdım?", "durum", ["SGK primi", "2026-07"]),
    ("Eylül KDV'sini yatırmış mıyız?", "durum", ["KDV", "2026-09"]),
    ("Geçici vergimi ödedim mi?", "siradaki_tur", ["Geçici vergi"]),           # belgeden "ödediniz" UYDURUYORDU
    ("geçici vergiyi yatırdık mı", "siradaki_tur", ["Geçici vergi"]),
    ("Bu ay toplam borcum ne kadar?", "ay_odemeleri", ["2026-11"]),
    ("Ay sonuna kadar ne ödemem lazım?", "ay_odemeleri", ["2026-11"]),
    ("Ödemesi geçmiş vergilerim neler?", "gecikmis", []),                      # "kayıtlarınızda yok" diyordu
    ("Ödemeyi unuttuğum bir vergi var mı?", "gecikmis", []),
    ("Hiç geç ödeme yaptım mı?", "gec_odenenler", []),
    ("Bir sonraki vergi ödemem hangisi?", "en_yakin", []),
    ("Şimdi sırada hangi ödeme var?", "en_yakin", []),
    ("Önümüzdeki 7 günde hangi ödemeler var?", "gun_icinde", ["2026-11-23", "2026-11-30", "önümüzdeki 7 gün"]),
    ("Bu hafta ödemem var mı?", "gun_icinde", ["2026-11-23", "2026-11-29", "bu hafta"]),
    ("Önümüzdeki günlerde hangi ödemelerim var?", "yaklasanlar", []),
    ("Eylülde ne kadar vergi ödedim?", "odenenler", ["2026-09"]),
    ("Temmuz ayında yaptığım ödemeler", "odenenler", ["2026-07"]),
    ("Bu yıl ödediğim muhtasar toplamı?", "yil_odenenler", None),               # "mu"htasar soru eki sanılmasın
    ("Moda Butik'ten ne kadar alacağım var?", "alacak", []),
    ("Ege Otel bize ne kadar borçlu?", "alacak", []),
    ("Moda Butik'in borcu ne kadar?", "alacak", []),
    ("Hangi faturalarım hâlâ tahsil edilmedi?", "alacak", []),
    ("Müşterilerimden toplam alacağım ne kadar?", "alacak", []),
    ("Ortalama kaç günde tahsilat yapıyorum?", "alacak", []),
    ("Ödemesini geciktiren müşteri var mı?", "alacak", []),
    ("En çok alım yaptığım firma hangisi?", "cari", ["satici"]),               # "işe alım" sanıyordu
    ("İşletmemin finansal sağlığı nasıl?", "saglik", []),
    ("Şirketim ne durumda?", "saglik", []),
    ("SGK prim ödemeleri ayın kaçına kadar yapılır?", "belge", None),
    ("kdv ne zman ödenio", "belge", None),                                      # yazım hatası
])
def test_yonlendirme(soru, sorgu, parametreler):
    r = _yol(soru)
    assert r[0] == sorgu, r
    if parametreler is not None:
        assert r[1] == parametreler, r


@pytest.mark.parametrize("soru", ["Bu ay ödemem gereken SGK ne kadar?", "Kasım'da ödenecek KDV ne kadar?",
                                  "Müşterilerden ne kadar tahsilat bekliyorum?", "Gelecek ay alacaklarım ne kadar?",
                                  "Kent Market'ten 5000 TL alacağım var", "En çok satış yaptığım müşteri kim?"])
def test_eski_dogru_yollar_bozulmadi(soru):
    assert _yol(soru)[0] not in ("durum", "alacak", "gun_icinde") or "alacak" not in str(_yol(soru))


def test_yazim_duzeltme():
    assert niyet.yazim_duzelt("kdv ne zman ödenio") == "kdv ne zaman ödenir"
    assert niyet.yazim_duzelt("ekim sgk odedimmi") == "ekim sgk ödedim mi"
    assert niyet.yazim_duzelt("gecikmiş borcum varmı") == "gecikmiş borcum var mı"
    assert niyet.yazim_duzelt("Ekim SGK primim ödendi mi?") == "Ekim SGK primim ödendi mi?"  # doğru yazım değişmez


def test_gorev_sayisi_ve_kim():
    from app.bordro import bordro_cevabi, bordro_kalibi
    assert bordro_kalibi("Kaç dikiş operatörüm var?", "F003") and bordro_kalibi("Büro elemanım kim?", "F003")
    assert "4 çalışanınız" in bordro_cevabi("Kaç dikiş operatörüm var?", "F003")["cevap"]
    assert "Pınar Özkan" in bordro_cevabi("Büro elemanım kim?", "F003")["cevap"]
    assert not bordro_kalibi("En çok alım yaptığım firma hangisi?", "F001")


def test_beyanname_istenen_satir():
    from app.rag import beyanname_satiri
    c = beyanname_satiri("Ağustos KDV beyannamesinde hesaplanan KDV ne kadar?", "F002")
    assert c.startswith("Hesaplanan KDV (%20): 219.966,40 TL")
    assert beyanname_satiri("Ağustos KDV beyannamesinde matrah ne kadar?", "F002").startswith("Teslim ve hizmetlerin")
    assert "Ödenecek KDV: 44.307,46" in beyanname_satiri("Eylül KDV beyannamemde ödenecek KDV ne kadardı?", "F001")


def test_kavram_sorusu_rehberden():
    from app.rag import kavram_cevabi
    assert kavram_cevabi("KDV beyannamesi nedir?").startswith("KDV (Katma Değer Vergisi)")
    assert kavram_cevabi("Geçici vergi nedir").startswith("Geçici vergi:")
    assert kavram_cevabi("KDV ne zaman ödenir?") is None  # takvim sorusu, tanım değil


def test_odedim_mi_acik_cevap():
    from app.kayit import cevapla_kayit
    c = cevapla_kayit("Geçici vergimi ödedim mi?", "F003", {"sorgu": "siradaki_tur", "parametreler": ["Geçici vergi"]})
    assert c["cevap"].startswith("**Ödenmedi.**") and "17.223,80" in c["cevap"]


def test_gun_icinde_cevabi():
    from app.kayit import cevapla_kayit
    c = cevapla_kayit("x", "F002", {"sorgu": "gun_icinde", "parametreler": ["2026-11-23", "2026-11-30", "önümüzdeki 7 gün"]})
    assert "3 ödemeniz var" in c["cevap"] and "217.701,53" in c["cevap"]


def test_tahsilat_beklentisi_acik_faturalari_da_soyler():
    from app.kayit import cevapla_kayit
    c = cevapla_kayit("x", "F001", {"sorgu": "beklenen_tahsilatlar", "parametreler": []})["cevap"]
    assert "eklediğiniz beklenen tahsilat yok" in c and "tahsil edilmemiş **6 satış faturanız**" in c


@pytest.mark.parametrize("soru, odeme, yaratici", [
    ("Benim yerime KDV'mi öde.", True, False), ("vergiyi benim için yatır", True, False),
    ("KDV'mi ne zaman ödemeliyim?", False, False), ("Eylül KDV'mi ödedim mi?", False, False),
    ("Bana bir şiir yaz", False, True)])
def test_odeme_talimati_ve_yaratici_istek(soru, odeme, yaratici):
    import re
    from app.akis import ODEME_TALIMATI, YARATICI
    s = soru.lower()
    o = bool(re.search(ODEME_TALIMATI, s) and not re.search(r"ödedi|ödendi|ödersem|ödemeli|ödeyece|ne zaman|ne kadar", s))
    assert (o, bool(re.search(YARATICI, s))) == (odeme, yaratici)


def test_guvenlik_agi_kayitta_yok_demez():
    from app.akis import _guvenlik_agi
    yok = "Bu bilgi kayıtlarınızda yok, muhasebecinize iletebilirim."
    r = _guvenlik_agi({"soru": "Ödemeyi unuttuğum bir vergi var mı?", "firma_id": "F002"}, yok)
    assert r and "anlayamadım" in r["cevap"] and "107.718,74" in r["cevap"]
    for soru in ("2025 Mart KDV'm ne kadardı?", "KDV iadesi nasıl alınır?", "Hangi hisseyi almalıyım?"):
        assert _guvenlik_agi({"soru": soru, "firma_id": "F002"}, yok) is None  # dönem / genel bilgi / kapsam dışı
    assert _guvenlik_agi({"soru": "Gecikmiş ödemem var mı?", "firma_id": "F002"}, "Gecikmiş ödemeniz var: ...") is None


def test_guvenlik_agi_dolu_cevaba_dokunmaz():
    # SGK faiz cevabının içinde "bu tutar kayıtlarınızda yok" geçer; cevap doluysa ağ devreye GİRMEMELİ (K013)
    from app.akis import _guvenlik_agi
    dolu = "Son ödeme tarihi geçmiş 2 ödemeniz var: ... SGK hesaplar; bu tutar kayıtlarınızda yok, tahmin vermiyorum."
    assert _guvenlik_agi({"soru": "Gecikme faizim ne kadar oldu?", "firma_id": "F003"}, dolu) is None
