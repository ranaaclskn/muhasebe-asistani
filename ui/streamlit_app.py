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
from app.db import (bekleyen_talepler, firma_talepleri, kullanici_dogrula,  # noqa: E402
                    talep_karar, yukumlulukler)
from app.kayit import donem_tr, tarih_tr, tl  # noqa: E402

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


# ---------- 3) MUHASEBECİ PANELİ ----------
def muhasebeci_paneli(k):
    st.title("🧾 Onay kuyruğu")
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
                talep_karar(t["id"], "Onaylandı", k["id"])
                st.rerun()
            if c2.button("❌ Reddet", key=f"red_{t['id']}"):
                talep_karar(t["id"], "Reddedildi", k["id"])
                st.rerun()


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
