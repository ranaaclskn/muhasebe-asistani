"""Rana'nın arayüz denemelerinde bulduğu hatalar için kalıcı testler (model GEREKMEZ).
Gerçek veritabanına dokunmaz: data/muhasebe.db'nin geçici KOPYASINDA çalışır.
Çalıştır (proje klasöründen):  python -m pytest -q tests/test_kullanici_hatalari.py
"""
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))

import app.db as db  # noqa: E402
from app.dogrulama import kanit_eslestir  # noqa: E402
from app.bordro import bordro_cevabi, bordro_kalibi, calisan_bul  # noqa: E402
from app.rag import takvim_cevabi  # noqa: E402
from app.kayit import cevapla_kayit, planli_aciklama_cevabi, tl  # noqa: E402
from app.niyet import kural_duzelt  # noqa: E402


@pytest.fixture(autouse=True)
def gecici_db(tmp_path, monkeypatch):
    kopya = tmp_path / "test.db"
    shutil.copy(KOK / "data" / "muhasebe.db", kopya)
    monkeypatch.setattr(db, "DB_YOLU", kopya)
    monkeypatch.setattr(db, "_SEMA_GUNCEL", False)
    db.baglan().execute("DELETE FROM planli_islemler").connection.commit()  # kopyada temiz başla


def belge(metin, kaynak="x.txt"):
    return SimpleNamespace(page_content=metin, metadata={"kaynak": kaynak})


# --- A: uydurma yüzde/sayı yakalanır ("ev satın alma ücreti %15" hatası) ---
def test_uydurma_yuzde_yakalanir():
    doc = belge("Brüt ücret toplamı: 143.002,73 TL\nMuhtasar ödenecek tutar: 21.450,41 TL")
    k = kanit_eslestir("Ev satın alma ücreti genellikle %15'lik bir tutardır.", [doc])
    assert "15" in k["uydurma_sayilar"]


def test_dogru_sayilar_gecer():
    doc = belge("KDV beyannamesi dönemi izleyen ayın 28'i akşamına kadar verilir. Ödenecek KDV: 44.307,46 TL")
    assert kanit_eslestir("Ayın 28'ine kadar verilir; ödenecek KDV 44.307,46 TL.", [doc])["uydurma_sayilar"] == []


# --- D/E: niyet kod kuralları (model 'belge' dese bile) ---
@pytest.mark.parametrize("soru, sorgu, parametreler", [
    ("Ekim faturalarımı göster", "faturalar", ["2026-10"]),
    ("eylül ayında kaç tl gecikmiş ödemem vardı", "gec_odenenler", []),
    ("son 1 sene içinde ödediğim gecikmiş ödeme tutarı nedir", "gec_odenenler", []),
    ("Gecikmiş ödemem var mı?", "gecikmis", []),
    # Yaklaşan ödemeler: kaç tane istenirse o kadar (rakam ya da yazıyla)
    ("önümüzdeki en yakın 3 ödemeyi göster", "yaklasanlar", ["3"]),
    ("en yakın 4 ödememi göster", "yaklasanlar", ["4"]),
    ("sıradaki beş ödemem ne", "yaklasanlar", ["5"]),
    ("önümüzdeki 6 tane ödemeyi listele", "yaklasanlar", ["6"]),
    ("2 yaklaşan ödememi göster", "yaklasanlar", ["2"]),
    ("en yakın on iki ödeme", "yaklasanlar", ["12"]),
    ("önümüzeki 4 ödeme ne kadar", "yaklasanlar", ["4"]),  # yazım hatası (model Temmuz uydurmuştu)
    ("siradaki 2 odeme", "yaklasanlar", ["2"]),
    ("gelecek 3 ödemem ne", "yaklasanlar", ["3"]),
    # Ay toplamı: bu ay/gelecek -> ödenecekler, geçmiş ay -> o ay ödenenler
    ("kasım ayında gelen toplam ödeme ne kadar", "ay_odemeleri", ["2026-11"]),
    ("ekim ayında toplam ödeme ne kadar", "odenenler", ["2026-10"]),
])
def test_niyet_kurallari(soru, sorgu, parametreler):
    n = kural_duzelt(soru, {"niyet": "belge", "sorgu": None, "parametreler": []})
    assert (n["niyet"], n["sorgu"], n["parametreler"]) == ("kayit", sorgu, parametreler)


