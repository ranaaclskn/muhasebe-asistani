"""Veritabanı katmanı: hazır SQL sorguları (SORGULAR), calistir(), talep_ekle().

Kural 3 — Serbest SQL yok: Model SQL YAZMAZ. Yalnızca SORGULAR'dan bir sorgu ADI ve
parametre değerleri seçer. Ad listede yoksa reddedilir.
Kural 2 — firma_id her zaman KODDAN (oturumdan) gelir, modelden değil; her sorguda zorunlu.

Kontrol (proje klasöründen):  python -m app.db
"""
import re
import sqlite3
from datetime import datetime

from app.config import BUGUN, DB_YOLU

# Her sorgu: açıklama (niyet prompt'unda modele gösterilecek), modelin vereceği parametre
# adları ve SQL. :firma_id ve :bugun'u KOD ekler; model bunları hiçbir zaman vermez.
SORGULAR = {
    "durum": {
        "aciklama": "Belirli bir türün belirli bir dönemdeki tutarı, son tarihi, ödenip ödenmediği",
        "parametreler": ["tur", "donem"],
        "sql": """SELECT id, tur, donem, tutar_tl, son_odeme_tarihi, durum, odeme_tarihi
                  FROM yukumlulukler
                  WHERE firma_id = :firma_id AND tur = :tur AND donem = :donem""",
    },
    "ay_odemeleri": {
        "aciklama": "Bir ay içinde son tarihi olan ödenmemiş ödemeler (bu ay ne ödeyeceğim, toplam)",
        "parametreler": ["ay"],  # ör. "2026-11"
        "sql": """SELECT id, tur, donem, tutar_tl, son_odeme_tarihi, durum
                  FROM yukumlulukler
                  WHERE firma_id = :firma_id AND substr(son_odeme_tarihi, 1, 7) = :ay
                        AND durum != 'Ödendi'
                  ORDER BY son_odeme_tarihi""",
    },
    "gecikmis": {
        "aciklama": "Son tarihi geçmiş ve ödenmemiş (gecikmiş) ödemeler",
        "parametreler": [],
        "sql": """SELECT id, tur, donem, tutar_tl, son_odeme_tarihi, durum
                  FROM yukumlulukler
                  WHERE firma_id = :firma_id
                        AND (durum = 'Gecikti' OR (durum = 'Bekliyor' AND son_odeme_tarihi < :bugun))
                  ORDER BY son_odeme_tarihi""",
    },
    "en_yakin": {
        "aciklama": "Bugünden sonraki en yakın son ödeme tarihi olan ödenmemiş ödeme",
        "parametreler": [],
        "sql": """SELECT id, tur, donem, tutar_tl, son_odeme_tarihi, durum
                  FROM yukumlulukler
                  WHERE firma_id = :firma_id AND durum != 'Ödendi' AND son_odeme_tarihi >= :bugun
                  ORDER BY son_odeme_tarihi, id
                  LIMIT 1""",
    },
    "odeme_gecmisi": {
        "aciklama": "Bir türün geçmiş ödemeleri, ne zaman ve ne kadar ödendiği (son 6 kayıt)",
        "parametreler": ["tur"],
        "sql": """SELECT id, tur, donem, tutar_tl, son_odeme_tarihi, durum, odeme_tarihi
                  FROM yukumlulukler
                  WHERE firma_id = :firma_id AND tur = :tur AND durum = 'Ödendi'
                  ORDER BY son_odeme_tarihi DESC
                  LIMIT 6""",
    },
    "faturalar": {
        "aciklama": "Bir aydaki alış/satış faturaları",
        "parametreler": ["ay"],  # ör. "2026-10"
        "sql": """SELECT id, tip, karsi_taraf, tarih, tutar_tl, kdv_orani
                  FROM faturalar
                  WHERE firma_id = :firma_id AND substr(tarih, 1, 7) = :ay
                  ORDER BY tarih""",
    },
}

# DB'deki tür adları birebir bu dört değer (CLAUDE.md §8). Model/ kullanıcı farklı yazarsa eşle.
TURLER = ["KDV", "Muhtasar", "SGK primi", "Geçici vergi"]
_TUR_ESLEME = {
    "kdv": "KDV", "katma değer vergisi": "KDV",
    "muhtasar": "Muhtasar", "stopaj": "Muhtasar",
    "sgk": "SGK primi", "sgk primi": "SGK primi", "sigorta primi": "SGK primi", "prim": "SGK primi",
    "geçici vergi": "Geçici vergi", "gecici vergi": "Geçici vergi", "geçici": "Geçici vergi",
}


def tur_normalize(metin):
    """'sgk' / 'SGK Primi' / 'sigorta primi' -> 'SGK primi'. Tanınmazsa None."""
    if metin in TURLER:
        return metin
    anahtar = str(metin).replace("İ", "i").replace("I", "ı").lower().strip()
    return _TUR_ESLEME.get(anahtar)


def baglan():
    con = sqlite3.connect(DB_YOLU)
    con.row_factory = sqlite3.Row
    return con


