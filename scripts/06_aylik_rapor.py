"""Aylık yönetici raporu: her firma için seçilen ayın PDF raporunu data/raporlar/ klasörüne yazar.

Rakamlar app/rapor.py -> app/nakit + app/analiz fonksiyonlarından gelir (panelle aynı); model kullanılmaz.

Çalıştır (proje klasöründen):
  python scripts/06_aylik_rapor.py                     # geçen ay, tüm firmalar
  python scripts/06_aylik_rapor.py --ay 2026-09        # belirli bir ay
  python scripts/06_aylik_rapor.py --firma F001        # tek firma
Her ayın 1'inde otomatik çalışsın istenirse: n8n "Schedule Trigger" ya da cron ile bu betik çağrılabilir.
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import VERI_DIR  # noqa: E402
from app.db import firma_bilgisi, firmalar  # noqa: E402
from app.kayit import donem_tr  # noqa: E402
from app.rapor import dosya_adi, rapor_pdf, varsayilan_ay  # noqa: E402

CIKTI_DIR = VERI_DIR / "raporlar"


def main():
    p = argparse.ArgumentParser(description="Aylık yönetici raporu (PDF)")
    p.add_argument("--ay", default=varsayilan_ay(), help="YYYY-AA (varsayılan: geçen ay)")
    p.add_argument("--firma", help="Tek firma (ör. F001); verilmezse tüm firmalar")
    a = p.parse_args()
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", a.ay):
        p.error("--ay YYYY-AA biçiminde olmalı (ör. 2026-10)")
    CIKTI_DIR.mkdir(parents=True, exist_ok=True)
    for fid in [a.firma] if a.firma else firmalar():
        yol = CIKTI_DIR / dosya_adi(fid, a.ay)
        yol.write_bytes(rapor_pdf(fid, a.ay))
        print(f"{firma_bilgisi(fid).get('unvan', fid)} · {donem_tr(a.ay)} -> {yol.relative_to(VERI_DIR.parent)}")


if __name__ == "__main__":
    main()
