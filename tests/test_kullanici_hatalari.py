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
    # Gelecek / henüz ödenmemiş ay -> son 3 ay ortalamasıyla TAHMİN; bordrosu olmayan GEÇMİŞ ay -> kayıt yok
    c = bordro_cevabi("bu ay maaşlara ne kadar ödedim", "F001")["cevap"]
    assert "henüz ödenmedi" in c and "tahmin" in c
    assert "bordrosu kayıtlarınızda yok" in bordro_cevabi("ocak ayında ödediğim maaşlar", "F001")["cevap"]


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


# --- Görevlere göre maaş ("paketleme elemanlarına geçen ay ödenen maaş", "eleman türlerine göre") ---
def test_goreve_gore_gecen_ay():
    r = bordro_cevabi("paketleme elemanlarına geçen ay ödenen maaş miktarı nedir", "F001")
    ekim = [s for s in db.calistir("ay_bordrosu", "F001", "2026-10") if s["gorev"] == "Paketleme elemanı"]
    assert {s["id"] for s in r["satirlar"]} == {s["id"] for s in ekim}
    assert tl(round(sum(s["net_tl"] for s in ekim), 2)) in r["cevap"]


def test_gorev_turlerine_gore_ozet():
    r = bordro_cevabi("eleman türlerine göre maaş miktarları", "F001")
    gorevler = {c["gorev"] for c in db.calistir("calisan_listesi", "F001")}
    assert all(f"**{g}**" in r["cevap"] for g in gorevler)
    assert tl(_ay_toplami("F001", "2026-10")["net_tl"]) in r["cevap"]  # genel toplam = ay toplamı


@pytest.mark.parametrize("soru, gorev", [("şoförlere ne kadar maaş ödedim", "Şoför"),
                                         ("üretim şefine ne kadar maaş ödendi", "Üretim şefi")])
def test_gorev_eslestirme(soru, gorev):
    assert {s["gorev"] for s in bordro_cevabi(soru, "F001")["satirlar"]} == {gorev}


@pytest.mark.parametrize("soru", ["depo kirası ne kadar ödedim", "satış faturalarım ne kadar"])
def test_kismi_gorev_kelimesi_bordro_degil(soru):  # "depo" / "satış" tek başına görev sayılmaz
    assert not bordro_kalibi(soru, "F001")


def test_maas_esigi_ve_karsilastirma():
    r = bordro_cevabi("net maaşı 4000 TL üstü olan çalışanlar", "F001")
    assert r["satirlar"] and all(s["net_tl"] > 4000 for s in r["satirlar"])
    k = bordro_cevabi("maaş giderleri geçen aya göre arttı mı", "F001")["cevap"]
    assert "Eylül 2026" in k and "Ekim 2026" in k and "azaldı" in k


def test_personel_maliyeti():
    t = _ay_toplami("F001", "2026-10")
    sgk = db.calistir("durum", "F001", "SGK primi", "2026-10")[0]["tutar_tl"]
    maliyet = round(t["brut_tl"] + round(sgk - t["sgk_isci_tl"] - t["issizlik_isci_tl"], 2), 2)
    assert tl(maliyet) in bordro_cevabi("personel maliyetim ne kadar", "F001")["cevap"]


def test_kidem():
    en_eski = min(db.calistir("calisan_listesi", "F001"), key=lambda c: c["ise_giris"])
    r = bordro_cevabi("en eski çalışanım kim", "F001")
    assert len(r["satirlar"]) == 1 and en_eski["ad_soyad"] in r["cevap"]


# --- Bugün = GERÇEK tarih: son tarihi geçmiş ödenmemiş kayıt "Gecikti" sayılır, yaklaşanlarda görünmez ---
def test_son_tarihi_gecen_gecikti_sayilir(monkeypatch):
    monkeypatch.setattr(db, "BUGUN", "2026-11-21")  # geçici vergi son günü 17.11.2026
    assert [s["id"] for s in db.calistir("gecikmis", "F001")] == ["Y020"]
    assert "Y020" not in [s["id"] for s in db.calistir("yaklasanlar", "F001", "5")]
    bu_ay = {s["id"]: s["durum"] for s in db.calistir("ay_odemeleri", "F001", "2026-11")}
    assert bu_ay["Y020"] == "Gecikti" and bu_ay["Y017"] == "Bekliyor"
    assert {s["id"]: s["durum"] for s in db.yukumlulukler("F001")}["Y020"] == "Gecikti"  # panel kartları


