"""Son ödeme tarihi hafta sonuna / resmî tatile düşen yükümlülükleri İZLEYEN İLK İŞ GÜNÜNE kaydırır.

Kural (VUK md. 18; SGK için de aynı uygulama): sürenin son günü resmî tatile rastlarsa süre, tatili
izleyen ilk iş günü mesai bitiminde sona erer. Demo CSV bu kuralı uygulamıyordu: 60 kaydın 15'i
cumartesi/pazara düşüyordu (ör. Ekim KDV'si 28.11.2026 cumartesi -> 30.11.2026 pazartesi).

Ne yapar (tekrar çalıştırmak zararsızdır):
  1) data/csv/yukumlulukler.csv  -> son_odeme_tarihi düzeltilir (DB sıfırdan kurulursa da doğru gelsin)
  2) data/muhasebe.db            -> yalnızca bu sütun UPDATE edilir; planlı kayıtlar, talepler vb. KORUNUR
     (01_veritabani_kur.py DB'yi silip baştan kurar, kullanıcı verisi gider; bu betik onu yapmaz)
  Durum (Bekliyor/Gecikti) sütununa dokunulmaz: "Gecikti" sorgu anında BUGÜN'e göre hesaplanır (app/db.py).
Sonra beyanname metinleri: python scripts/02_belge_uret.py   ve indeks: python scripts/03_indeksle.py

Çalıştır (proje klasöründen):  python scripts/07_tatil_kaydir.py
"""
import csv
import sqlite3
from datetime import date, timedelta
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
CSV_YOLU = KOK / "data" / "csv" / "yukumlulukler.csv"
DB_YOLU = KOK / "data" / "muhasebe.db"

# 2026 resmî tatilleri (tam gün). Arife yarım gündür, iş günü sayılır.
TATILLER = {
    "2026-01-01",                                        # Yılbaşı
    "2026-03-20", "2026-03-21", "2026-03-22",            # Ramazan Bayramı
    "2026-04-23", "2026-05-01", "2026-05-19",            # 23 Nisan, 1 Mayıs, 19 Mayıs
    "2026-05-27", "2026-05-28", "2026-05-29", "2026-05-30",  # Kurban Bayramı
    "2026-07-15", "2026-08-30", "2026-10-29",            # 15 Temmuz, 30 Ağustos, 29 Ekim
}


def is_gunu(iso):
    """'2026-11-28' (cumartesi) -> '2026-11-30' (pazartesi). İş günüyse aynen döner."""
    g = date.fromisoformat(iso)
    while g.weekday() >= 5 or g.isoformat() in TATILLER:
        g += timedelta(days=1)
    return g.isoformat()


def csv_duzelt():
    with open(CSV_YOLU, encoding="utf-8", newline="") as f:
        satirlar = list(csv.DictReader(f))
    alanlar = list(satirlar[0].keys())
    degisen = []
    for s in satirlar:
        yeni = is_gunu(s["son_odeme_tarihi"])
        if yeni != s["son_odeme_tarihi"]:
            degisen.append((s["id"], s["son_odeme_tarihi"], yeni))
            s["son_odeme_tarihi"] = yeni
    with open(CSV_YOLU, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=alanlar, lineterminator="\r\n")  # orijinal dosya CRLF
        w.writeheader()
        w.writerows(satirlar)
    return degisen


def db_duzelt():
    con = sqlite3.connect(DB_YOLU)
    degisen = []
    for yid, eski in con.execute("SELECT id, son_odeme_tarihi FROM yukumlulukler").fetchall():
        yeni = is_gunu(eski)
        if yeni != eski:
            con.execute("UPDATE yukumlulukler SET son_odeme_tarihi = ? WHERE id = ?", (yeni, yid))
            degisen.append((yid, eski, yeni))
    con.commit()
    con.close()
    return degisen


if __name__ == "__main__":
    c = csv_duzelt()
    d = db_duzelt()
    for yid, eski, yeni in c:
        print(f"{yid}: {eski} -> {yeni}")
    print(f"\nCSV: {len(c)} kayıt, veritabanı: {len(d)} kayıt düzeltildi.")
    kalan = [s for s in csv.DictReader(open(CSV_YOLU, encoding="utf-8")) if is_gunu(s["son_odeme_tarihi"])
             != s["son_odeme_tarihi"]]
    print("KONTROL:", "OK, tatile düşen son tarih kalmadı" if not kalan else f"HATA, {len(kalan)} kayıt kaldı")
