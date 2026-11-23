"""n8n köprüsü (Adım 10): onaylanan taleplerin ve ödeme hatırlatmalarının e-postasını n8n'e gönderir.

Atölye karşılığı: n8n/campus_approve.json (insan onayından SONRA n8n webhook'u çağrılır).

Neden e-postayı Python değil n8n gönderiyor?
- E-posta dışarıya etkisi olan bir işlem; Python yalnızca NE gönderileceğini hazırlar.
- SMTP ayarı (sunucu, şifre) n8n'de durur; Python kodunda ya da .env'de e-posta şifresi tutulmaz.
- Akış n8n ekranında görülür, her gönderim n8n "Executions" listesinde kayıt olarak kalır.

Akış:
  muhasebeci "Onayla" -> onay.talep_gonder()  -> gonderimler: 'Kuyrukta'
                      -> kuyrugu_isle(talep_id) -> POST {N8N_URL}/webhook/talep-onay -> n8n e-postayı yollar
                      -> başarılı: 'Gönderildi' (talep 'Tamamlandı') + denetim kaydı
                      -> n8n kapalı/hata: 'Kuyrukta' kalır, panelden "Tekrar dene" ile sonra gönderilir
Hatırlatma: scripts/05_hatirlatma.py -> hatirlatma_gonder() -> POST {N8N_URL}/webhook/hatirlatma

Kontrol (proje klasöründen):  python -m pytest -q tests/test_bildirim.py
"""
from datetime import date, timedelta
from pathlib import Path

import requests

from app.config import BELGE_DIR, BUGUN, N8N_URL
from app.db import baglan, calistir, firma_bilgisi, kayitli_eposta
from app.kayit import donem_tr, tarih_tr, tl
from app.onay import denetim_yaz, tablolari_kur

ZAMAN_ASIMI = 20  # saniye: n8n + SMTP bu sürede cevap vermezse gönderim kuyrukta kalır


def n8n_calisiyor():
    """n8n açık mı? (/healthz kısa bir kontrol; panelde durum göstermek için)"""
    try:
        return requests.get(f"{N8N_URL}/healthz", timeout=2).ok
    except requests.RequestException:
        return False


def _n8n(yol, veri, ek=None):
    """n8n webhook'unu çağırır. Ek dosya varsa multipart (n8n onu e-posta ekine çevirir), yoksa JSON.
    Başarısızsa RuntimeError (çağıran 'Kuyrukta' bırakır)."""
    url = f"{N8N_URL}/webhook/{yol}"
    try:
        if ek:
            r = requests.post(url, data=veri, files={"ek": ek}, timeout=ZAMAN_ASIMI)
        else:
            r = requests.post(url, json=veri, timeout=ZAMAN_ASIMI)
    except requests.RequestException as e:
        raise RuntimeError(f"n8n'e ulaşılamadı ({N8N_URL})") from e
    if not r.ok:
        ipucu = " — akış yayında (aktif) değil olabilir" if r.status_code == 404 else ""
        raise RuntimeError(f"n8n hata verdi: HTTP {r.status_code}{ipucu}")
    return r


def _belge(dosya):
    """Belge dosyasını oku. Yalnızca dosya ADI kullanılır: '../' ile klasör dışına çıkılamaz.
    Not: n8n ekin türünü dosya uzantısından belirler (.txt -> text/plain) ve 'charset=utf-8' bilgisini
    e-postaya yazmaz; dosyanın baytları birebir aynı ulaşır (bkz. tests/test_bildirim.py)."""
    yol = BELGE_DIR / Path(dosya).name
    return (yol.name, yol.read_bytes(), "text/plain; charset=utf-8") if yol.is_file() else None