@pytest.mark.parametrize("soru", ["son ödeme tarihi geçmiş ödemeleri getir", "vadesi geçen borçlarım",
                                  "son tarihi geçti mi ödemelerimin"])
def test_gecikmis_ifadeleri(soru):
    for model in ({"niyet": "belge", "sorgu": None, "parametreler": []},
                  {"niyet": "kayit", "sorgu": "ay_odemeleri", "parametreler": ["2026-11"]}):
        n = kural_duzelt(soru, model)
        assert (n["niyet"], n["sorgu"]) == ("kayit", "gecikmis")


# --- SSS: model "SGK primi ÖDEMEYEBİLİRSİNİZ" yazmıştı; SSS cevabı aynen + yanıltıcı ifade koruması ---
def test_sss_aynen_ve_yaniltici_ifade():
    from app.rag import YANILTICI, sss_cevabi
    c = sss_cevabi("SGK primini geç ödersem ne olur?")
    assert c.startswith("SGK primi son ödeme tarihinde ödenmezse") and c.endswith("[kaynak: sss.txt]")
    assert YANILTICI.search("SGK primi ödemeyebilirsiniz.") and not YANILTICI.search(c)
    n = kural_duzelt("SGK primini geç ödersem ne olur?", {"niyet": "kayit", "sorgu": "gecikmis", "parametreler": []})
    assert n["niyet"] == "belge"



# --- "kasım ayında ödenecek toplam maaç" (yazım hatası) yıllık vergi özetine gidiyordu ---
def test_maas_yazim_hatasi_ve_gelecek_ay_tahmini():
    son3 = [r for r in db.calistir("bordro_aylik_toplam", "F001")][-3:]
    ort = round(sum(r["net_tl"] for r in son3) / 3, 2)
    for soru in ["kasım ayında ödenecek toplam maaç ne kadar", "aralık ayında toplam ödenecek maaş tutarı ne"]:
        assert bordro_kalibi(soru, "F001")
        c = bordro_cevabi(soru, "F001")["cevap"]
        assert "tahmin" in c and tl(ort) in c


@pytest.mark.parametrize("soru, ay", [
    ("gelecek ocak ayındaki toplam giderler ne kadar", "2027-01"), ("ocakta ödenecek vergiler", "2027-01"),
    ("ocak ayında ödediğim KDV", "2026-01"), ("geçen aralık ödemelerim", "2025-12"),
    ("aralık ayında toplam ödenecek maaş", "2026-12"),
])
def test_ay_adinin_yili(soru, ay):  # bugün Kasım 2026: geçmiş ay adı + gelecek zaman -> gelecek yıl
    from app.niyet import _kucuk, _soru_ayi
    assert _soru_ayi(_kucuk(soru)) == ay


def test_aylik_gider_gelecek_ay():
    n = kural_duzelt("gelecek ocak ayındaki toplam giderler ne kadar", {"niyet": "belge", "sorgu": None, "parametreler": []})
    assert (n["sorgu"], n["parametreler"]) == ("aylik_gider", ["2027-01"])
    db.planli_islem_ekle("F001", None, "Gider", "2027-01-05", 20000, "Depo kirası", "Ev sahibi")
    c = cevapla_kayit("x", "F001", n)["cevap"]
    for parca in ["KDV: yaklaşık", "Muhtasar: yaklaşık", "SGK primi: yaklaşık", "çalışana net yaklaşık",
                  "Depo kirası", "20.000,00 TL", "Toplam: yaklaşık"]:
        assert parca in c


def test_aylik_gider_gecmis_ay_gercek():  # geçmiş ay: tahmin yok, ödenen vergi + ödenen net maaş
    c = cevapla_kayit("x", "F001", {"sorgu": "aylik_gider", "parametreler": ["2026-10"]})["cevap"]
    vergi = round(sum(s["tutar_tl"] for s in db.calistir("odenenler", "F001", "2026-10")), 2)
    assert "yaklaşık" not in c and tl(round(vergi + _ay_toplami("F001", "2026-10")["net_tl"], 2)) in c


def test_gelecek_ay_odemeleri_tahmin_ve_yaklasanlar():
    r = cevapla_kayit("x", "F001", {"sorgu": "ay_odemeleri", "parametreler": ["2026-12"]})
    assert "henüz kayıtlı yükümlülük yok" in r["cevap"] and "tahmin" in r["cevap"]
    n = kural_duzelt("gelecek ödemelerim ne kadar", {"niyet": "kayit", "sorgu": "yil_odenenler", "parametreler": ["2026"]})
    assert n["sorgu"] == "yaklasanlar"