@pytest.mark.parametrize("adet", ["3", "4"])
def test_yaklasanlar_istenen_adet_kadar(adet):
    r = cevapla_kayit("en yakın ödemeler", "F001", {"sorgu": "yaklasanlar", "parametreler": [adet]})
    assert len(r["satirlar"]) == int(adet)
    assert r["cevap"].startswith(f"Sıradaki {adet} ödemeniz")


def test_yaklasanlar_az_kayit_varsa_soyler():
    r = cevapla_kayit("en yakın 10 ödeme", "F001", {"sorgu": "yaklasanlar", "parametreler": ["10"]})
    assert len(r["satirlar"]) < 10 and "10 ödeme istediniz" in r["cevap"]


@pytest.mark.parametrize("soru", ["SGK primini geç ödersem ne olur?", "Geçici vergi ne zaman ödenir?"])
def test_genel_sorular_belge_kalir(soru):
    assert kural_duzelt(soru, {"niyet": "belge", "sorgu": None, "parametreler": []})["niyet"] == "belge"


def test_fatura_odeme_plani_fatura_sorgusu_degil():
    n = kural_duzelt("elektrik faturası 10 Aralık ödeyeceğim", {"niyet": "belge", "sorgu": None, "parametreler": []})
    assert n.get("sorgu") != "faturalar"


# --- E: geç ödenenler, şu anki gecikmişten AYRI ---
def test_gec_odenenler():
    assert cevapla_kayit("x", "F001", {"sorgu": "gec_odenenler", "parametreler": []})["cevap"].startswith(
        "Kayıtlarınıza göre geç ödenmiş bir ödemeniz yok")
    con = db.baglan()  # Eylül SGK'yı (son tarih 31.10) 03.11'de ödenmiş gibi yap
    con.execute("UPDATE yukumlulukler SET odeme_tarihi = '2026-11-03' WHERE id = 'Y015'")
    con.commit()
    satirlar = db.calistir("gec_odenenler", "F001")
    assert [s["id"] for s in satirlar] == ["Y015"]
    assert db.calistir("gecikmis", "F001") == []  # ödenmiş olduğu için "şu an gecikmiş" DEĞİL


# --- C: kendi kayıtlarında açıklamaya göre arama ---
def test_aciklama_aramasi():
    db.planli_islem_ekle("F001", 1, "Gelir", "2026-11-11", 450000, "Ev satın alma ücreti")
    db.planli_islem_ekle("F002", 2, "Gelir", "2026-11-11", 999, "Ev satın alma ücreti başka firma")
    r = planli_aciklama_cevabi("ev satın alma ücreti ne", "F001")
    assert r and "450.000,00 TL" in r["cevap"] and "999" not in r["cevap"]
    assert planli_aciklama_cevabi("Geçici vergi ne zaman ödenir?", "F001") is None


# --- Model soruda olmayan bir ay uydurursa soru kazanır ---
@pytest.mark.parametrize("soru, sorgu, parametreler", [
    ("önümüzeki 4 ödeme ne kadar", "yaklasanlar", ["4"]),
    ("gelecek ay ödemelerim", "ay_odemeleri", ["2026-12"]),
    ("önümüzeki ay ödemelerim", "ay_odemeleri", ["2026-12"]),
])
def test_uydurulan_ay_duzeltilir(soru, sorgu, parametreler):
    model = {"niyet": "kayit", "sorgu": "odenenler", "parametreler": ["2026-07"]}  # arayüzde görülen
    n = kural_duzelt(soru, model)
    assert (n["sorgu"], n["parametreler"]) == (sorgu, parametreler)


