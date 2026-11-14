"""Streamlit arayüzü: giriş, firma paneli, muhasebeci paneli.

Çalıştır (proje klasöründen):  streamlit run ui/streamlit_app.py
"""
import sys
from pathlib import Path

# ui/ klasöründen çalıştırınca "app" paketini bulabilmek için proje kökünü ekle
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

from app.akis import sor  # noqa: E402
from app.config import BUGUN  # noqa: E402
from datetime import date  # noqa: E402

from app.db import (YONLER, bekleyen_talepler, firma_talepleri, kullanici_dogrula,  # noqa: E402
                    planli_islem_ekle, planli_islem_sil, planli_islemler, talep_karar, yukumlulukler)
from app.kayit import donem_tr, tarih_tr, tl  # noqa: E402
from app.onay import onay_ver, son_denetim, talep_gonder  # noqa: E402

st.set_page_config(page_title="Muhasebe Asistanı", page_icon="📊", layout="wide")


# ---------- 1) GİRİŞ ----------
def giris_ekrani():
    st.title("📊 Kişisel Muhasebe Asistanı")
    st.caption("Demo prototip — tüm firmalar ve rakamlar kurgusaldır.")
    with st.form("giris"):
        eposta = st.text_input("E-posta")
        sifre = st.text_input("Şifre", type="password")
        if st.form_submit_button("Giriş yap"):
            kullanici = kullanici_dogrula(eposta, sifre)
            if kullanici:
                st.session_state.kullanici = kullanici
                st.session_state.mesajlar = []
                st.rerun()
            else:
                st.error("E-posta veya şifre hatalı.")
    st.info("**Demo hesapları** (şifre hepsinde `Demo2026!`)  \n"
            "Firma: `gida@demo.local` · `yazilim@demo.local` · `tekstil@demo.local`  \n"
            "Muhasebeci: `muhasebe@demo.local`")


# ---------- 2a) KULLANICININ KENDİ EKLEDİĞİ PLANLI ÖDEME / TAHSİLATLAR ----------
def planli_bolumu(k, firma_id):
    """Form -> db.planli_islem_ekle (doğrulama orada) -> planli_islemler tablosu.
    Eklenen kayıtlar sohbetten sorulabilir: 'Aralıkta planladığım ödemeler', 'tahsilat bekliyor muyum'."""
    with st.expander("📅 Planlı ödeme ve tahsilatlarım"):
        mesaj = st.session_state.pop("planli_mesaj", None)
        if mesaj:
            getattr(st, mesaj[0])(mesaj[1])
        with st.form("planli_ekle", clear_on_submit=True):
            yon = st.radio("Tür", list(YONLER), format_func=YONLER.get, horizontal=True)
            c1, c2 = st.columns(2)
            tarih = c1.date_input("Tarih", value=date.fromisoformat(BUGUN), format="DD.MM.YYYY")
            tutar = c2.number_input("Tutar (TL)", min_value=0.0, step=100.0, format="%.2f")
            aciklama = st.text_input("Açıklama", placeholder="ör. Aralık kirası, X müşterisi faturası")
            karsi = st.text_input("Karşı taraf (isteğe bağlı)", placeholder="ör. Ev sahibi, ABC Ltd.")
            if st.form_submit_button("➕ Ekle"):
                try:
                    no = planli_islem_ekle(firma_id, k["id"], yon, tarih.isoformat(), tutar, aciklama, karsi)
                    st.session_state.planli_mesaj = ("success", f"Kayıt eklendi (#{no}). Artık sohbetten "
                                                     "sorabilirsiniz.")
                except ValueError as e:
                    st.session_state.planli_mesaj = ("error", f"Eklenemedi: {e}")
                st.rerun()

        kayitlar = planli_islemler(firma_id)
        if not kayitlar:
            st.caption("Henüz kayıt eklemediniz.")
            return
        st.dataframe([{"#": r["id"], "Tür": YONLER[r["yon"]], "Tarih": tarih_tr(r["tarih"]),
                       "Tutar": tl(r["tutar_tl"]), "Açıklama": r["aciklama"], "Karşı taraf": r["karsi_taraf"] or ""}
                      for r in kayitlar], hide_index=True, width="stretch")
        c1, c2 = st.columns([3, 1])
        sec = c1.selectbox("Silinecek kayıt", [r["id"] for r in kayitlar],
                           format_func=lambda i: next(f"#{r['id']} · {tarih_tr(r['tarih'])} · {r['aciklama']}"
                                                      for r in kayitlar if r["id"] == i))
        if c2.button("🗑️ Sil", width="stretch"):
            planli_islem_sil(sec, firma_id)  # yalnızca kendi firmasının kaydı silinir
            st.session_state.planli_mesaj = ("info", f"#{sec} silindi.")
            st.rerun()