# --- "gecikmiş ödemelerimin faizi" : model ana borcu (54.938,65 TL) "faiz" diye sunmuştu ---
def test_gecikme_faizi_ana_borcu_faiz_demez(monkeypatch):
    import app.kayit as kayit
    monkeypatch.setattr(db, "BUGUN", "2026-11-21")
    monkeypatch.setattr(kayit, "BUGUN", "2026-11-21")
    n = kural_duzelt("kasım ayında gecikmiş ödemelerimin faizi var mı varsa ne kadar",
                     {"niyet": "kayit", "sorgu": "gecikmis", "parametreler": []})
    assert (n["sorgu"], n["parametreler"]) == ("gecikme_faizi", ["2026-11"])
    c = cevapla_kayit("x", "F001", n)["cevap"]
    assert "ana borç **54.938,65 TL**" in c and "4 gündür gecikmiş" in c
    assert "faiz değil" in c  # ana borç faiz diye sunulmaz
    # tahmini gecikme zammı: 54.938,65 × %3,7 / 30 × 4 gün = 271,03 TL (oran cevapta açıkça yazılı)
    assert "**271,03 TL**" in c and "**55.209,68 TL**" in c and "%3,7" in c and "tahmini" in c


# --- "geciken ödemeler nedir faizleriyle beraber toplam ödenecek tutar nedir": faiz kısmı atlanıyordu ---
@pytest.mark.parametrize("soru", ["geciken ödemeler nedir faizleriyle beraber toplam ödenecek tutar nedir",
                                  "son ödeme tarihi geçen ödemelerimin faiz tutarı nedir"])
def test_faizli_toplam_sorusu_gecikme_faizine_gider(soru):
    n = kural_duzelt(soru, {"niyet": "kayit", "sorgu": "gecikmis", "parametreler": []})
    assert n["sorgu"] == "gecikme_faizi"


def test_gecikme_zammi_hesabi_ve_sgk_tahmin_edilmez(monkeypatch):
    import app.kayit as kayit
    assert kayit.gecikme_zammi(54938.65, 4, 3.7) == 271.03
    assert kayit.gecikme_zammi(1000, 30, 3.7) == 37.0   # tam bir ay = aylık oran
    assert kayit.gecikme_zammi(1000, -2, 3.7) == 0      # vadesi gelmemişse zam yok
    monkeypatch.setattr(db, "BUGUN", "2026-11-21")
    monkeypatch.setattr(kayit, "BUGUN", "2026-11-21")
    c = kayit.gecikme_faizi_cevabi("F003")["cevap"]  # SGK primi (21 gün) + geçici vergi (4 gün)
    assert "SGK hesaplar" in c and "tahmin vermiyorum" in c
    assert "**84,97 TL**" in c and "SGK priminin cezası/zammı hariç" in c
    assert tl(21306.57 * 0.037 / 30 * 21) not in c  # SGK için zam rakamı uydurulmaz


def test_model_cevabinda_uydurma_kavram_reddedilir():
    from app.kayit import cevap_dogrula
    veri = "Geçici vergi, 2026/3 dönemi: 54.938,65 TL, son ödeme tarihi 17.11.2026, durum: Gecikti"
    satir = [{"tutar_tl": 54938.65, "durum": "Gecikti"}]
    assert not cevap_dogrula("Gecikmiş ödemelerinizin faizi 54.938,65 TL'dir.", veri, satir)["gecerli"]
    assert cevap_dogrula("Gecikmiş ödemeniz 54.938,65 TL'dir.", veri, satir)["gecerli"]


@pytest.mark.parametrize("soru", ["SGK primini geç ödersem ne olur?", "kredi faiz oranı nedir"])
def test_genel_faiz_sorulari_belgeye(soru):
    assert kural_duzelt(soru, {"niyet": "kayit", "sorgu": "gecikmis", "parametreler": []})["niyet"] == "belge"


# --- "gecikme zammı oranı nedir": oran belgelerde yok, RAG "belgelerinizde yok" diyordu -> KOD cevaplar ---
@pytest.mark.parametrize("soru", ["gecikme zammı oranı nedir", "gecikme faizi yüzde kaç",
                                  "gecikme zammı nasıl hesaplanır"])
