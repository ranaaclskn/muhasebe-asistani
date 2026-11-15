"""HTTP API köprüsü (atölye 7-8. gün api_kopru.py karşılığı): LangGraph akışını FastAPI'den çağırır.
n8n (ya da başka bir uygulama) asistanla HTTP üzerinden konuşabilir.

Çalıştır (proje klasöründen):
  uvicorn app.api:app --host 127.0.0.1 --port 8000
Swagger (tarayıcıda dene):  http://127.0.0.1:8000/docs

Çok adımlı sohbet (interrupt) HTTP'de şöyle yürür:
  1) POST /sohbet {"mesaj": "Beyannamemi gönder", "firma_id": "F001"}
     -> {"durum": "CEVAP_BEKLENIYOR", "thread_id": "...", "soru": "Hangi beyanname?"}
  2) POST /sohbet {"cevap": "KDV", "thread_id": "..."}          (aynı thread_id ile devam)
     -> ... -> {"durum": "TAMAM", "cevap": "Talebiniz iletildi ..."}

GÜVENLİK (demo): Kimlik doğrulama YOK; firma_id istekten gelir. Yalnızca 127.0.0.1'de çalıştırın,
internete açmayın. Gerçek üründe firma_id oturumdan/token'dan gelmeli (Kural 2).
"""
import re
from datetime import date, timedelta

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.akis import devam, sor
from app.config import BUGUN
from app.db import calistir

app = FastAPI(title="Muhasebe Asistanı API", description="LangGraph + SQL + RAG; yalnızca yerel demo.")


class SohbetIstegi(BaseModel):
    mesaj: str = ""                # yeni soru
    cevap: str | None = None       # bekleyen soruya cevap (thread_id ile birlikte)
    thread_id: str | None = None
    firma_id: str = "F001"         # DEMO: gerçek üründe oturumdan gelmeli


def _firma(firma_id):
    if not re.fullmatch(r"F\d{3}", firma_id or ""):
        raise HTTPException(400, "Geçersiz firma_id (ör. F001)")
    return firma_id


@app.get("/saglik")
def saglik():
    return {"durum": "ok", "servis": "Muhasebe Asistanı (LangGraph)"}


@app.post("/sohbet")
def sohbet(istek: SohbetIstegi):
    """Yeni soru (mesaj) ya da bekleyen soruya cevap (cevap + thread_id)."""
    if istek.cevap is not None:
        if not istek.thread_id:
            raise HTTPException(400, "Cevap gönderirken thread_id gerekli")
        s = devam(istek.cevap, istek.thread_id)
    else:
        if not istek.mesaj.strip():
            raise HTTPException(400, "mesaj boş olamaz")
        s = sor(istek.mesaj, _firma(istek.firma_id))
    if s["bekleyen"]:
        return {"durum": "CEVAP_BEKLENIYOR", "thread_id": s["thread_id"],
                "soru": s["cevap"], "soru_turu": s["bekleyen"].get("tur")}
    return {"durum": "TAMAM", "thread_id": s["thread_id"], "cevap": s["cevap"],
            "yol": s["arac"], "kaynaklar": s["kaynaklar"]}


@app.get("/yaklasan-odemeler/{firma_id}")
def yaklasan_odemeler(firma_id: str, gun: int = 3):
    """Son tarihine `gun` gün ya da daha az kalan ÖDENMEMİŞ yükümlülükler (n8n hatırlatması için).
    Rakamlar SQL'den gelir; model kullanılmaz."""
    bugun = date.fromisoformat(BUGUN)
    sinir = (bugun + timedelta(days=max(0, min(gun, 60)))).isoformat()
    satirlar = [s for s in calistir("ay_odemeleri", _firma(firma_id), BUGUN[:7])
                + calistir("ay_odemeleri", firma_id, sinir[:7])
                if BUGUN <= s["son_odeme_tarihi"] <= sinir]
    tekil = {s["id"]: s for s in satirlar}.values()  # iki ay sorgusu çakışırsa tekrar etme
    return {"firma_id": firma_id, "bugun": BUGUN, "gun": gun,
            "odemeler": sorted(tekil, key=lambda s: s["son_odeme_tarihi"])}
