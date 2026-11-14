"""MCP Sunucusu: muhasebe asistanının araçlarını Model Context Protocol ile dışarı açar.

Atölye karşılığı: d7_04_mcp_server.py (FastMCP("KampusDestek")).

İKİ ÇALIŞMA ŞEKLİ (transport):
  1) stdio (varsayılan): İstemci (app/mcp_istemci.py) bu dosyayı KENDİSİ alt süreç olarak başlatır,
     stdin/stdout üzerinden konuşur. Terminalde tek başına çalıştırılınca sessizce bekler.
     UYARI: stdio modunda stdout'a print YAZMAYIN — MCP iletişimi stdout üzerinden yapılır, bozulur.
  2) HTTP (streamable-http): Sunucu AYRI bir terminalde bir port dinler, istemci ona bağlanır:
       Terminal 1:  MUHASEBE_FIRMA_ID=F001 python -m app.mcp_sunucu --http
       Terminal 2:  python -m app.mcp_istemci --http
     Adres: http://127.0.0.1:8765/mcp (yalnızca bu bilgisayar; 8000 FastAPI için boş bırakıldı)

GÜVENLİK (Kural 2): Araçların hiçbirinde firma_id PARAMETRESİ YOKTUR. Firma, sunucu başlatılırken
istemcinin verdiği MUHASEBE_FIRMA_ID ortam değişkeninden (oturumdan) okunur. Böylece aracı çağıran
(model ya da başka bir uygulama) başka bir firmanın verisini isteyemez.
Araçların hepsi SALT OKUNURDUR (Kural 5); yazma aracı onay token'ı ile ayrıca eklenecek.
"""
import json
import logging
import os
import re
import sys

from mcp.server.fastmcp import FastMCP

from app.db import SORGULAR, baglan, calistir

MCP_HOST, MCP_PORT = "127.0.0.1", 8765  # yalnızca yerel erişim; internete açılmaz

mcp = FastMCP("MuhasebeAsistani", log_level="WARNING",  # INFO satırları çıktıyı kalabalıklaştırmasın
              host=MCP_HOST, port=MCP_PORT,
              # HTTP modunda: her istek bağımsız + düz JSON cevap. Açık kalan bildirim (SSE) kanalı
              # olmadığı için istemci bağlantıyı kapatınca sunucu "ClosedResourceError" yazmaz.
              stateless_http=True, json_response=True)
logging.getLogger("httpx").setLevel(logging.WARNING)


def _firma():
    """Sunucunun hizmet verdiği firma: ortam değişkeninden (oturumdan), asla araç argümanından."""
    firma_id = os.environ.get("MUHASEBE_FIRMA_ID", "")
    if not re.fullmatch(r"F\d{3}", firma_id):
        raise ValueError("Sunucu bir firma oturumuyla başlatılmamış (MUHASEBE_FIRMA_ID yok/geçersiz)")
    return firma_id


def _json(veri):
    return json.dumps(veri, ensure_ascii=False)


@mcp.tool()
def sorgu_listesi() -> str:
    """Kullanılabilir hazır kayıt sorgularını ve parametrelerini listeler."""
    return _json({"ok": True, "sorgular": [
        {"ad": ad, "aciklama": s["aciklama"], "parametreler": s["parametreler"],
         "istege_bagli": s.get("istege_bagli", [])} for ad, s in SORGULAR.items()]})


@mcp.tool()
def kayit_sorgula(sorgu: str, parametreler: list[str] | None = None) -> str:
    """Firmanın ödeme/beyanname/fatura kayıtlarında HAZIR bir sorgu çalıştırır (serbest SQL yok).
    sorgu: sorgu_listesi'ndeki adlardan biri (ör. 'durum'); parametreler: ör. ['SGK primi', '2026-10']."""
    try:
        satirlar = calistir(sorgu, _firma(), *(parametreler or []))
        return _json({"ok": True, "sorgu": sorgu, "satirlar": satirlar})
    except Exception as e:  # listede olmayan sorgu, eksik parametre vb. -> hata olarak döner
        return _json({"ok": False, "error": str(e)})


@mcp.tool()
def belge_ara(soru: str, k: int = 3) -> str:
    """Firmanın beyannamelerinde ve ortak vergi rehberlerinde arama yapar, kaynaklarıyla döndürür."""
    try:
        from app.rag import getir  # ağır kütüphaneler yalnızca bu araç çağrılınca yüklenir
        parcalar = getir(soru, _firma(), top_n=max(1, min(k, 5)))
        return _json({"ok": True, "kaynaklar": [
            {"kaynak": d.metadata["kaynak"], "chunk_id": d.metadata["chunk_id"],
             "metin": d.page_content[:600]} for d, _b, _l in parcalar]})
    except Exception as e:
        return _json({"ok": False, "error": str(e)})


@mcp.tool()
def talep_durumu(talep_id: int) -> str:
    """Firmanın kendi talebinin durumunu sorgular (başka firmanın talebi görünmez)."""
    try:
        con = baglan()
        try:
            r = con.execute("SELECT id, emir, ozet, talep_metni, durum, olusturma_tarihi FROM talepler "
                            "WHERE id = ? AND firma_id = ?", (talep_id, _firma())).fetchone()
        finally:
            con.close()
        return _json({"ok": True, "talep": dict(r) if r else None})
    except Exception as e:
        return _json({"ok": False, "error": str(e)})


if __name__ == "__main__":
    if "--http" in sys.argv:
        firma = _firma()  # firma oturumu yoksa sunucu hiç başlamaz
        print(f"MCP sunucusu çalışıyor: http://{MCP_HOST}:{MCP_PORT}/mcp | firma oturumu: {firma}\n"
              "Araçlar: sorgu_listesi, kayit_sorgula, belge_ara, talep_durumu | Durdurmak için Ctrl + C",
              file=sys.stderr, flush=True)
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")  # stdout'a print yazma: MCP iletişimi bozulur.