@pytest.mark.parametrize("model_niyeti", ["kayit", "belge"])
def test_gecikme_orani_sorusu_koda_gider(soru, model_niyeti):
    n = kural_duzelt(soru, {"niyet": model_niyeti, "sorgu": None, "parametreler": []})
    assert (n["niyet"], n["sorgu"]) == ("kayit", "gecikme_orani")


def test_gecikme_orani_cevabi():
    r = cevapla_kayit("gecikme zammı oranı nedir", "F001", {"sorgu": "gecikme_orani", "parametreler": []})
    c = r["cevap"]
    assert "aylık %3,7" in c and "13.11.2025" in c and "%0,1233" in c
    assert "370,00 TL" in c and "10.370,00 TL" in c  # 10.000 TL × %3,7 × 1 ay
    assert "SGK" in c and r["yontem"] == "gecikme_orani"


# --- "bir şoföre verilecek maaş": tekil + gelecek zaman (iki kişinin listesi ve Ekim geliyordu) ---
def test_bir_sofore_verilecek_maas():
    from app.bordro import maas_tahmini
    t = maas_tahmini("F001", ["Şoför"])
    c = bordro_cevabi("bir şoföre verilecek maaş nedir", "F001")["cevap"]
    assert "Kasım 2026" in c and "bir Şoför için tahmini maaş" in c and tl(t["kisi_net"]) in c
    assert "Merve Karaca" not in c  # kişi listesi değil, kişi başı tutar


def test_bir_sofore_odenen_gecmis_ay():
    ekim = [r for r in db.calistir("ay_bordrosu", "F001", "2026-10") if r["gorev"] == "Şoför"]
    c = bordro_cevabi("bir şoföre ekimde ne kadar maaş ödendi", "F001")["cevap"]
    assert tl(round(sum(r["net_tl"] for r in ekim) / len(ekim), 2)) in c and "ortalama net" in c


def test_bir_ayda_tekil_sayilmaz():
    c = bordro_cevabi("bir ayda ödenen toplam maaş miktarı ne kadar", "F001")["cevap"]
    assert "Çalışanlara ödenen net toplam" in c


# --- "gecikme zammı oranı nedir": model beyannamedeki "%14" (SGK işçi payı) satırını oran diye sunmuştu ---
def test_yuzde_sorunun_satirinda_gecmeli():
    from types import SimpleNamespace
    from app.dogrulama import kanit_eslestir
    d = [SimpleNamespace(page_content="- SGK işçi payı kesintisi (%14): 15.128,24 TL", metadata={"kaynak": "x.txt"})]
    assert kanit_eslestir("Gecikme zammı oranı %14'tür.", d, "gecikme zammı oranı nedir")["uydurma_sayilar"]
    assert not kanit_eslestir("SGK işçi payı %14'tür.", d, "sgk işçi payı oranı kaç")["uydurma_sayilar"]


def test_belgede_olmayan_oran_durustce_soylenir(monkeypatch):
    from types import SimpleNamespace
    import app.rag as rag
    parca = SimpleNamespace(page_content="Ücret ödemeleri özeti\n- SGK işçi payı kesintisi (%14): 15.128,24 TL\n"
                                         "SGK primi gecikirse gecikme zammı uygulanır.",
                            metadata={"kaynak": "F001_MUHSGK_2026-10.txt", "donem": "2026-10"})
    monkeypatch.setattr(rag, "getir", lambda soru, firma_id: [(parca, 1.0, 1.0)])
    monkeypatch.setattr(rag, "llm", lambda: (_ for _ in ()).throw(AssertionError("model çağrılmamalı")))
    assert rag.cevapla_belge("gecikme zammı oranı nedir", "F001")["cevap"] == rag.ORAN_YOK


# --- "maaş giderleri geçmiş 3 aya göre arttı mı" yalnız Eylül → Ekim karşılaştırıyordu ---
def test_gecmis_n_aya_gore_ortalama():
    t = db.calistir("bordro_aylik_toplam", "F001")
    ort = round(sum(r["net_tl"] for r in t[-4:-1]) / 3, 2)  # Ekim'den önceki 3 ay
    c = bordro_cevabi("maaş giderleri geçmiş 3 aya göre arttı mı", "F001")["cevap"]
    assert "önceki 3 ayın" in c and tl(ort) in c and "Temmuz 2026" in c


def test_son_n_ayda_gidisat_ve_n_ay_oncesi():
    c = bordro_cevabi("maaş giderleri son 3 ayda arttı mı", "F001")["cevap"]
    assert "gidişatı" in c and "Eylül'e göre" in c and "Ağustos'a göre" in c
    c = bordro_cevabi("maaş giderleri 3 ay öncesine göre nasıl", "F001")["cevap"]
    assert "Temmuz 2026 → Ekim 2026" in c


