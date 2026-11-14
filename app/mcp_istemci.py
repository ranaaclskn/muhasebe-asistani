"""MCP İstemcisi: app/mcp_sunucu.py'yi stdio üzerinden başlatır, araçları keşfeder ve çağırır.

Atölye karşılığı: d7_05_mcp_client.py.
Fark: sunucuyu başlatırken firma_id'yi ORTAM DEĞİŞKENİ olarak veririz (oturumdan gelir);
araçlara firma_id argümanı gönderilmez (Kural 2).

Çalıştır (proje klasöründen):  python -m app.mcp_istemci
"""
import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

KOK = Path(__file__).resolve().parent.parent


def _parametreler(firma_id):
    ortam = os.environ.copy()
    ortam["MUHASEBE_FIRMA_ID"] = firma_id  # oturumdaki firma; sunucu yalnızca buna hizmet eder
    return StdioServerParameters(command=sys.executable, args=["-m", "app.mcp_sunucu"],
                                 env=ortam, cwd=str(KOK))


async def mcp_cagir(arac, argumanlar, firma_id):
    """Tek bir MCP aracını çağır, JSON sonucunu sözlük olarak döndür."""
    async with stdio_client(_parametreler(firma_id)) as (okuyucu, yazici):
        async with ClientSession(okuyucu, yazici) as oturum:
            await oturum.initialize()
            sonuc = await oturum.call_tool(arac, argumanlar)
            if sonuc.isError:
                raise RuntimeError(f"MCP araç hatası: {sonuc.content}")
            metinler = [c.text for c in sonuc.content if getattr(c, "type", "") == "text"]
            if not metinler:
                raise RuntimeError("MCP sunucusundan metin sonucu gelmedi")
            return json.loads(metinler[0])


async def araclari_listele(firma_id):
    async with stdio_client(_parametreler(firma_id)) as (okuyucu, yazici):
        async with ClientSession(okuyucu, yazici) as oturum:
            await oturum.initialize()
            sonuc = await oturum.list_tools()
            return [(a.name, (a.description or "").split("\n")[0]) for a in sonuc.tools]


def _goster(baslik, veri):
    print(f"\n=== {baslik}")
    print(json.dumps(veri, ensure_ascii=False, indent=2)[:900])


if __name__ == "__main__":
    print("SUNULAN ARAÇLAR:")
    for ad, aciklama in asyncio.run(araclari_listele("F001")):
        print(f"  - {ad}: {aciklama}")

    _goster("kayit_sorgula (F001): Ekim SGK primi",
            asyncio.run(mcp_cagir("kayit_sorgula", {"sorgu": "durum", "parametreler": ["SGK primi", "2026-10"]}, "F001")))
    _goster("kayit_sorgula (F002): AYNI sorgu, başka firma oturumu",
            asyncio.run(mcp_cagir("kayit_sorgula", {"sorgu": "durum", "parametreler": ["SGK primi", "2026-10"]}, "F002")))
    _goster("GÜVENLİK: listede olmayan sorgu",
            asyncio.run(mcp_cagir("kayit_sorgula", {"sorgu": "DROP TABLE firmalar"}, "F001")))
    _goster("talep_durumu (F001): talep 1",
            asyncio.run(mcp_cagir("talep_durumu", {"talep_id": 1}, "F001")))
    _goster("GÜVENLİK: F002 oturumu F001'in talebini isterse",
            asyncio.run(mcp_cagir("talep_durumu", {"talep_id": 1}, "F002")))
    _goster("belge_ara (F001): Eylül KDV beyannamesi",
            asyncio.run(mcp_cagir("belge_ara", {"soru": "Eylül KDV beyannamesi ödenecek KDV", "k": 2}, "F001")))
