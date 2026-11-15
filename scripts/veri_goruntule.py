"""Veritabanına eklenen GERÇEK satırları gör (atölye 7. gün 05_veri_goruntule.py karşılığı).

Kullanım (proje klasöründen):
  python scripts/veri_goruntule.py              # her tablodan son 5 kayıt
  python scripts/veri_goruntule.py --limit 10
  python scripts/veri_goruntule.py --tablo talepler
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import DB_YOLU  # noqa: E402

TABLOLAR = {  # tablo -> gösterilecek kolonlar (uzun metinler kısaltılır)
    "talepler": "id, firma_id, emir, durum, ozet, olusturma_tarihi",
    "planli_islemler": "id, firma_id, yon, tarih, tutar_tl, aciklama",
    "loglar": "id, firma_id, soru, niyet, arac, kaynaklar, sure_ms, tarih",
    "onay_tokenlari": "talep_id, veren_id, kullanildi, olusturma",
    "gonderimler": "talep_id, firma_id, dosya, eposta, durum, tarih",
    "denetim": "id, talep_id, olay, detay, tarih",
}


def goster(con, tablo, kolonlar, limit):
    print("\n" + "=" * 72 + f"\n{tablo.upper()} — SON {limit} KAYIT")
    try:
        satirlar = con.execute(f"SELECT {kolonlar} FROM {tablo} ORDER BY rowid DESC LIMIT ?", (limit,)).fetchall()
    except sqlite3.OperationalError:
        print("(tablo henüz oluşmamış)")
        return
    if not satirlar:
        print("(henüz kayıt yok)")
    for r in reversed(satirlar):
        print({k: (str(v)[:70] + "…" if isinstance(v, str) and len(v) > 70 else v) for k, v in dict(r).items()})


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--tablo", choices=list(TABLOLAR))
    a = p.parse_args()
    con = sqlite3.connect(DB_YOLU)
    con.row_factory = sqlite3.Row
    print("VERİTABANI:", DB_YOLU)
    for t, k in TABLOLAR.items():
        if not a.tablo or a.tablo == t:
            goster(con, t, k, a.limit)
    con.close()