def _firma_kontrol(firma_id):
    if not isinstance(firma_id, str) or not re.fullmatch(r"F\d{3}", firma_id):
        raise ValueError(f"Geçersiz firma_id: {firma_id!r}")


def calistir(sorgu_adi, firma_id, *parametreler):
    """SORGULAR'daki hazır sorguyu çalıştır; satırları sözlük listesi olarak döndür.

    calistir("ay_odemeleri", "F001", "2026-11")
    calistir("durum", "F001", "SGK primi", "2026-10")
    """
    if sorgu_adi not in SORGULAR:  # Kural 3: listede olmayan sorgu reddedilir
        raise ValueError(f"İzin verilmeyen sorgu: {sorgu_adi!r}")
    _firma_kontrol(firma_id)
    sorgu = SORGULAR[sorgu_adi]
    adlar = sorgu["parametreler"]
    if len(parametreler) != len(adlar):
        raise ValueError(f"{sorgu_adi} {len(adlar)} parametre bekler {adlar}, {len(parametreler)} geldi")

    degerler = dict(zip(adlar, parametreler))
    if "tur" in degerler:
        degerler["tur"] = tur_normalize(degerler["tur"]) or degerler["tur"]
    degerler["firma_id"] = firma_id  # modelden değil, koddan
    degerler["bugun"] = BUGUN

    con = baglan()
    try:
        con.execute("PRAGMA query_only = ON")  # sorgu yolu veritabanını değiştiremez
        return [dict(r) for r in con.execute(sorgu["sql"], degerler).fetchall()]
    finally:
        con.close()


def talep_ekle(firma_id, talep_metni):
    """İşlem taleplerini 'Onay bekliyor' olarak kaydet (Kural 5: dış etki yok). Yeni id döner."""
    _firma_kontrol(firma_id)
    con = baglan()
    try:
        cur = con.execute(
            "INSERT INTO talepler (firma_id, talep_metni, durum, olusturma_tarihi) "
            "VALUES (?, ?, 'Onay bekliyor', ?)",
            (firma_id, talep_metni, datetime.now().isoformat(timespec="seconds")))
        con.commit()
        return cur.lastrowid
    finally:
        con.close()


def _kontrol():
    """CLAUDE.md Adım 5 Kontrol."""
    tamam = True

    def yaz(ok, mesaj):
        nonlocal tamam
        tamam &= ok
        print("OK   " if ok else "HATA ", mesaj)

    print("--- KONTROL ---")
    satirlar = calistir("ay_odemeleri", "F001", "2026-11")
    toplam = round(sum(s["tutar_tl"] for s in satirlar), 2)  # toplamı Python hesaplar (Kural 1)
    yaz(len(satirlar) == 4 and toplam == 165469.58,
        f"ay_odemeleri F001 2026-11: {len(satirlar)} satır, toplam {toplam} ({[s['id'] for s in satirlar]})")

    f002 = calistir("ay_odemeleri", "F002", "2026-11")
    yaz(all(s["id"] not in {x["id"] for x in satirlar} for s in f002),
        f"F002 ile F001 verisi gelmez (F002: {[s['id'] for s in f002]})")

    s = calistir("durum", "F001", "sgk", "2026-10")
    yaz(len(s) == 1 and s[0]["id"] == "Y018" and s[0]["durum"] == "Bekliyor",
        f"durum F001 'sgk' 2026-10 -> {s[0]['id'] if s else None} {s[0]['tutar_tl'] if s else ''} (T01)")

    s = calistir("durum", "F002", "KDV", "2026-08")
    yaz(s and s[0]["id"] == "Y030" and s[0]["odeme_tarihi"] == "2026-09-26",
        f"durum F002 KDV 2026-08 -> ödeme tarihi {s[0]['odeme_tarihi'] if s else None} (T03)")

    s = calistir("gecikmis", "F003")
    yaz([x["id"] for x in s] == ["Y055"], f"gecikmis F003 -> {[x['id'] for x in s]} (T04)")

    s = calistir("en_yakin", "F002")
    yaz(s and s[0]["id"] == "Y040", f"en_yakin F002 -> {s[0]['id'] if s else None} {s[0]['son_odeme_tarihi'] if s else ''} (T05)")

    s = calistir("durum", "F002", "KDV", "2025-03")
    yaz(s == [], "durum F002 KDV 2025-03 -> 0 satır, yani çekimser kalınacak (T13)")

    for kotu, aciklama in [(("DROP TABLE firmalar", "F001"), "listede olmayan sorgu adı"),
                           (("durum", "F001' OR '1'='1", "KDV", "2026-10"), "sahte firma_id"),
                           (("durum", "F001", "KDV"), "eksik parametre")]:
        try:
            calistir(*kotu)
            yaz(False, f"{aciklama} REDDEDİLMEDİ")
        except ValueError as e:
            yaz(True, f"{aciklama} reddedildi: {e}")

    print("\nSONUÇ:", "Adım 5 Kontrol GEÇTİ ✅" if tamam else "Kontrol GEÇMEDİ ❌")


if __name__ == "__main__":
    _kontrol()