def _talep_epostasi(g, talep):
    """Bir gönderim kaydından e-posta içeriğini hazırla. Adres her zaman KAYITLI adrestir (Kural 5)."""
    unvan = firma_bilgisi(g["firma_id"]).get("unvan", g["firma_id"])
    eposta = g["eposta"] or kayitli_eposta(g["firma_id"])
    ozet = talep["ozet"] or talep["talep_metni"]
    ek = _belge(g["dosya"]) if g["dosya"] else None
    if g["dosya"] and not ek:
        raise RuntimeError(f"Belge dosyası bulunamadı: {g['dosya']}")
    if ek:
        konu = f"Talep #{g['talep_id']}: {ek[0]}"
        metin = (f"Merhaba,\n\nMuhasebecinizin onayıyla talep ettiğiniz belge ektedir.\n\n"
                 f"Talep: {ozet}\nTalep no: #{g['talep_id']}\nFirma: {unvan}\n\n"
                 "Bu e-posta Kişisel Muhasebe Asistanı tarafından otomatik gönderilmiştir.")
    else:  # görüşme talebi gibi eki olmayan talepler: onay bildirimi
        konu = f"Talep #{g['talep_id']} onaylandı"
        metin = (f"Merhaba,\n\nTalebiniz muhasebeciniz tarafından onaylandı.\n\n"
                 f"Talep: {ozet}\nTalep no: #{g['talep_id']}\nFirma: {unvan}\n\n"
                 "Muhasebeciniz en kısa sürede sizinle iletişime geçecek.\n\n"
                 "Bu e-posta Kişisel Muhasebe Asistanı tarafından otomatik gönderilmiştir.")
    veri = {"talep_id": str(g["talep_id"]), "firma": unvan, "eposta": eposta, "konu": konu, "metin": metin}
    return veri, ek


def kuyrukta_bekleyenler():
    """Henüz e-postası gitmemiş gönderimler (muhasebeci panelinde gösterilir)."""
    tablolari_kur()
    con = baglan()
    try:
        return [dict(r) for r in con.execute(
            "SELECT g.talep_id, g.firma_id, g.eposta, g.dosya, g.tarih, t.ozet, f.unvan FROM gonderimler g "
            "JOIN talepler t ON t.id = g.talep_id LEFT JOIN firmalar f ON f.id = g.firma_id "
            "WHERE g.durum = 'Kuyrukta' ORDER BY g.talep_id")]
    finally:
        con.close()


def _sahiplen(talep_id):
    """Kaydı 'Kuyrukta' -> 'Gönderiliyor' yap. Yalnızca BİR çağrı başarılı olur: aynı talep iki kez
    gönderilmez (butona iki kez basılsa, iki pencere aynı anda denese bile). Satırı döndürür ya da None."""
    con = baglan()
    try:
        cur = con.execute("UPDATE gonderimler SET durum = 'Gönderiliyor' WHERE talep_id = ? AND durum = 'Kuyrukta'",
                          (talep_id,))
        con.commit()
        if cur.rowcount != 1:
            return None, None
        g = dict(con.execute("SELECT * FROM gonderimler WHERE talep_id = ?", (talep_id,)).fetchone())
        t = dict(con.execute("SELECT id, ozet, talep_metni FROM talepler WHERE id = ?", (talep_id,)).fetchone())
        return g, t
    finally:
        con.close()


def _sonuclandir(talep_id, basarili):
    con = baglan()
    try:
        if basarili:
            con.execute("UPDATE gonderimler SET durum = 'Gönderildi' WHERE talep_id = ?", (talep_id,))
            con.execute("UPDATE talepler SET durum = 'Tamamlandı' WHERE id = ?", (talep_id,))
        else:  # tekrar denenebilsin
            con.execute("UPDATE gonderimler SET durum = 'Kuyrukta' WHERE talep_id = ?", (talep_id,))
        con.commit()
    finally:
        con.close()