# --- Tahmin: "önümüzdeki ay SGK primini tahmin et" RAG'a gidip alakasız cevap veriyordu ---
@pytest.mark.parametrize("soru, parametreler", [
    ("önümüzdeki ay sgk primini tahmin eder misin", ["2026-12", "SGK primi"]),
    ("gelecek ay ne kadar vergi ödeyeceğimi tahmin et", ["2026-12"]),
    ("aralık KDV tahmini", ["2026-12", "KDV"]),
])
def test_tahmin_niyeti(soru, parametreler):
    n = kural_duzelt(soru, {"niyet": "belge", "sorgu": None, "parametreler": []})
    assert (n["niyet"], n["sorgu"], n["parametreler"]) == ("kayit", "tahmin", parametreler)


def test_tahmin_son_3_donem_ortalamasi():
    r = cevapla_kayit("x", "F001", {"sorgu": "tahmin", "parametreler": ["2026-12", "SGK primi"]})
    gecmis = db.calistir("donem_gecmisi", "F001", "SGK primi")
    ort = round(sum(g["tutar_tl"] for g in gecmis) / len(gecmis), 2)
    assert len(gecmis) == 3 and tl(ort) in r["cevap"] and "tahmindir" in r["cevap"]


def test_tahmin_kayit_varsa_gercek_tutar():
    r = cevapla_kayit("x", "F001", {"sorgu": "tahmin", "parametreler": ["2026-11", "KDV"]})
    assert "tahmin değil, kayıtta var" in r["cevap"] and "tahmindir" not in r["cevap"]


# --- Maaş / çalışan soruları: bordrolar tablosundan, hesap Python'da (RAG "kayıtlarınızda yok" diyordu) ---
def _ay_toplami(firma, donem):
    return next(r for r in db.calistir("bordro_aylik_toplam", firma) if r["donem"] == donem)


def test_bordro_verisi_beyannameyle_tutarli():
    for r in db.calistir("bordro_aylik_toplam", "F001"):
        muh = db.calistir("durum", "F001", "Muhtasar", r["donem"])[0]["tutar_tl"]
        assert r["gelir_vergisi_tl"] == muh and r["brut_tl"] == round(muh / 0.15, 2)
        assert r["net_tl"] == round(r["brut_tl"] - r["sgk_isci_tl"] - r["issizlik_isci_tl"]
                                    - r["gelir_vergisi_tl"] - r["damga_vergisi_tl"], 2)


def test_bordro_toplam_ve_ortalama_net():
    son = _ay_toplami("F001", "2026-10")
    toplam = bordro_cevabi("bir ayda ödenen toplam maaş miktarı ne kadar", "F001")["cevap"]
    assert tl(son["net_tl"]) in toplam and tl(son["brut_tl"]) in toplam
    ort = bordro_cevabi("ortalama net maaş ne kadar", "F001")["cevap"]
    assert tl(round(son["net_tl"] / son["kisi"], 2)) in ort


def test_elemanlara_odenen_tutarlar_kisi_kisi():
    r = bordro_cevabi("elemanlara ödenen tutarlar", "F001")
    assert len(r["satirlar"]) == 24 and all(s["donem"] == "2026-10" for s in r["satirlar"])
    assert tl(_ay_toplami("F001", "2026-10")["net_tl"]) in r["cevap"]


def test_calisana_ozel_odeme():
    kisi = db.calistir("calisan_listesi", "F001")[0]
    ad, soyad = kisi["ad_soyad"].split()
    r = bordro_cevabi(f"{ad}'ya eylülde ne kadar maaş ödendi", "F001")
    eylul = next(s for s in db.calistir("calisan_bordrosu", "F001", kisi["id"]) if s["donem"] == "2026-09")
    assert kisi["ad_soyad"] in r["cevap"] and tl(eylul["net_tl"]) in r["cevap"]
    tum = bordro_cevabi(f"{ad} {soyad} ne kadar maaş aldı", "F001")
    assert len(tum["satirlar"]) == 6 and "Toplam net" in tum["cevap"]


def test_en_yuksek_ve_en_dusuk_maas():
    ekim = db.calistir("ay_bordrosu", "F001", "2026-10")
    assert ekim[0]["ad_soyad"] in bordro_cevabi("en yüksek maaşı kim alıyor", "F001")["cevap"]
    r = bordro_cevabi("en düşük 3 maaş", "F001")
    assert [s["id"] for s in r["satirlar"]] == [s["id"] for s in ekim[::-1][:3]]


