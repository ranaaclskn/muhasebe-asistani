"""İnsan onayı, tek kullanımlık onay token'ı, idempotent gönderim ve denetim kaydı (SQLite).

Atölye karşılığı: d7_store.py (approvals / tickets / audit tabloları, issue_approval, create_ticket).

Neden token? Dışarıya etkisi olan işlem (belge e-postası) YALNIZCA insan onayından sonra yapılmalı
(Kural 5). Onay anında güvenilir kod tek kullanımlık, tahmin edilemez bir token üretir; yazma işlemi
(talep_gonder) bu token olmadan çalışmaz. Model token'ı ÜRETMEZ ve GÖRMEZ.
Neden idempotency? Aynı talep iki kez gönderilmesin (butona iki kez basılsa, istek tekrar gelse bile).

Akış:  muhasebeci "Onayla" -> onay_ver(talep_id, muhasebeci_id) -> token
                          -> talep_gonder(talep_id, token)    -> gönderim kaydı (bir kez)
Kontrol (proje klasöründen):  python -m pytest -q tests/test_onay.py
"""
import json
import secrets
from datetime import datetime

from app.db import baglan

SEMA = """
CREATE TABLE IF NOT EXISTS onay_tokenlari (
    token TEXT PRIMARY KEY,
    talep_id INTEGER NOT NULL,
    veren_id INTEGER NOT NULL,          -- onayı veren muhasebeci
    kullanildi INTEGER NOT NULL DEFAULT 0,
    olusturma TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gonderimler (
    talep_id INTEGER PRIMARY KEY,       -- PRIMARY KEY: bir talep EN FAZLA BİR kez gönderilir
    firma_id TEXT NOT NULL,
    eposta TEXT,
    dosya TEXT,
    durum TEXT NOT NULL,                -- 'Kuyrukta' (n8n e-postası Adım 10'da)
    tarih TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS denetim (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    talep_id INTEGER,
    olay TEXT NOT NULL,                 -- onay_verildi | gonderim_reddedildi | gonderildi | tekrar_istek ...
    detay TEXT NOT NULL,
    tarih TEXT NOT NULL
);
"""


def _simdi():
    return datetime.now().isoformat(timespec="seconds")


def tablolari_kur():
    con = baglan()
    try:
        con.executescript(SEMA)
        con.commit()
    finally:
        con.close()


def denetim_yaz(talep_id, olay, detay=""):
    tablolari_kur()
    con = baglan()
    try:
        con.execute("INSERT INTO denetim (talep_id, olay, detay, tarih) VALUES (?, ?, ?, ?)",
                    (talep_id, olay, str(detay)[:1000], _simdi()))
        con.commit()
    finally:
        con.close()


def onay_ver(talep_id, veren_id):
    """İNSAN ONAYI: yalnızca muhasebeci, yalnızca 'Onay bekliyor' durumundaki talebi onaylayabilir.
    Talebi 'Onaylandı' yapar ve tek kullanımlık token döndürür. Bu fonksiyonu yalnızca güvenilir kod
    (muhasebeci paneli / LangGraph interrupt sonrası) çağırır; model asla çağırmaz."""
    tablolari_kur()
    con = baglan()
    try:
        con.execute("BEGIN IMMEDIATE")  # aynı anda iki onay isteği gelirse sırayla işlenir
        rol = con.execute("SELECT rol FROM kullanicilar WHERE id = ?", (veren_id,)).fetchone()
        if not rol or rol["rol"] != "muhasebeci":
            con.rollback()
            raise PermissionError("Talepleri yalnızca muhasebeci onaylayabilir")
        cur = con.execute("UPDATE talepler SET durum = 'Onaylandı', onaylayan_id = ? "
                          "WHERE id = ? AND durum = 'Onay bekliyor'", (veren_id, talep_id))
        if cur.rowcount != 1:
            con.rollback()
            raise ValueError(f"Talep {talep_id} onay bekleyen bir talep değil")
        token = secrets.token_urlsafe(32)  # tahmin edilemez, 256 bit
        con.execute("INSERT INTO onay_tokenlari (token, talep_id, veren_id, olusturma) VALUES (?, ?, ?, ?)",
                    (token, talep_id, veren_id, _simdi()))
        con.commit()
    finally:
        con.close()
    denetim_yaz(talep_id, "onay_verildi", f"veren_id={veren_id}")
    return token


def talep_gonder(talep_id, onay_token, firma_id=None):
    """YAZMA İŞLEMİ: geçerli + kullanılmamış + bu talebe ait token yoksa ÇALIŞMAZ.
    Aynı talep ikinci kez istenirse yeniden göndermez, önceki kaydı döndürür (idempotent).
    firma_id verilirse talep o firmaya ait değilse reddedilir (MCP sunucusu firma oturumunu verir).
    Döner: {"ok": bool, "tekrar": bool, "gonderim": {...}} ya da {"ok": False, "hata": "..."}"""
    tablolari_kur()
    con = baglan()
    try:
        con.execute("BEGIN IMMEDIATE")
        talep = con.execute("SELECT id, firma_id, emir, detay, durum FROM talepler WHERE id = ?",
                            (talep_id,)).fetchone()
        if not talep or (firma_id and talep["firma_id"] != firma_id):
            con.rollback()
            hata = "Talep bulunamadı"  # başka firmanın talebi için de aynı mesaj: varlığı sızdırılmaz
        else:
            onceki = con.execute("SELECT * FROM gonderimler WHERE talep_id = ?", (talep_id,)).fetchone()
            if onceki:  # idempotency: ikinci istek yeni gönderim yapmaz
                con.rollback()
                denetim_yaz(talep_id, "tekrar_istek", "zaten gönderilmiş")
                return {"ok": True, "tekrar": True, "gonderim": dict(onceki)}
            t = con.execute("SELECT kullanildi FROM onay_tokenlari WHERE token = ? AND talep_id = ?",
                            (onay_token, talep_id)).fetchone()
            if not t or t["kullanildi"] or talep["durum"] != "Onaylandı":
                con.rollback()
                hata = "Geçerli insan onayı bulunamadı"
            else:
                detay = json.loads(talep["detay"]) if talep["detay"] else {}
                con.execute("INSERT INTO gonderimler (talep_id, firma_id, eposta, dosya, durum, tarih) "
                            "VALUES (?, ?, ?, ?, 'Kuyrukta', ?)",
                            (talep_id, talep["firma_id"], detay.get("eposta"), detay.get("dosya"), _simdi()))
                con.execute("UPDATE onay_tokenlari SET kullanildi = 1 WHERE token = ?", (onay_token,))
                con.execute("UPDATE talepler SET durum = 'İşleme alındı' WHERE id = ?", (talep_id,))
                con.commit()
                gonderim = dict(con.execute("SELECT * FROM gonderimler WHERE talep_id = ?",
                                            (talep_id,)).fetchone())
                hata = None
    finally:
        con.close()
    if hata:
        denetim_yaz(talep_id, "gonderim_reddedildi", hata)
        return {"ok": False, "hata": hata}
    denetim_yaz(talep_id, "gonderildi", json.dumps({"dosya": gonderim["dosya"]}, ensure_ascii=False))
    return {"ok": True, "tekrar": False, "gonderim": gonderim}


def son_denetim(limit=20):
    tablolari_kur()
    con = baglan()
    try:
        return [dict(r) for r in con.execute("SELECT * FROM denetim ORDER BY id DESC LIMIT ?",
                                             (max(1, min(limit, 100)),))]
    finally:
        con.close()
