"""Adım 2: SQLite veritabanını kur (şema + CSV yükleme + bcrypt).

Kullanım (proje klasöründen):  python scripts/01_veritabani_kur.py

Her çalıştırmada data/muhasebe.db silinip baştan kurulur (demo verisi; talepler ve
loglar da sıfırlanır). Sonunda CLAUDE.md'deki Kontrol satırını kendisi çalıştırır.
"""
import csv
import sqlite3
import sys
from pathlib import Path

import bcrypt

# scripts/ klasöründen çalıştırınca "app" paketini bulabilmek için proje kökünü ekle
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import CSV_DIR, DB_YOLU  # noqa: E402

SEMA = """
CREATE TABLE firmalar (
    id TEXT PRIMARY KEY,
    unvan TEXT NOT NULL,
    tur TEXT,
    vergi_no TEXT,
    sektor TEXT,
    calisan_sayisi INTEGER
);
CREATE TABLE kullanicilar (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    eposta TEXT UNIQUE NOT NULL,
    sifre_hash TEXT NOT NULL,
    rol TEXT NOT NULL CHECK (rol IN ('firma', 'muhasebeci')),
    firma_id TEXT NULL REFERENCES firmalar(id),
    ad TEXT
);
CREATE TABLE yukumlulukler (
    id TEXT PRIMARY KEY,
    firma_id TEXT NOT NULL REFERENCES firmalar(id),
    tur TEXT NOT NULL,
    donem TEXT NOT NULL,
    tutar_tl REAL NOT NULL,
    son_odeme_tarihi TEXT NOT NULL,
    durum TEXT NOT NULL CHECK (durum IN ('Ödendi', 'Bekliyor', 'Gecikti')),
    odeme_tarihi TEXT NULL
);
CREATE TABLE faturalar (
    id TEXT PRIMARY KEY,
    firma_id TEXT NOT NULL REFERENCES firmalar(id),
    tip TEXT NOT NULL,
    karsi_taraf TEXT,
    tarih TEXT NOT NULL,
    tutar_tl REAL NOT NULL,
    kdv_orani REAL
);
CREATE TABLE belgeler (
    id TEXT PRIMARY KEY,
    firma_id TEXT NOT NULL,          -- F001/F002/F003 veya ORTAK
    tur TEXT,
    donem TEXT NULL,
    dosya_adi TEXT NOT NULL
);
CREATE TABLE talepler (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    firma_id TEXT NOT NULL,
    talep_metni TEXT NOT NULL,       -- kullanıcının yazdığı cümle (olduğu gibi)
    emir TEXT NULL,                  -- EMIRLER menüsünden: belge_gonder | gorusme_talebi
    detay TEXT NULL,                 -- JSON: emir alanları (belge_turu, donem, dosya, eposta...)
    ozet TEXT NULL,                  -- muhasebecinin ne onayladığını gördüğü tek cümle
    durum TEXT DEFAULT 'Onay bekliyor',
    onaylayan_id INTEGER NULL REFERENCES kullanicilar(id),
    olusturma_tarihi TEXT
);
CREATE TABLE loglar (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kullanici_id INTEGER,
    firma_id TEXT,
    soru TEXT,
    niyet TEXT,
    arac TEXT,
    kaynaklar TEXT,                  -- JSON listesi
    cevap TEXT,
    sure_ms INTEGER,
    tarih TEXT
);
-- Sık kullanılan filtre: her sorgu firma_id ile başlar
CREATE TABLE planli_islemler (      -- kullanıcının KENDİ eklediği planlı ödeme / tahsilatlar
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    firma_id TEXT NOT NULL REFERENCES firmalar(id),
    yon TEXT NOT NULL CHECK (yon IN ('Gider', 'Gelir')),
    tarih TEXT NOT NULL,
    tutar_tl REAL NOT NULL CHECK (tutar_tl > 0),
    aciklama TEXT NOT NULL,
    karsi_taraf TEXT,
    ekleyen_id INTEGER,
    olusturma TEXT
);
CREATE INDEX ix_planli_firma ON planli_islemler(firma_id, tarih);
CREATE INDEX ix_yuk_firma ON yukumlulukler(firma_id, son_odeme_tarihi);
CREATE INDEX ix_fat_firma ON faturalar(firma_id, tarih);
"""


def csv_oku(dosya):
    """CSV satırlarını sözlük olarak döndür; boş hücreler None olur (SQL NULL)."""
    with open(CSV_DIR / dosya, encoding="utf-8", newline="") as f:
        return [{k: (v if v != "" else None) for k, v in satir.items()} for satir in csv.DictReader(f)]


def ekle(con, tablo, satirlar, kolonlar, donustur=None):
    """Satırları parametreli (?) INSERT ile tabloya yaz."""
    yer_tutucu = ", ".join("?" for _ in kolonlar)
    sql = f"INSERT INTO {tablo} ({', '.join(kolonlar)}) VALUES ({yer_tutucu})"
    veriler = []
    for s in satirlar:
        if donustur:
            s = donustur(s)
        veriler.append(tuple(s[k] for k in kolonlar))
    con.executemany(sql, veriler)
    return len(veriler)