# ---------- 2) FİRMA PANELİ ----------
def firma_paneli(k):
    firma_id = k["firma_id"]  # Kural 2: firma_id OTURUMDAN; kullanıcı değiştiremez
    st.title(f"🏢 {k['unvan']}")

    satirlar = yukumlulukler(firma_id)
    bu_ay = [s for s in satirlar if s["son_odeme_tarihi"][:7] == BUGUN[:7] and s["durum"] != "Ödendi"]
    geciken = [s for s in satirlar if s["durum"] == "Gecikti"]
    yaklasan = sorted((s for s in satirlar if s["durum"] != "Ödendi" and s["son_odeme_tarihi"] >= BUGUN),
                      key=lambda s: s["son_odeme_tarihi"])

    c1, c2, c3 = st.columns(3)
    c1.metric("Bu ay ödenecek", tl(sum(s["tutar_tl"] for s in bu_ay)), f"{len(bu_ay)} ödeme", delta_color="off")
    c2.metric("Geciken ödeme", len(geciken), tl(sum(s["tutar_tl"] for s in geciken)) if geciken else None,
              delta_color="inverse")
    if yaklasan:
        c3.metric("En yakın son tarih", tarih_tr(yaklasan[0]["son_odeme_tarihi"]),
                  f"{yaklasan[0]['tur']} · {tl(yaklasan[0]['tutar_tl'])}", delta_color="off")

    with st.expander("📋 Yükümlülükler"):
        st.dataframe([{"Tür": s["tur"], "Dönem": donem_tr(s["donem"]), "Tutar": tl(s["tutar_tl"]),
                       "Son ödeme": tarih_tr(s["son_odeme_tarihi"]), "Durum": s["durum"],
                       "Ödeme tarihi": tarih_tr(s["odeme_tarihi"])} for s in satirlar],
                     hide_index=True, width="stretch")

    planli_bolumu(k, firma_id)

    with st.expander("📨 Taleplerim"):
        talepler = firma_talepleri(firma_id)
        if talepler:
            st.dataframe(talepler, hide_index=True, width="stretch")
        else:
            st.caption("Henüz talebiniz yok.")

    st.subheader("💬 Asistana sorun")
    for m in st.session_state.mesajlar:  # önceki mesajları yeniden çiz
        with st.chat_message(m["rol"]):
            st.write(m["metin"])
            if m.get("kaynak"):
                st.caption(m["kaynak"])

    soru = st.chat_input("Ör. Ekim SGK primi ödendi mi?")
    if soru:
        st.session_state.mesajlar.append({"rol": "user", "metin": soru})
        with st.chat_message("user"):
            st.write(soru)
        with st.chat_message("assistant"):
            with st.spinner("Kayıtlarınıza bakıyorum..."):
                s = sor(soru, firma_id, k["id"])
            kaynak = f"Yol: {s['arac']} · Kaynak: {', '.join(s['kaynaklar']) or '—'}"
            st.write(s["cevap"])
            st.caption(kaynak)
        st.session_state.mesajlar.append({"rol": "assistant", "metin": s["cevap"], "kaynak": kaynak})
        st.session_state.bekleyen_kayit = s.get("bekleyen_kayit")  # varsa onay butonları çıkar

    b = st.session_state.get("bekleyen_kayit")
    if b:  # KULLANICI ONAYI: kayıt ancak burada, butona basınca yazılır
        c1, c2, _ = st.columns([1, 1, 4])
        if c1.button("✅ Kaydet"):
            try:
                no = planli_islem_ekle(firma_id, k["id"], b["yon"], b["tarih"], b["tutar_tl"], b["aciklama"])
                metin = f"✅ Kaydedildi (#{no}). “📅 Planlı ödeme ve tahsilatlarım” bölümünde görebilirsiniz."
            except ValueError as e:
                metin = f"Kaydedilemedi: {e}"
            st.session_state.mesajlar.append({"rol": "assistant", "metin": metin})
            st.session_state.bekleyen_kayit = None
            st.rerun()
        if c2.button("❌ Vazgeç"):
            st.session_state.mesajlar.append({"rol": "assistant", "metin": "Tamam, kaydetmedim."})
            st.session_state.bekleyen_kayit = None
            st.rerun()


