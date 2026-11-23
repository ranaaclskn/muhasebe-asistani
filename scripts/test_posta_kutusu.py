"""Test posta kutusu: n8n'in gönderdiği e-postaları YAKALAYAN küçük, yerel bir SMTP sunucusu.

Neden? Demo hesapların adresleri (gida@demo.local ...) gerçek değil; gerçek e-posta sunucusu bu adreslere
posta teslim edemez. Bu betik 127.0.0.1:1025'te dinler, gelen her e-postayı data/posta_kutusu/ klasörüne
.eml dosyası olarak kaydeder ve terminale özetini yazar. Hiçbir e-posta dışarı gitmez.
n8n'deki "Test posta kutusu (yerel)" SMTP kimliği bu adrese bağlanır (n8n/test_posta_kimligi.json).
Gerçek gönderim istenirse n8n'de SMTP kimliği Gmail vb. ile değiştirilir; Python kodu değişmez.

Çalıştır (proje klasöründen, ayrı bir terminalde açık kalsın):  python scripts/test_posta_kutusu.py
Dosyayı aç (eki dahil):  .eml dosyaları Thunderbird/Evolution ile açılır ya da düz metin olarak okunur.
"""
import asyncio
import sys
from datetime import datetime
from email import message_from_bytes, policy
from pathlib import Path

KLASOR = Path(__file__).resolve().parent.parent / "data" / "posta_kutusu"
ADRES, PORT = "127.0.0.1", 1025  # yalnızca bu bilgisayar


def kaydet(veri: bytes):
    KLASOR.mkdir(parents=True, exist_ok=True)
    dosya = KLASOR / f"{datetime.now():%Y%m%d-%H%M%S-%f}.eml"
    dosya.write_bytes(veri)
    m = message_from_bytes(veri, policy=policy.default)
    ekler = [p.get_filename() for p in m.iter_attachments()]
    print(f"\n[{datetime.now():%H:%M:%S}] YENİ E-POSTA -> {dosya.name}")
    print(f"  Kime : {m['To']}\n  Konu : {m['Subject']}" + (f"\n  Ek   : {', '.join(ekler)}" if ekler else ""))
    govde = m.get_body(preferencelist=("plain", "html"))
    if govde:
        print("  " + govde.get_content().strip().replace("\n", "\n  ")[:600])
    sys.stdout.flush()


async def oturum(okuyucu: asyncio.StreamReader, yazici: asyncio.StreamWriter):
    """En basit SMTP konuşması: EHLO, MAIL FROM, RCPT TO, DATA ... '.', QUIT."""
    def yaz(satir):
        yazici.write((satir + "\r\n").encode())

    yaz("220 test-posta-kutusu hazir")
    try:
        while True:
            satir = await okuyucu.readline()
            if not satir:
                break
            komut = satir.decode(errors="replace").strip().upper()
            if komut.startswith(("EHLO", "HELO")):
                yaz("250-test-posta-kutusu")
                yaz("250-8BITMIME")
                yaz("250 SMTPUTF8")
            elif komut.startswith(("MAIL FROM", "RCPT TO", "RSET", "NOOP")):
                yaz("250 OK")
            elif komut == "DATA":
                yaz("354 Veriyi gonderin, sonu <CRLF>.<CRLF>")
                await yazici.drain()
                parcalar = []
                while True:
                    s = await okuyucu.readline()
                    if s in (b".\r\n", b".\n", b""):
                        break
                    parcalar.append(s[1:] if s.startswith(b"..") else s)  # nokta doldurmayı geri al
                kaydet(b"".join(parcalar))
                yaz("250 OK kaydedildi")
            elif komut == "QUIT":
                yaz("221 Gule gule")
                await yazici.drain()
                break
            else:
                yaz("502 Desteklenmiyor")
            await yazici.drain()
    finally:
        yazici.close()


async def ana():
    sunucu = await asyncio.start_server(oturum, ADRES, PORT)
    print(f"Test posta kutusu {ADRES}:{PORT} adresinde dinliyor. E-postalar: {KLASOR}")
    print("Durdurmak için Ctrl + C")
    async with sunucu:
        await sunucu.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(ana())
    except KeyboardInterrupt:
        print("\nTest posta kutusu kapatıldı.")