def sayilari_cevir(alanlar, tip):
    def cevir(s):
        s = dict(s)
        for a in alanlar:
            if s[a] is not None:
                s[a] = tip(s[a])
        return s
    return cevir


def kullanici_hazirla(s):
    """Düz şifreyi bcrypt ile hash'le; düz şifre DB'ye YAZILMAZ."""
    s = dict(s)
    s["sifre_hash"] = bcrypt.hashpw(s.pop("sifre_duz").encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    return s


def kur():
    if DB_YOLU.exists():
        DB_YOLU.unlink()  # yalnızca bu scriptin ürettiği demo DB'si
    con = sqlite3.connect(DB_YOLU)
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SEMA)

    sonuc = {
        "firmalar": ekle(con, "firmalar", csv_oku("firmalar.csv"),
                         ["id", "unvan", "tur", "vergi_no", "sektor", "calisan_sayisi"],
                         sayilari_cevir(["calisan_sayisi"], int)),
        "kullanicilar": ekle(con, "kullanicilar", csv_oku("kullanicilar.csv"),
                             ["eposta", "sifre_hash", "rol", "firma_id", "ad"], kullanici_hazirla),
        "yukumlulukler": ekle(con, "yukumlulukler", csv_oku("yukumlulukler.csv"),
                              ["id", "firma_id", "tur", "donem", "tutar_tl", "son_odeme_tarihi", "durum", "odeme_tarihi"],
                              sayilari_cevir(["tutar_tl"], float)),
        "faturalar": ekle(con, "faturalar", csv_oku("faturalar.csv"),
                          ["id", "firma_id", "tip", "karsi_taraf", "tarih", "tutar_tl", "kdv_orani"],
                          sayilari_cevir(["tutar_tl", "kdv_orani"], float)),
        "belgeler": ekle(con, "belgeler", csv_oku("belgeler.csv"),
                         ["id", "firma_id", "tur", "donem", "dosya_adi"]),
    }
    con.commit()
    return con, sonuc


def kontrol(con):
    """CLAUDE.md Adım 2 Kontrol: COUNT=60; Y018=54364.86; sifre_hash düz şifre değil."""
    print("\n--- KONTROL ---")
    tamam = True

    adet = con.execute("SELECT COUNT(*) FROM yukumlulukler").fetchone()[0]
    ok = adet == 60
    tamam &= ok
    print("OK   " if ok else "HATA ", f"yukumlulukler satır sayısı = {adet} (beklenen 60)")

    tutar, son, durum = con.execute(
        "SELECT tutar_tl, son_odeme_tarihi, durum FROM yukumlulukler WHERE id = ?", ("Y018",)).fetchone()
    ok = tutar == 54364.86 and son == "2026-11-30" and durum == "Bekliyor"
    tamam &= ok
    print("OK   " if ok else "HATA ", f"Y018 = {tutar} TL, son tarih {son}, {durum}")

    toplam = con.execute(
        "SELECT ROUND(SUM(tutar_tl), 2) FROM yukumlulukler "
        "WHERE firma_id = ? AND son_odeme_tarihi LIKE ? AND durum != 'Ödendi'", ("F001", "2026-11%")).fetchone()[0]
    ok = toplam == 165469.58
    tamam &= ok
    print("OK   " if ok else "HATA ", f"F001 Kasım ödenmemiş toplam = {toplam} (beklenen 165469.58)")

    duz_sifre = "Demo2026!"
    hashler = con.execute("SELECT eposta, sifre_hash FROM kullanicilar").fetchall()
    ok = all(h != duz_sifre and h.startswith("$2") and bcrypt.checkpw(duz_sifre.encode(), h.encode())
             for _, h in hashler)
    tamam &= ok
    print("OK   " if ok else "HATA ", f"{len(hashler)} kullanıcı: sifre_hash bcrypt, düz şifre DB'de yok "
          f"(örnek: {hashler[0][1][:20]}...)")

    kolonlar = [r[1] for r in con.execute("PRAGMA table_info(kullanicilar)")]
    ok = "sifre_duz" not in kolonlar
    tamam &= ok
    print("OK   " if ok else "HATA ", "kullanicilar tablosunda 'sifre_duz' kolonu yok")

    print("\nSONUÇ:", "Adım 2 Kontrol GEÇTİ ✅" if tamam else "Kontrol GEÇMEDİ ❌")
    return tamam


if __name__ == "__main__":
    con, sonuc = kur()
    print("Veritabanı:", DB_YOLU)
    for tablo, n in sonuc.items():
        print(f"  {tablo:<14} {n:>3} satır")
    basarili = kontrol(con)
    con.close()
    sys.exit(0 if basarili else 1)
