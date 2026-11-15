"""Terminalden asistan (atölye 7. gün 04_konsol_agent.py karşılığı).

Aynı görüşmede çok adımlı soru-cevap: asistan eksik bilgiyi sorar (interrupt ⏸), sen cevaplarsın,
grafik KALDIĞI YERDEN devam eder (Command(resume=...)). Her düğümün çalışması ekranda görünür.

Kullanım (proje klasöründen):
  python scripts/konsol_asistan.py                     # firma F001 (Demo Gıda), model ile
  python scripts/konsol_asistan.py --firma F003        # başka firma
  python scripts/konsol_asistan.py --kurallar          # MODELSİZ (atölye AI_MODE=rules): hızlı, az bellek
  python scripts/konsol_asistan.py --thread abc123     # yarım kalan görüşmeye devam
  python scripts/konsol_asistan.py --sessiz            # düğüm izlerini gösterme
Çıkmak için: q
"""
import argparse
import json
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from langgraph.types import Command  # noqa: E402

import app.akis as akis  # noqa: E402
from app import niyet  # noqa: E402
from app.emirler import emir_cikar, emir_kalibi  # noqa: E402

FIRMALAR = {"F001": "Demo Gıda Ltd. Şti.", "F002": "Demo Yazılım A.Ş.", "F003": "Demo Tekstil (Şahıs)"}


def kural_niyeti(soru):
    """Modelsiz niyet (atölye AI_MODE=rules): emir kipi -> islem, değilse kod kuralları."""
    if emir_kalibi(soru):
        return {"niyet": "islem", "sorgu": None, "parametreler": [], **emir_cikar(soru), "kaynak": "kural"}
    return {**niyet.kural_duzelt(soru, {"niyet": "belge", "sorgu": None, "parametreler": []}), "kaynak": "kural"}


def kisalt(deger, n=220):
    metin = json.dumps(deger, ensure_ascii=False, default=str)
    return metin if len(metin) <= n else metin[:n] + "…"


def calistir(girdi, cfg, izle):
    """Grafiği adım adım çalıştır; her düğümün değiştirdiği alanları göster. Bekleyen soru varsa döndür."""
    bekleyen, son = None, {}
    for parca in akis.asistan.stream(girdi, cfg, stream_mode="updates"):
        for dugum, degisim in parca.items():
            if dugum == "__interrupt__":
                bekleyen = degisim[0].value
                if izle:
                    print(f"  [GRAPH] ⏸ DURDU (interrupt): {kisalt(bekleyen)}")
                continue
            if izle:
                print(f"  [GRAPH] ▶ {dugum:<14} {kisalt(degisim or {})}")
            son.update(degisim or {})
    return bekleyen, son


def main():
    p = argparse.ArgumentParser(description="Muhasebe asistanı — terminal")
    p.add_argument("--firma", default="F001", choices=list(FIRMALAR), help="Oturum firması (Kural 2: koddan gelir)")
    p.add_argument("--thread", default="", help="Yarım kalmış görüşmenin thread ID'si")
    p.add_argument("--kurallar", action="store_true", help="Modelsiz çalış (AI_MODE=rules)")
    p.add_argument("--sessiz", action="store_true", help="Düğüm izlerini gösterme")
    a = p.parse_args()
    izle = not a.sessiz
    if a.kurallar:
        akis.niyet_belirle = kural_niyeti

    print("\n=== MUHASEBE ASİSTANI — LANGGRAPH (terminal) ===")
    print(f"Firma: {a.firma} · {FIRMALAR[a.firma]} | Niyet: {'kurallar (modelsiz)' if a.kurallar else 'model + kurallar'}")
    print("Örnekler: 'Ekim SGK primi ödendi mi?' · 'Beyannamemi gönder' · 'Taleplerim ne oldu?' · çıkış: q\n")

    thread = a.thread
    if thread:  # yarım görüşme: checkpoint'ten kaldığı yeri bul
        durum = akis.asistan.get_state({"configurable": {"thread_id": thread}})
        if durum and durum.tasks and durum.tasks[0].interrupts:
            bekleyen = durum.tasks[0].interrupts[0].value
            print(f"Kayıtlı yarım görüşme bulundu (thread {thread}). Kaldığımız yer:")
        else:
            print(f"Thread {thread} için bekleyen bir soru yok; yeni soruyla başlayın.")
            thread, bekleyen = "", None
    else:
        bekleyen = None

    while True:
        if bekleyen:
            print(f"\nASİSTAN ❓ {bekleyen['soru'].replace('**', '')}")
            cevap = input("CEVAP  > ").strip()
            if cevap.lower() == "q":
                print(f"Görüşme kaydedildi. Devam etmek için: --thread {thread}")
                break
            girdi = Command(resume=cevap)
        else:
            soru = input("\nSORU   > ").strip()
            if soru.lower() == "q":
                break
            if not soru:
                continue
            thread = uuid.uuid4().hex[:10]
            girdi = {"soru": soru, "firma_id": a.firma, "kullanici_id": None, "baslangic": time.time()}
            if izle:
                print(f"  [THREAD] {thread}")
        cfg = {"configurable": {"thread_id": thread}, "recursion_limit": 60}
        bas = time.time()
        bekleyen, son = calistir(girdi, cfg, izle)
        if not bekleyen:
            print(f"\nASİSTAN ✅ {son.get('cevap', '(cevap yok)').replace('**', '')}")
            print(f"  (yol: {son.get('arac', '?')} · kaynak: {', '.join(son.get('kaynaklar', [])) or '—'} "
                  f"· {time.time() - bas:.1f} sn)")
    print("Görüşme bitti. Kayıtları görmek için: python scripts/veri_goruntule.py")


if __name__ == "__main__":
    main()
