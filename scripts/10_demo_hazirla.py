"""SUNUM veritabanını (data/demo.db) baştan kurar: temiz, tutarlı ve 2 Aralık 2026'ya göre gerçekçi.

Neden ayrı veritabanı? Geliştirme veritabanında (data/muhasebe.db) denemelerden kalan kayıtlar var
(deneme planlı kayıtları, talepler, loglar) ve testler o veritabanının 11 Kasım senaryosuna göre yazıldı.
Sunum veritabanı her çalıştırmada SIFIRDAN kurulur; demoda oluşan talep/kayıtlar bir sonraki sunumu bozmaz.

Kullanım (proje klasöründen):
    python scripts/10_demo_hazirla.py            # demo.db'yi kur / sıfırla
.env'de şu iki satır olmalı (uygulama demo veritabanını ve sunum gününü kullansın):
    MUHASEBE_DB=data/demo.db
    BUGUN=2026-12-02
Geliştirmeye dönmek için bu iki satırın başına # koyun.

Senaryo (2 Aralık 2026, Çarşamba):
- Ekim dönemi KDV, Muhtasar ve SGK primleri (son günleri 26 ve 30 Kasım) ZAMANINDA ödenmiş.
- Demo Gıda'nın (F001) 2026/3 geçici vergisi ödenmemiş: 17.11'den beri gecikmiş -> uyarı + gecikme zammı örneği.
  Demo Yazılım ve Demo Tekstil geçici vergilerini ödemiş; Demo Tekstil'in Eylül SGK primi CSV'deki gibi gecikmiş.
- Kasım maaşları ödenmiş (Ekim bordrosuyla aynı ücretler; Kasım muhtasarı Aralık'ta beyan edileceği için yok).
- Kasım dönemi beyannameleri henüz verilmedi -> Aralık vergileri kayıtta yok, asistan ve panel TAHMİN gösterir.
- Her firmanın Aralık için birkaç planlı ödeme/tahsilatı var (kira, kredi taksiti, beklenen müşteri ödemesi).
Tüm firmalar, kişiler ve tutarlar KURGUSALDIR.
"""
import importlib.util
import os
import sys
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
DEMO_DB = "data/demo.db"
os.environ["MUHASEBE_DB"] = DEMO_DB  # 01_veritabani_kur ve app.db bu yolu kullansın (config import edilmeden ÖNCE)
os.environ["BUGUN"] = "2026-12-02"
sys.path.insert(0, str(KOK))

# Ekim dönemi ödemeleri: (kayıt no, ödeme tarihi) — hepsi son günden önce
ODEMELER = {
    "Y017": "2026-11-25", "Y016": "2026-11-27", "Y018": "2026-11-28",   # Demo Gıda: Muhtasar, KDV, SGK
    "Y037": "2026-11-24", "Y036": "2026-11-27", "Y038": "2026-11-27",   # Demo Yazılım
    "Y057": "2026-11-25", "Y056": "2026-11-30", "Y058": "2026-11-30",   # Demo Tekstil
    "Y040": "2026-11-16", "Y060": "2026-11-17",                         # geçici vergi (F002, F003)
}
# Aralık planlı kayıtları: (firma, yön, tarih, tutar, açıklama, karşı taraf)
PLANLI = [
    ("F001", "Gider", "2026-12-05", 42000.00, "Depo kirası (Aralık)", "Mert Gayrimenkul (kurgusal)"),
    ("F001", "Gelir", "2026-12-10", 118500.00, "Toptan satış tahsilatı", "Anadolu Lojistik (kurgusal)"),
    ("F001", "Gider", "2026-12-15", 86400.00, "Un ve yağ alımı (tedarikçi)", "Trakya Un Sanayi (kurgusal)"),
    ("F001", "Gider", "2026-12-18", 24750.00, "Fırın makinesi kredi taksiti (9/24)", "Demo Bank (kurgusal)"),
    ("F001", "Gelir", "2026-12-22", 64000.00, "Yılbaşı siparişi ön ödemesi", "Kent AVM Mağazaları (kurgusal)"),
    ("F002", "Gider", "2026-12-04", 28000.00, "Ofis kirası (Aralık)", "Plaza Yönetimi (kurgusal)"),
    ("F002", "Gelir", "2026-12-12", 240000.00, "Yazılım lisansı yıllık yenileme", "Delta Sigorta (kurgusal)"),
    ("F002", "Gider", "2026-12-20", 36500.00, "Sunucu ve bulut hizmeti (yıllık)", "Bulut Veri Merkezi (kurgusal)"),
    ("F003", "Gider", "2026-12-06", 15500.00, "Atölye kirası (Aralık)", "Çarşı İş Hanı (kurgusal)"),
    ("F003", "Gelir", "2026-12-16", 52000.00, "Kumaş siparişi tahsilatı", "Moda Butik (kurgusal)"),
]
KASIM_MAAS_GUNU = "2026-11-30"


