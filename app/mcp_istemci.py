"""MCP İstemcisi: app/mcp_sunucu.py'nin araçlarını keşfeder ve çağırır.

Atölye karşılığı: d7_05_mcp_client.py.
Fark: firma_id araçlara argüman olarak GÖNDERİLMEZ (Kural 2):
  - stdio modunda istemci sunucuyu MUHASEBE_FIRMA_ID ortam değişkeniyle kendisi başlatır;
  - HTTP modunda sunucu zaten bir firma oturumuyla başlatılmıştır; istemci firmayı değiştiremez.

Çalıştır (proje klasöründen):
  python -m app.mcp_istemci          # stdio: sunucuyu istemci başlatır (tek terminal)
  python -m app.mcp_istemci --http   # HTTP: önce başka terminalde sunucuyu başlatın:
                                     #   MUHASEBE_FIRMA_ID=F001 python -m app.mcp_sunucu --http
"""
import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

KOK = Path(__file__).resolve().parent.parent
MCP_URL = "http://127.0.0.1:8765/mcp"


def _stdio_parametreleri(firma_id):
    ortam = os.environ.copy()
    ortam["MUHASEBE_FIRMA_ID"] = firma_id  # oturumdaki firma; sunucu yalnızca buna hizmet eder
    return StdioServerParameters(command=sys.executable, args=["-m", "app.mcp_sunucu"],
                                 env=ortam, cwd=str(KOK))


@asynccontextmanager
async def _oturum(firma_id, http=False):
    """MCP oturumu aç. stdio: sunucuyu alt süreç olarak başlat. HTTP: çalışan sunucuya bağlan."""
    if http:
        async with streamablehttp_client(MCP_URL) as (okuyucu, yazici, _oturum_id):
            async with ClientSession(okuyucu, yazici) as oturum:
                await oturum.initialize()
                yield oturum
    else:
        async with stdio_client(_stdio_parametreleri(firma_id)) as (okuyucu, yazici):
            async with ClientSession(okuyucu, yazici) as oturum:
                await oturum.initialize()
                yield oturum


async def mcp_cagir(arac, argumanlar, firma_id, http=False):
    """Tek bir MCP aracını çağır, JSON sonucunu sözlük olarak döndür."""
    async with _oturum(firma_id, http) as oturum:
        sonuc = await oturum.call_tool(arac, argumanlar)
        if sonuc.isError:
            raise RuntimeError(f"MCP araç hatası: {sonuc.content}")
        metinler = [c.text for c in sonuc.content if getattr(c, "type", "") == "text"]
        if not metinler:
            raise RuntimeError("MCP sunucusundan metin sonucu gelmedi")
        return json.loads(metinler[0])


async def araclari_listele(firma_id, http=False):
    async with _oturum(firma_id, http) as oturum:
        sonuc = await oturum.list_tools()
        return [(a.name, (a.description or "").split("\n")[0]) for a in sonuc.tools]


def _goster(baslik, veri):
    print(f"\n=== {baslik}")
    print(json.dumps(veri, ensure_ascii=False, indent=2)[:900])


if __name__ == "__main__":
    http = "--http" in sys.argv
    if http:
        print(f"Bağlanılan sunucu: {MCP_URL} (firma oturumu sunucu başlatılırken belirlendi)")
    else:
        print("stdio modu: sunucu bu istemci tarafından alt süreç olarak başlatılıyor")
    try:
        araclar = asyncio.run(araclari_listele("F001", http))
    except Exception as e:
        if http:
            sys.exit(f"Sunucuya bağlanılamadı ({e.__class__.__name__}). Önce başka bir terminalde:\n"
                     "  MUHASEBE_FIRMA_ID=F001 python -m app.mcp_sunucu --http")
        raise
    print("SUNULAN ARAÇLAR:")
    for ad, aciklama in araclar:
        print(f"  - {ad}: {aciklama}")

    def cagir(arac, argumanlar, firma_id="F001"):
        return asyncio.run(mcp_cagir(arac, argumanlar, firma_id, http))

    _goster("kayit_sorgula: Ekim SGK primi",
            cagir("kayit_sorgula", {"sorgu": "durum", "parametreler": ["SGK primi", "2026-10"]}))
    if not http:  # stdio'da her çağrı kendi firma oturumuyla başlar: izolasyonu göster
        _goster("kayit_sorgula (F002 oturumu): AYNI sorgu, başka firma",
                cagir("kayit_sorgula", {"sorgu": "durum", "parametreler": ["SGK primi", "2026-10"]}, "F002"))
        _goster("GÜVENLİK: F002 oturumu F001'in talebini isterse",
                cagir("talep_durumu", {"talep_id": 1}, "F002"))
    _goster("GÜVENLİK: listede olmayan sorgu", cagir("kayit_sorgula", {"sorgu": "DROP TABLE firmalar"}))
    _goster("talep_durumu: talep 1", cagir("talep_durumu", {"talep_id": 1}))
    _goster("belge_ara: Eylül KDV beyannamesi",
            cagir("belge_ara", {"soru": "Eylül KDV beyannamesi ödenecek KDV", "k": 2}))