# --- İşe alım: "son bir senede kaç kişi işe alındı" firma kartına / kapsam dışına gidiyordu ---
@pytest.mark.parametrize("soru", ["son bir senede kaç kişi işe alındı", "son bir senede işe alınan kişiler kimler"])
def test_ise_alim_yolu(soru, monkeypatch):
    import app.bordro as bordro
    monkeypatch.setattr(bordro, "BUGUN", "2026-11-21")
    assert bordro_kalibi(soru, "F001")
    c = bordro_cevabi(soru, "F001")["cevap"]
    en_son = max(db.calistir("calisan_listesi", "F001"), key=lambda c: c["ise_giris"])
    assert "işe alınan çalışan **yok**" in c and en_son["ad_soyad"] in c  # 10.08.2025'ten beri alım yok


def test_ise_alim_yil_ve_maliyet():
    c = bordro_cevabi("2025 yılında işe alınanlar", "F001")
    beklenen = [x for x in db.calistir("calisan_listesi", "F001") if x["ise_giris"].startswith("2025")]
    assert {x["id"] for x in c["satirlar"]} == {x["id"] for x in beklenen}
    assert "toplam net maaş giderinin %" in c["cevap"]


# --- 2026-11-23 arayüz denemeleri ---
def test_sigorta_primi_yalniz_sgk():  # "sigorta primi" filtre uygulanmıyor, 4 ödemenin hepsi geliyordu
    n = kural_duzelt("bu ayki sigorta primi ödemem ne kadar",
                     {"niyet": "kayit", "sorgu": "ay_odemeleri", "parametreler": ["2026-11"]})
    assert n["sorgu"] == "ay_odemeleri" and n["parametreler"] == ["2026-11", "SGK primi"]


def test_almam_gereken_tahsilattir():  # vergi borçlarını listeliyordu
    n = kural_duzelt("almam gereken ödemeler neler bu ay",
                     {"niyet": "kayit", "sorgu": "ay_odemeleri", "parametreler": ["2026-11"]})
    assert n["sorgu"] == "beklenen_tahsilatlar" and n["parametreler"] == ["2026-11"]


def test_gelecek_ve_gecikmis_ayri_toplanir(monkeypatch):  # gecikmiş borç "gelecek ödeme" toplamına karışıyordu
    monkeypatch.setattr(db, "BUGUN", "2026-11-23")
    c = cevapla_kayit("bu ay gelecek ödemelerim neler", "F001",
                      {"sorgu": "ay_odemeleri", "parametreler": ["2026-11"]})["cevap"]
    assert "Gelecek ödemeler: 110.530,93 TL" in c and "Gecikmiş: 54.938,65 TL" in c
    assert "Ay toplamı: 165.469,58 TL" in c


def test_olustur_onceki_teklife_onaydir():  # "oluştur" genel "Ne yapmamı istersiniz?" cevabı alıyordu
    from app.emirler import emir_cikar, teklif_onayi
    onceki = "bu ay geciken vergilerimin faizi ne kadar"
    for cevap in ["oluştur", "Evet", "oluşturabilirsin", "tamam lütfen"]:
        emir = teklif_onayi(cevap, onceki)
        assert emir and onceki in emir and emir_cikar(emir)["emir"] == "gorusme_talebi"
    assert teklif_onayi("oluştur", None) is None                       # teklif yoksa dokunma
    assert teklif_onayi("KDV beyannamemi gönder", onceki) is None      # yeni bir istek


def test_son_odeme_tarihi_tatile_dusmez():  # Ekim KDV'si 28.11.2026 cumartesi görünüyordu (VUK md. 18)
    import importlib.util
    spec = importlib.util.spec_from_file_location("tatil", KOK / "scripts" / "07_tatil_kaydir.py")
    tatil = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tatil)
    assert tatil.is_gunu("2026-11-28") == "2026-11-30" and tatil.is_gunu("2026-10-29") == "2026-10-30"
    kotu = [r["id"] for r in db.baglan().execute("SELECT id, son_odeme_tarihi FROM yukumlulukler")
            if tatil.is_gunu(r["son_odeme_tarihi"]) != r["son_odeme_tarihi"]]
    assert kotu == []
    s = db.calistir("durum", "F001", "KDV", "2026-10")
    assert s[0]["son_odeme_tarihi"] == "2026-11-30"