def _modul(ad):
    spec = importlib.util.spec_from_file_location(ad.replace(".py", ""), KOK / "scripts" / ad)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def kur():
    kurucu = _modul("01_veritabani_kur.py")  # CSV'lerden şema + veri (yalnızca demo.db'yi siler/kurar)
    assert str(kurucu.DB_YOLU).endswith(DEMO_DB), kurucu.DB_YOLU  # geliştirme veritabanına asla dokunma
    con, _ = kurucu.kur()
    con.close()

    import app.db as db  # şema güncellemeleri (planlı kayıtlar, fatura vadeleri) ilk bağlantıda eklenir
    con = db.baglan()
    for yid, tarih in ODEMELER.items():
        con.execute("UPDATE yukumlulukler SET durum = 'Ödendi', odeme_tarihi = ? WHERE id = ?", (tarih, yid))
    # Kasım bordrosu: Ekim'in aynısı (ücretler değişmedi), Kasım sonunda ödendi
    con.execute("DELETE FROM bordrolar WHERE donem = '2026-11'")
    con.execute("""INSERT INTO bordrolar (id, firma_id, calisan_id, donem, brut_tl, sgk_isci_tl, issizlik_isci_tl,
                                          gelir_vergisi_tl, damga_vergisi_tl, net_tl, odeme_tarihi)
                   SELECT id || '-2026-11', firma_id, calisan_id, '2026-11', brut_tl, sgk_isci_tl, issizlik_isci_tl,
                          gelir_vergisi_tl, damga_vergisi_tl, net_tl, ?
                   FROM bordrolar WHERE donem = '2026-10'""", (KASIM_MAAS_GUNU,))
    kullanici = {r["firma_id"]: r["id"] for r in con.execute("SELECT id, firma_id FROM kullanicilar")}
    con.execute("DELETE FROM planli_islemler")
    con.executemany("""INSERT INTO planli_islemler (firma_id, yon, tarih, tutar_tl, aciklama, karsi_taraf,
                                                    ekleyen_id, olusturma)
                       VALUES (?, ?, ?, ?, ?, ?, ?, '2026-11-28T10:00:00')""",
                    [(f, y, t, tu, a, k, kullanici.get(f)) for f, y, t, tu, a, k in PLANLI])
    for tablo in ("talepler", "loglar", "gonderimler", "denetim", "giris_denemeleri", "onay_tokenlari"):
        if con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (tablo,)).fetchone():
            con.execute(f"DELETE FROM {tablo}")
    con.commit()
    con.close()
    return db


def kontrol(db):
    from app.config import BUGUN
    print(f"Demo veritabanı: {db.DB_YOLU}\nSunum günü: {BUGUN}\n")
    tamam = True
    for fid in ("F001", "F002", "F003"):
        gecikmis = db.calistir("gecikmis", fid)
        planli = db.planli_islemler(fid)
        bordro = db.calistir("ay_bordrosu", fid, "2026-11") if "ay_bordrosu" in db.SORGULAR else []
        print(f"{fid}: gecikmiş {[(s['tur'], s['tutar_tl']) for s in gecikmis]} · Aralık planlı {len(planli)} kayıt"
              f" · Kasım bordrosu {len(bordro)} satır")
    g = [s["id"] for s in db.calistir("gecikmis", "F001")]
    ok = g == ["Y020"]
    tamam &= ok
    print("\nOK   " if ok else "\nHATA ", "Demo Gıda'nın yalnızca geçici vergisi gecikmiş (Y020)")
    bos = db.baglan().execute("SELECT COUNT(*) FROM talepler").fetchone()[0] == 0
    tamam &= bos
    print("OK   " if bos else "HATA ", "talep kuyruğu boş")
    print("\nSONUÇ:", "Demo hazır ✅" if tamam else "Kontrol GEÇMEDİ ❌")
    return tamam


if __name__ == "__main__":
    sys.exit(0 if kontrol(kur()) else 1)