# ---------- 3) MUHASEBECİ PANELİ ----------
def onayla(talep_id, muhasebeci_id):
    """İNSAN ONAYI -> tek kullanımlık token -> token'la gönderim (app/onay.py, atölye d7_store).
    Token yalnızca bu güvenilir kodda üretilir ve hemen kullanılır; ekranda/modelde görünmez."""
    try:
        token = onay_ver(talep_id, muhasebeci_id)
        sonuc = talep_gonder(talep_id, token)
    except (PermissionError, ValueError) as e:
        return ("error", f"#{talep_id} onaylanamadı: {e}")
    if not sonuc["ok"]:
        return ("error", f"#{talep_id} gönderime alınamadı: {sonuc['hata']}")
    g = sonuc["gonderim"]
    hedef = f" → {g['dosya']} · {g['eposta']}" if g.get("dosya") else ""
    return ("success", f"#{talep_id} onaylandı ve gönderime alındı{hedef}")


def muhasebeci_paneli(k):
    st.title("🧾 Onay kuyruğu")
    mesaj = st.session_state.pop("onay_mesaji", None)  # st.rerun sonrası sonucu göster
    if mesaj:
        getattr(st, mesaj[0])(mesaj[1])
    talepler = bekleyen_talepler()
    if not talepler:
        st.info("Onay bekleyen talep yok.")
    for t in talepler:
        with st.container(border=True):
            st.markdown(f"**#{t['id']} · {t['unvan']}** · {t['olusturma_tarihi']}")
            if t.get("ozet"):  # muhasebeci NE onayladığını açıkça görür
                st.markdown(f"📋 **{t['ozet']}**")
                st.caption(f"Firmanın yazdığı: “{t['talep_metni']}”")
            else:  # eski (emir bilgisi olmayan) talepler
                st.write(t["talep_metni"])
            c1, c2, _ = st.columns([1, 1, 4])
            if c1.button("✅ Onayla", key=f"onay_{t['id']}"):
                st.session_state.onay_mesaji = onayla(t["id"], k["id"])
                st.rerun()
            if c2.button("❌ Reddet", key=f"red_{t['id']}"):
                talep_karar(t["id"], "Reddedildi", k["id"])
                st.session_state.onay_mesaji = ("info", f"#{t['id']} reddedildi; hiçbir işlem yapılmadı.")
                st.rerun()

    with st.expander("🔎 Denetim kaydı (son 15 olay)"):
        kayitlar = son_denetim(15)
        if kayitlar:
            st.dataframe([{"Talep": d["talep_id"], "Olay": d["olay"], "Ayrıntı": d["detay"], "Zaman": d["tarih"]}
                          for d in kayitlar], hide_index=True, width="stretch")
        else:
            st.caption("Henüz kayıt yok.")


# ---------- ANA AKIŞ ----------
if "kullanici" not in st.session_state:
    giris_ekrani()
else:
    k = st.session_state.kullanici
    with st.sidebar:
        st.markdown(f"👤 **{k['ad']}**")
        st.caption(k["eposta"])
        if st.button("Çıkış yap"):
            st.session_state.clear()
            st.rerun()
    if k["rol"] == "muhasebeci":
        muhasebeci_paneli(k)
    else:
        firma_paneli(k)
