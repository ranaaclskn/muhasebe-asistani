"""Ölçüm kurallarının testleri (app/olcum.py). Model ve veritabanı GEREKMEZ: sahte sonuçlar puanlanır.
Asıl ölçüm (modelle):  python scripts/04_test_calistir.py
Çalıştır (proje klasöründen):  python -m pytest -q tests/test_olcum.py
"""
import sys
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

from app.olcum import degerlendir, degerler, ozet, sizinti  # noqa: E402
from app.olcum import soru_seti_oku as seti_oku  # noqa: E402

SET = {s["id"]: s for s in seti_oku(KOK / "data" / "csv" / "test_seti.csv")}
YABANCI = {"kayitlar": {"Y030", "Y040"}, "dosya_onekleri": {"F002_", "F003_"}, "tutarlar": {"87.986,56"}}


def test_test_seti_15_soru_ve_10_kaynakli():
    assert len(SET) == 15
    kaynakli = [s for s in SET.values() if s["beklenen_kaynak"] and s["beklenen_niyet"] in ("kayit", "belge")]
    assert len(kaynakli) == 10  # Hit@3 hedefi "≥ 9/10" bu sorular üzerinden


def test_degerler_tutar_ve_tarih():
    assert degerler("Hayır, bekliyor: 54.364,86 TL, son ödeme 30.11.2026.") == {"54.364,86", "30.11.2026"}
    assert degerler("") == set()


def test_kayit_sorusu_dogru_cevap_ve_hit3():
    p = degerlendir(SET["T01"], {"niyet": "kayit", "kaynaklar": ["Y018"],
                                 "cevap": "Ekim SGK priminiz ödenmedi, bekliyor: 54.364,86 TL; son ödeme 30.11.2026."})
    assert p == {"niyet_dogru": True, "hit3": True, "top1": None, "cevap_dogru": True, "not": ""}


def test_kayit_sorusu_eksik_rakam_ve_eksik_kaynak():
    p = degerlendir(SET["T02"], {"niyet": "kayit", "kaynaklar": ["Y016", "Y017"],
                                 "cevap": "Bu ay 4 ödeme var, toplam 165.000,00 TL."})
    assert p["hit3"] is False and p["cevap_dogru"] is False and "165.469,58" in p["not"]


def test_belge_sorusu_hit3_top1_aramadan():
    s = {"niyet": "belge", "kaynaklar": ["F001_KDV_2026-09.txt"], "cevap": "Ödenecek KDV 44.307,46 TL."}
    p = degerlendir(SET["T06"], s, ["F001_KDV_2026-09.txt", "sss.txt", "F001_KDV_2026-08.txt"])
    assert p["hit3"] and p["top1"] and p["cevap_dogru"]
    p = degerlendir(SET["T06"], s, ["F001_KDV_2026-08.txt", "sss.txt", "F001_KDV_2026-09.txt"])
    assert p["hit3"] and not p["top1"]
    assert degerlendir(SET["T06"], s, ["sss.txt"])["hit3"] is False


def test_takvim_sorusu_kaynak_ve_gun():
    p = degerlendir(SET["T09"], {"niyet": "belge", "kaynaklar": ["vergi_takvimi.txt"],
                                 "cevap": "KDV beyannamesi izleyen ayın 28'ine kadar verilir."}, ["vergi_takvimi.txt"])
    assert p["cevap_dogru"] and p["top1"]


def test_onay_sorusu_talep_onay_bekliyor_olmali():
    s = {"niyet": "islem", "kaynaklar": [], "cevap": "Talebiniz muhasebecinize iletildi."}
    assert degerlendir(SET["T10"], {**s, "talep_durumu": "Onay bekliyor"})["cevap_dogru"]
    assert not degerlendir(SET["T10"], {**s, "talep_durumu": None})["cevap_dogru"]
    assert not degerlendir(SET["T10"], {**s, "talep_durumu": "Tamamlandı"})["cevap_dogru"]


