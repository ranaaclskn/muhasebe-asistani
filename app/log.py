"""Her soru-cevabı loglar tablosuna yazar (kim, ne sordu, hangi yol, hangi kaynak, ne kadar sürdü)."""
import json
from datetime import datetime

from app.db import baglan


def log_yaz(kullanici_id, firma_id, soru, niyet, arac, kaynaklar, cevap, sure_ms):
    con = baglan()
    try:
        con.execute(
            "INSERT INTO loglar (kullanici_id, firma_id, soru, niyet, arac, kaynaklar, cevap, sure_ms, tarih) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (kullanici_id, firma_id, soru, niyet, arac, json.dumps(kaynaklar, ensure_ascii=False),
             cevap, sure_ms, datetime.now().isoformat(timespec="seconds")))
        con.commit()
    finally:
        con.close()