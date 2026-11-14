"""Atölye d7_03_tool_calling.py'nin bu projedeki karşılığı (DENEME / karşılaştırma aracı).

Hocanın yöntemi: modele Python fonksiyonları "araç" olarak verilir (bind_tools); model hangi
aracı hangi argümanlarla çağıracağını SEÇER (tool_calls), aracı KOD çalıştırır.
Bizim sistemimiz (app/niyet.py) aynı fikri JSON + sorgu menüsü ile yapar.

Bu script ikisini aynı sorularla karşılaştırır:
  python scripts/tool_calling_dene.py              # hazır 8 soru
  python scripts/tool_calling_dene.py "soru ..."   # tek soru

GÜVENLİK: firma_id araçların parametresi DEĞİLDİR. Oturumdan gelir (burada FIRMA_ID sabiti);
model onu göremez ve değiştiremez (Kural 2). Araçların hepsi SALT OKUNUR (Kural 5).
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402
from langchain_core.tools import tool  # noqa: E402
from langchain_ollama import ChatOllama  # noqa: E402

from app.config import BUGUN, LLM_MODEL, OLLAMA_URL  # noqa: E402
from app.db import calistir  # noqa: E402

FIRMA_ID = "F001"  # Demo Gıda — gerçek sistemde Streamlit oturumundan gelir


# ---------- Araçlar (hocanın kampus_belgesi_ara'sı gibi; hepsi salt okunur) ----------
@tool
def odeme_durumu(tur: str, donem: str) -> str:
    """Bir vergi/prim türünün bir dönemdeki tutarını, son ödeme tarihini ve ödenip ödenmediğini getirir.
    tur: 'KDV', 'Muhtasar', 'SGK primi' veya 'Geçici vergi'. donem: 'YYYY-AA' (ör. '2026-10')."""
    return json.dumps(calistir("durum", FIRMA_ID, tur, donem), ensure_ascii=False)


@tool
def ay_odemeleri(ay: str) -> str:
    """Bir ayda son tarihi olan ÖDENMEMİŞ ödemeleri ve tutarlarını getirir. ay: 'YYYY-AA' (bu ay = '2026-11')."""
    return json.dumps(calistir("ay_odemeleri", FIRMA_ID, ay), ensure_ascii=False)


@tool
def gecikmis_odemeler() -> str:
    """Son ödeme tarihi geçmiş, ödenmemiş (gecikmiş) ödemeleri getirir."""
    return json.dumps(calistir("gecikmis", FIRMA_ID), ensure_ascii=False)


@tool
def belge_ara(soru: str) -> str:
    """Beyanname içeriği, vergi takvimi, kurallar ve genel vergi/SGK bilgileri için belgelerde arama yapar."""
    from app.rag import getir  # ağır kütüphane yalnızca gerekirse yüklenir
    return "\n".join(f"[{d.metadata['kaynak']}] {d.page_content[:200]}" for d, _b, _l in getir(soru, FIRMA_ID))


ARACLAR = {a.name: a for a in (odeme_durumu, ay_odemeleri, gecikmis_odemeler, belge_ara)}

# Soru -> beklenen araç (karşılaştırma için; None = hiçbir araç çağrılmamalı)
TESTLER = [
    ("Ekim SGK primi ödendi mi?", "odeme_durumu"),
    ("Bu ay toplam ne kadar ödeyeceğim?", "ay_odemeleri"),
    ("Gecikmiş ödemem var mı?", "gecikmis_odemeler"),
    ("Eylül KDV beyannamemde ödenecek KDV ne kadardı?", "belge_ara"),
    ("Geçici vergi ne zaman ödenir?", "belge_ara"),
    ("SGK primini geç ödersem ne olur?", "belge_ara"),
    ("Haziran muhtasarı ne kadardı?", "odeme_durumu"),
    ("Hangi hisseyi almalıyım?", None),
]


def model(model_adi):
    llm = ChatOllama(model=model_adi, base_url=OLLAMA_URL, temperature=0, keep_alive="10m")
    return llm.bind_tools(list(ARACLAR.values()))


def dene(llm, soru, calistir_araci=True):
    mesajlar = [SystemMessage(content=f"Sen bir muhasebe asistanısın. Bugün {BUGUN}. Soruyu cevaplamak "
                                      "için uygun aracı çağır. Vergi/muhasebe dışı sorularda araç çağırma."),
                HumanMessage(content=soru)]
    bas = time.time()
    cevap = llm.invoke(mesajlar)
    sure = time.time() - bas
    cagrilar = cevap.tool_calls
    print(f"\nSORU: {soru}  ({sure:.1f}s)")
    if not cagrilar:
        print("  Model araç seçmedi.", f"Metin: {cevap.content[:120]!r}" if cevap.content else "")
    for c in cagrilar:
        print(f"  Araç çağrısı: {c['name']}({json.dumps(c['args'], ensure_ascii=False)})")
        if calistir_araci and c["name"] in ARACLAR:
            try:
                print("  Sonuç:", ARACLAR[c["name"]].invoke(c["args"])[:300])
            except Exception as e:  # model yanlış argüman verebilir (ör. '2026-10' yerine 'Ekim')
                print(f"  ARAÇ HATASI: {e}")
    return cagrilar[0]["name"] if cagrilar else None


if __name__ == "__main__":
    model_adi = os.getenv("AGENT_MODEL", LLM_MODEL)
    llm = model(model_adi)
    print(f"Model: {model_adi} | firma: {FIRMA_ID} (oturumdan; model göremez)")
    if len(sys.argv) > 1:
        dene(llm, " ".join(sys.argv[1:]))
        sys.exit()
    dogru = 0
    for soru, beklenen in TESTLER:
        secilen = dene(llm, soru, calistir_araci=False)
        ok = secilen == beklenen
        dogru += ok
        print(f"  {'OK' if ok else 'YANLIŞ'} (beklenen: {beklenen})")
    print(f"\nTool calling ile doğru araç seçimi: {dogru}/{len(TESTLER)}")
    print("Karşılaştırma: bizim JSON + menü + kod denetimi yöntemimiz (python -m app.niyet) 15/15.")
