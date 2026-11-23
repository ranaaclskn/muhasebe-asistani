"""Adım 10: ödeme hatırlatması. Son tarihi geçmiş ya da son tarihine 3 gün veya daha az kalan ÖDENMEMİŞ
yükümlülükler için her firmaya bir hatırlatma e-postası (n8n /webhook/hatirlatma akışı gönderir).

Rakamlar SQL'den gelir, metni Python hazırlar; model kullanılmaz. Hatırlatılacak ödemesi olmayan
firmaya e-posta gitmez. E-posta her zaman firmanın KAYITLI adresine gider.

Çalıştır (proje klasöründen; n8n ve test posta kutusu açık olmalı):
  python scripts/05_hatirlatma.py            # 3 gün
  python scripts/05_hatirlatma.py --gun 7    # 7 gün
  python scripts/05_hatirlatma.py --dene     # e-posta göndermeden yalnızca metni göster
Her gün otomatik çalışsın istenirse: n8n'de "Schedule Trigger" ya da cron ile bu betik çağrılabilir.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.bildirim import hatirlatilacaklar, hatirlatma_gonder, hatirlatma_metni  # noqa: E402
from app.config import BUGUN  # noqa: E402
from app.db import baglan, kayitli_eposta  # noqa: E402


def firmalar():
    con = baglan()
    try:
        return [r["id"] for r in con.execute("SELECT id FROM firmalar ORDER BY id")]
    finally:
        con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Ödeme hatırlatma e-postaları (n8n)")
    ap.add_argument("--gun", type=int, default=3, help="son tarihe kaç gün kala hatırlatılsın (varsayılan 3)")
    ap.add_argument("--dene", action="store_true", help="e-posta gönderme, yalnızca metni yazdır")
    a = ap.parse_args()

    print(f"Bugün: {BUGUN} · son tarihine {a.gun} gün ya da daha az kalan + geciken ödemeler\n")
    hata = 0
    for f in firmalar():
        if a.dene:
            odemeler = hatirlatilacaklar(f, a.gun)
            print(f"===== {f} -> {kayitli_eposta(f)} ({len(odemeler)} ödeme)")
            print(hatirlatma_metni(f, odemeler) if odemeler else "Hatırlatılacak ödeme yok.", "\n")
            continue
        r = hatirlatma_gonder(f, a.gun)
        if not r["ok"]:
            hata += 1
            print(f"HATA  {f}: {r['hata']}")
        elif r["gonderildi"]:
            print(f"OK    {f}: {r['adet']} ödeme -> {r['eposta']}")
        else:
            print(f"—     {f}: hatırlatılacak ödeme yok, e-posta gönderilmedi")
    sys.exit(1 if hata else 0)