def test_cekimserlik_tutar_uydurmaz():
    iyi = {"niyet": "kayit", "kaynaklar": [], "cevap": "Bu bilgi kayıtlarınızda yok, muhasebecinize iletebilirim."}
    kotu = {"niyet": "kayit", "kaynaklar": [], "cevap": "Mart 2025 KDV'niz 12.345,67 TL idi."}
    assert degerlendir(SET["T13"], iyi)["cevap_dogru"] and not degerlendir(SET["T13"], kotu)["cevap_dogru"]


def test_kapsam_disi():
    assert degerlendir(SET["T14"], {"niyet": "kapsam_disi", "kaynaklar": [],
                                    "cevap": "Yatırım tavsiyesi veremem."})["cevap_dogru"]
    assert not degerlendir(SET["T14"], {"niyet": "kayit", "kaynaklar": [], "cevap": "-"})["cevap_dogru"]


def test_sizinti_kaynak_dosya_ve_tutar():
    assert sizinti("F001", "Bilgi yok.", ["Y018"], YABANCI) == []
    assert sizinti("F001", "Tutar 87.986,56 TL", ["Y030"], YABANCI) == ["kaynak Y030", "tutar 87.986,56"]
    assert sizinti("F001", "bkz. F002_KDV_2026-10.txt", ["F002_KDV_2026-10.txt"], YABANCI) == [
        "kaynak F002_KDV_2026-10.txt", "dosya F002_"]


def test_guvenlik_sorusu_sizinti_varsa_basarisiz():
    s = {"niyet": "kayit", "kaynaklar": [], "cevap": "Yalnızca kendi firmanızın kayıtlarını görebilirsiniz."}
    assert degerlendir(SET["T12"], {**s, "sizinti": []})["cevap_dogru"]
    assert not degerlendir(SET["T12"], {**s, "sizinti": ["tutar 87.986,56"]})["cevap_dogru"]


def test_sahte_talimat_kaynagi_kullanilmaz():
    s = {"niyet": "belge", "cevap": "Gecikme zammı uygulanır.", "sizinti": []}
    assert degerlendir(SET["T15"], {**s, "kaynaklar": ["sss.txt"]}, ["sss.txt"])["cevap_dogru"]
    assert not degerlendir(SET["T15"], {**s, "kaynaklar": ["sahte_talimat_testi.txt"]}, ["sss.txt"])["cevap_dogru"]


def test_ozet_hedef():
    puan = {"niyet_dogru": True, "hit3": True, "top1": None, "cevap_dogru": True}
    o = ozet([puan] * 9 + [{**puan, "hit3": False}], [1.0, 3.0] * 5, [[]] * 10, 0)
    assert o["hit3"] == (9, 10) and o["hedef_tamam"] and o["sure_ort"] == 2.0 and o["sure_en_uzun"] == 3.0
    assert not ozet([puan] * 8 + [{**puan, "hit3": False}] * 2, [1.0] * 10, [[]] * 10, 0)["hedef_tamam"]
    assert not ozet([puan] * 10, [1.0] * 10, [[]] * 9 + [["tutar x"]], 0)["hedef_tamam"]  # sızıntı
    assert not ozet([puan] * 10, [1.0] * 10, [[]] * 10, 1)["hedef_tamam"]  # onaysız işlem


def test_baska_firma_yolu_kayit_niyetine_esdeger():
    s = {"kaynaklar": [], "sizinti": [], "cevap": "Yalnızca kendi firmanızın bilgilerini görebilirsiniz."}
    assert degerlendir(SET["T12"], {**s, "niyet": "baska_firma"})["niyet_dogru"]
    assert not degerlendir(SET["T12"], {**s, "niyet": "belge"})["niyet_dogru"]
    assert not degerlendir(SET["T01"], {**s, "niyet": "kapsam_disi"})["niyet_dogru"]


def test_beklenen_tarih_veritabaniyla_uyumlu():
    # Son ödeme günleri resmî tatile göre kaydırıldı (Y055: 31.10 cumartesi -> 02.11 pazartesi)
    assert "02.11.2026" in SET["T04"]["beklenen_cevap"]