def kuyrugu_isle(talep_id=None):
    """Kuyruktaki gönderimlerin e-postasını n8n ile yollar (talep_id verilirse yalnız o talep).
    Döner: [{"talep_id", "ok", "eposta"|"hata"}, ...]"""
    hedefler = [talep_id] if talep_id is not None else [k["talep_id"] for k in kuyrukta_bekleyenler()]
    sonuclar = []
    for tid in hedefler:
        g, talep = _sahiplen(tid)
        if not g:
            continue  # kuyrukta değil (zaten gönderildi ya da başka bir istek şu an gönderiyor)
        try:
            veri, ek = _talep_epostasi(g, talep)
            _n8n("talep-onay", veri, ek)
        except RuntimeError as e:
            _sonuclandir(tid, False)
            denetim_yaz(tid, "eposta_bekliyor", str(e))
            sonuclar.append({"talep_id": tid, "ok": False, "hata": str(e)})
            continue
        _sonuclandir(tid, True)
        denetim_yaz(tid, "eposta_gonderildi", f"n8n -> {veri['eposta']}" + (f" (ek: {ek[0]})" if ek else ""))
        sonuclar.append({"talep_id": tid, "ok": True, "eposta": veri["eposta"]})
    return sonuclar


# ---------- Ödeme hatırlatması ----------
def hatirlatilacaklar(firma_id, gun=3):
    """Ödenmemiş: son tarihi geçmiş olanlar + son tarihine `gun` gün ya da daha az kalanlar (tarih sırasıyla)."""
    bugun = date.fromisoformat(BUGUN)
    sinir = (bugun + timedelta(days=gun)).isoformat()
    aylar = {BUGUN[:7], sinir[:7]}
    satirlar = {s["id"]: s for s in calistir("gecikmis", firma_id)}
    for ay in aylar:
        satirlar.update({s["id"]: s for s in calistir("ay_odemeleri", firma_id, ay)
                         if s["durum"] != "Ödendi" and s["son_odeme_tarihi"] <= sinir})
    return sorted(satirlar.values(), key=lambda s: s["son_odeme_tarihi"])


def hatirlatma_metni(firma_id, odemeler):
    bugun = date.fromisoformat(BUGUN)
    satirlar = []
    for s in odemeler:
        gun = (date.fromisoformat(s["son_odeme_tarihi"]) - bugun).days
        durum = f"{-gun} gün gecikti" if gun < 0 else ("bugün son gün" if gun == 0 else f"{gun} gün kaldı")
        satirlar.append(f"- {s['tur']} ({donem_tr(s['donem'])}): {tl(s['tutar_tl'])}, son ödeme "
                        f"{tarih_tr(s['son_odeme_tarihi'])} — {durum}")
    unvan = firma_bilgisi(firma_id).get("unvan", firma_id)
    toplam = tl(round(sum(s["tutar_tl"] for s in odemeler), 2))
    return (f"Merhaba,\n\n{unvan} için yaklaşan ve geciken ödemeleriniz:\n\n" + "\n".join(satirlar)
            + f"\n\nToplam: {toplam}\n\nGeciken ödemelere gecikme zammı uygulanır; ayrıntı için asistana "
              "“gecikmiş ödemelerimin faizi ne kadar?” diye sorabilirsiniz.\n\n"
              "Bu e-posta Kişisel Muhasebe Asistanı tarafından otomatik gönderilmiştir.")


def hatirlatma_gonder(firma_id, gun=3):
    """Bir firmanın hatırlatma e-postası. Hatırlatılacak ödeme yoksa e-posta gönderilmez."""
    odemeler = hatirlatilacaklar(firma_id, gun)
    if not odemeler:
        return {"firma_id": firma_id, "ok": True, "gonderildi": False, "adet": 0}
    eposta = kayitli_eposta(firma_id)
    veri = {"firma_id": firma_id, "eposta": eposta, "adet": str(len(odemeler)),
            "konu": f"Ödeme hatırlatması: {len(odemeler)} ödeme ({tarih_tr(BUGUN)})",
            "metin": hatirlatma_metni(firma_id, odemeler)}
    try:
        _n8n("hatirlatma", veri)
    except RuntimeError as e:
        return {"firma_id": firma_id, "ok": False, "gonderildi": False, "adet": len(odemeler), "hata": str(e)}
    return {"firma_id": firma_id, "ok": True, "gonderildi": True, "adet": len(odemeler), "eposta": eposta}