def test_beyannamedeki_net_ucret_toplami():  # RAG ortalamayı toplam diye veriyordu
    r = bordro_cevabi("Ekim muhtasar beyannamesinde net ücret toplamı ne kadar", "F001")["cevap"]
    assert tl(_ay_toplami("F001", "2026-10")["net_tl"]) in r


def test_bordro_olmayan_ay():
    assert "bordrosu kayıtlarınızda yok" in bordro_cevabi("bu ay maaşlara ne kadar ödedim", "F001")["cevap"]


def test_turkce_ek_ile_isim_eslesir():
    calisanlar = [{"id": "C1", "ad_soyad": "Ayşe Yılmaz"}, {"id": "C2", "ad_soyad": "Ayşegül Kaya"}]
    assert [c["id"] for c in calisan_bul("ayşeye ne kadar ödedim", calisanlar)] == ["C1"]
    assert [c["id"] for c in calisan_bul("Ayşe'nin maaşı", calisanlar)] == ["C1"]


@pytest.mark.parametrize("soru", ["ev satın alma ücreti ne", "KDV ne zaman ödenir?", "firmamızda kaç personel var",
                                  "Kaya Market'e ne kadar ödedim", "Ekim muhtasar beyannamesinde ödenecek tutar ne"])
def test_bordro_disindaki_sorular(soru):
    assert not bordro_kalibi(soru, "F001")


def test_bordro_firma_izolasyonu():
    f1 = {c["id"] for c in db.calistir("calisan_listesi", "F001")}
    r = bordro_cevabi("elemanlara ödenen tutarlar", "F001")
    assert all(s["firma_id"] == "F001" and s["calisan_id"] in f1 for s in r["satirlar"])
    # Başka firmanın çalışan adı sorulursa bulunmaz (yalnız kendi listesinde aranır)
    f1_isimler = {p for x in db.calistir("calisan_listesi", "F001") for p in x["ad_soyad"].split()}
    f2_yalniz = [c for c in db.calistir("calisan_listesi", "F002") if not set(c["ad_soyad"].split()) & f1_isimler]
    assert calisan_bul(f2_yalniz[0]["ad_soyad"] + " maaşı", db.calistir("calisan_listesi", "F001")) == []


# --- Takvim soruları: model cümleyi bozuyordu ("28 Ekim'de ödüllendirilir"); takvimden AYNEN alıntı ---
@pytest.mark.parametrize("soru, olmali", [
    ("KDV ne zaman ödenir?", "28'i"), ("Muhtasar ne zaman ödenir?", "26'sına"),
    ("SGK primi ne zaman ödenir?", "son gününe"), ("Geçici vergi ne zaman ödenir?", "17'si"),
])
def test_takvim_aynen_alinti(soru, olmali):
    c = takvim_cevabi(soru)
    assert olmali in c and c.endswith("[kaynak: vergi_takvimi.txt]")


@pytest.mark.parametrize("soru", ["Ekim KDV ne zaman ödedim", "SGK primini geç ödersem ne olur?"])
def test_takvim_disindaki_sorular(soru):
    assert takvim_cevabi(soru) is None


# --- Beyanname tutarı: aynı belgede Muhtasar/SGK/ücret yan yana; model yanlış satırı seçebiliyordu (T07) ---
@pytest.mark.parametrize("soru, firma, olmali, kaynak", [
    ("Temmuz muhtasar beyannamesinde ne kadar bildirildi?", "F003", "5.663,02", "F003_MUHSGK_2026-07.txt"),
    ("Eylül KDV beyannamemde ödenecek KDV ne kadardı?", "F001", "44.307,46", "F001_KDV_2026-09.txt"),
])
def test_beyanname_satiri_aynen(soru, firma, olmali, kaynak):
    from app.rag import beyanname_satiri
    c = beyanname_satiri(soru, firma)
    assert olmali in c and c.endswith(f"[kaynak: {kaynak}]")
