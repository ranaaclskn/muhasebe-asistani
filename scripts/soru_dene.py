"""Ara deneme aracı (Adım 6 sonrası): soru sor, sistemin her parçasının ne yaptığını gör.

Henüz cevap CÜMLESİ üretilmiyor (Adım 7). Gösterilen:
  1) niyet (model + kod düzeltmesi)
  2) kayit  -> çalışan hazır SQL sorgusu ve dönen satırlar (+ Python toplamı)
     belge  -> Chroma'dan firma filtresiyle bulunan ilk 3 parça
     islem / kapsam_disi -> ne yapılacağı

Kullanım (proje klasöründen):  python scripts/soru_dene.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.db import calistir  # noqa: E402
from app.niyet import baska_firma_adi, niyet_belirle  # noqa: E402
from app.rag import ara, vektor_deposu  # noqa: E402

FIRMALAR = {"1": "F001", "2": "F002", "3": "F003"}


def main():
    print("Firma seç: 1) Demo Gıda  2) Demo Yazılım  3) Demo Tekstil")
    firma_id = FIRMALAR.get(input("Seçim [1]: ").strip() or "1", "F001")
    print(f"Oturum firması: {firma_id}  (firma_id koddan gelir, sorudan değil)")
    depo = vektor_deposu()

    while True:
        soru = input("\nSoru (çıkmak için q): ").strip()
        if soru.lower() == "q":
            break
        if not soru:
            continue

        bas = time.time()
        n = niyet_belirle(soru)
        print(f"\n[1] NİYET: {n['niyet']}"
              + (f" | sorgu={n['sorgu']} parametreler={n['parametreler']}" if n["sorgu"] else "")
              + f"  ({time.time() - bas:.1f}s)")
        if "duzeltme" in n:
            print(f"    kod düzeltmesi: {n['duzeltme']}")
        baska = baska_firma_adi(soru, firma_id)
        if baska:
            print(f"    ⚠ soruda başka firma adı var ({baska}) -> yalnızca kendi firmanızın verisi gösterilir")

        if n["niyet"] == "kayit":
            satirlar = calistir(n["sorgu"], firma_id, *n["parametreler"])
            print(f"[2] SQL: {n['sorgu']} -> {len(satirlar)} satır")
            for s in satirlar:
                print("    ", s)
            if not satirlar:
                print("    (kayıt yok -> asistan çekimser kalacak: 'Bu bilgi kayıtlarınızda yok')")
            elif n["sorgu"] in ("ay_odemeleri", "gecikmis") and len(satirlar) > 1:
                print(f"    Python toplamı: {round(sum(s['tutar_tl'] for s in satirlar), 2)}")
        elif n["niyet"] == "belge":
            print("[2] RAG araması (ilk 3 parça, mesafe küçük = daha yakın):")
            for i, (doc, mesafe) in enumerate(ara(soru, firma_id, k=3, depo=depo), 1):
                print(f"    {i}. {doc.metadata['chunk_id']} (mesafe={mesafe:.3f})")
                print("       " + doc.page_content[:200].replace("\n", " | "))
        elif n["niyet"] == "islem":
            print("[2] İŞLEM: talep 'Onay bekliyor' olarak kaydedilecek (Adım 8'de). Şimdilik kaydedilmedi.")
        else:
            print("[2] KAPSAM DIŞI: nazikçe reddedilecek.")


if __name__ == "__main__":
    main()
