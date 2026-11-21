"""Streamlit arayüzü: giriş, firma paneli, muhasebeci paneli.

Çalıştır (proje klasöründen):  streamlit run ui/streamlit_app.py
"""
import sys
from datetime import date
from pathlib import Path

# ui/ klasöründen çalıştırınca "app" paketini bulabilmek için proje kökünü ekle
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

from app.akis import devam, sor  # noqa: E402
from app.config import BUGUN  # noqa: E402
from app.db import (YONLER, bekleyen_talepler, firma_talepleri, kullanici_dogrula,  # noqa: E402
                    planli_islem_ekle, planli_islem_sil, planli_islemler, talep_karar, yukumlulukler)
from app.kayit import AYLAR, donem_tr, tarih_tr, tl  # noqa: E402
from app.onay import onay_ver, son_denetim, talep_gonder  # noqa: E402
from ui.grafik import PENCERELER, aylik_tablo, grafik, kisa_tl  # noqa: E402

st.set_page_config(page_title="Muhasebe Asistanı", page_icon="📊", layout="wide")

ONERILER = ["Bu ay toplam ne kadar vergi ve prim ödeyeceğim?", "Gecikmiş ödemem var mı?",
            "Ekim SGK primi ödendi mi?", "En yakın son ödeme tarihi hangisi?",
            "Son muhtasar beyannamemi e-postama gönder."]
DURUM_ROZET = {"Ödendi": "✅ Ödendi", "Bekliyor": "⏳ Bekliyor", "Gecikti": "⚠️ Gecikti"}

# ---------- GÖRÜNÜM (CSS) ----------
# Renkler tek yerde; st.container(key="x") öğesi sayfada "st-key-x" sınıfını alır, onu süslüyoruz.
st.markdown("""
<style>
:root { --ink:#0f172a; --muted:#64748b; --line:#e6e8f0; --mor:#6d28d9; --good:#0b8a0b; --bad:#c62f2f; }
.stApp { background:
    radial-gradient(1100px 480px at 0% -10%, #e9ecff 0%, transparent 60%),
    radial-gradient(900px 420px at 100% 0%, #f3e8ff 0%, transparent 55%), #f7f8fc; }
.block-container { padding-top: 1.6rem; max-width: 1380px; }
h1, h2, h3 { color: var(--ink); }

/* Üst şerit */
.hero { background: linear-gradient(120deg, #3730a3 0%, #6d28d9 55%, #a21caf 100%); color: #fff;
        border-radius: 22px; padding: 22px 28px; display: flex; justify-content: space-between;
        align-items: center; gap: 16px; flex-wrap: wrap; box-shadow: 0 14px 34px rgba(76, 29, 149, .25); }
.hero .baslik { font-size: 1.65rem; font-weight: 800; line-height: 1.2; }
.hero .alt { opacity: .85; font-size: .95rem; margin-top: 4px; }
.hero .tarih { background: rgba(255,255,255,.16); border: 1px solid rgba(255,255,255,.28);
               border-radius: 999px; padding: 6px 14px; font-size: .9rem; white-space: nowrap; }

/* Özet kartları */
.kpi { background: #fff; border: 1px solid var(--line); border-radius: 18px; padding: 14px 18px;
       box-shadow: 0 1px 3px rgba(15, 23, 42, .05); height: 100%; }
.kpi .etiket { color: var(--muted); font-size: .76rem; font-weight: 600; letter-spacing: .05em;
               text-transform: uppercase; }
.kpi .deger { color: var(--ink); font-size: 1.45rem; font-weight: 800; margin-top: 2px; }
.kpi .alt { color: var(--muted); font-size: .85rem; }
.kpi.iyi { border-color: #bfe5bf; background: linear-gradient(180deg, #f1fbf1, #fff); }
.kpi.iyi .deger { color: var(--good); }
.kpi.kotu { border-color: #f3c4c4; background: linear-gradient(180deg, #fff3f3, #fff); }
.kpi.kotu .deger { color: var(--bad); }

/* ASİSTAN kartı: sayfanın yıldızı */
.st-key-asistan_kart { border: 2px solid transparent; border-radius: 24px; padding: 18px 18px 14px;
    background: linear-gradient(#fff, #fff) padding-box,
                linear-gradient(135deg, #6366f1, #a855f7, #ec4899) border-box;
    box-shadow: 0 22px 48px rgba(99, 102, 241, .20); }
.asistan-bas { display: flex; align-items: center; gap: 14px; }
.asistan-bas .avatar { width: 52px; height: 52px; border-radius: 16px; display: grid; place-items: center;
    font-size: 28px; background: linear-gradient(135deg, #6366f1, #a855f7); box-shadow: 0 8px 18px rgba(124,58,237,.35); }
.asistan-bas .ad { font-size: 1.3rem; font-weight: 800; color: var(--ink); }
.asistan-bas .aciklama { color: var(--muted); font-size: .88rem; }
.canli { display: inline-flex; align-items: center; gap: 6px; font-size: .78rem; font-weight: 600;
         color: #15803d; background: #ecfdf3; border: 1px solid #bbf7d0; padding: 2px 10px; border-radius: 999px;
         margin-left: 6px; vertical-align: middle; }
.canli::before { content: ""; width: 8px; height: 8px; border-radius: 50%; background: #22c55e;
                 animation: nabiz 1.6s infinite; }
@keyframes nabiz { 0% { box-shadow: 0 0 0 0 rgba(34,197,94,.6); } 70% { box-shadow: 0 0 0 8px rgba(34,197,94,0); }
                   100% { box-shadow: 0 0 0 0 rgba(34,197,94,0); } }
.st-key-sohbet_kutu { background: #fafaff; border: 1px solid #ecebfb; border-radius: 18px; }
.st-key-sohbet_kutu [data-testid="stChatMessage"] { background: #fff; border: 1px solid #efeff7;
    border-radius: 16px; padding: 10px 14px; box-shadow: 0 1px 2px rgba(15,23,42,.04); }
.st-key-sohbet_kutu [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
    background: #eef2ff; border-color: #dfe4ff; }
.st-key-oneriler button { border-radius: 999px !important; background: #f5f3ff !important;
    border: 1px solid #ddd6fe !important; color: #5b21b6 !important; padding: 2px 14px !important;
    min-height: 0 !important; }
.st-key-oneriler button:hover { background: #ede9fe !important; border-color: #c4b5fd !important; }
.st-key-oneriler button p { font-size: .84rem !important; }
.st-key-asistan_kart [data-testid="stChatInput"] { border-radius: 16px; }

/* Grafik kartı */
.st-key-grafik_kart, .st-key-alt_kart { background: #fff; border: 1px solid var(--line); border-radius: 22px;
    padding: 18px 20px; box-shadow: 0 1px 3px rgba(15, 23, 42, .05); }
.durum { border-radius: 16px; padding: 12px 16px; display: flex; align-items: center; gap: 12px; }
.durum.iyi { background: #effaf0; border: 1px solid #c7ebc8; }
.durum.kotu { background: #fff1f1; border: 1px solid #f6caca; }
.durum .ikon { font-size: 28px; }
.durum .ust { font-weight: 800; font-size: 1.1rem; color: var(--ink); }
.durum .rakam { font-weight: 800; font-size: 1.1rem; }
.durum.iyi .rakam { color: var(--good); }
.durum.kotu .rakam { color: var(--bad); }
.durum .detay { color: var(--muted); font-size: .85rem; }
.kart-baslik { font-size: 1.15rem; font-weight: 800; color: var(--ink); }
.kart-alt { color: var(--muted); font-size: .85rem; }

/* Giriş */
.st-key-giris_kart { background: #fff; border: 1px solid var(--line); border-radius: 22px; padding: 22px 24px;
    box-shadow: 0 18px 40px rgba(15, 23, 42, .08); }
[data-testid="stSidebar"] { background: #ffffff; border-right: 1px solid var(--line); }
</style>
""", unsafe_allow_html=True)


def html(metin):
    st.markdown(metin, unsafe_allow_html=True)


def bugun_tr():
    g = date.fromisoformat(BUGUN)
    return f"{g.day} {AYLAR[g.month - 1]} {g.year}"


def kpi(kolon, etiket, deger, alt="", ton=""):
    kolon.markdown(f'<div class="kpi {ton}"><div class="etiket">{etiket}</div>'
                   f'<div class="deger">{deger}</div><div class="alt">{alt or "&nbsp;"}</div></div>',
                   unsafe_allow_html=True)


# ---------- 1) GİRİŞ ----------
def giris_ekrani():
    _, orta, _ = st.columns([1, 1.3, 1])
    with orta:
        st.write("")
        html('<div class="hero"><div><div class="baslik">🤖 Kişisel Muhasebe Asistanı</div>'
             '<div class="alt">Vergi, prim, maaş ve ödemelerinizi sorun; asistan kayıtlarınıza bakıp cevaplasın.</div>'
             '</div></div>')
        st.write("")
        with st.container(key="giris_kart"):
            with st.form("giris", border=False):
                eposta = st.text_input("E-posta", placeholder="ornek@demo.local")
                sifre = st.text_input("Şifre", type="password")
                if st.form_submit_button("Giriş yap", type="primary", width="stretch"):
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
        st.caption("Demo prototip — tüm firmalar ve rakamlar kurgusaldır.")


# ---------- 2a) KULLANICININ KENDİ EKLEDİĞİ PLANLI ÖDEME / TAHSİLATLAR ----------
def planli_bolumu(k, firma_id):
    """Form -> db.planli_islem_ekle (doğrulama orada) -> planli_islemler tablosu.
    Eklenen kayıtlar sohbetten sorulabilir ve gelir–gider grafiğine de yansır."""
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
        if st.form_submit_button("➕ Ekle", type="primary"):
            try:
                no = planli_islem_ekle(firma_id, k["id"], yon, tarih.isoformat(), tutar, aciklama, karsi)
                st.session_state.planli_mesaj = ("success", f"Kayıt eklendi (#{no}). Artık sohbetten "
                                                 "sorabilirsiniz; grafiğe de eklendi.")
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
    c1, c2 = st.columns([3, 1], vertical_alignment="bottom")
    sec = c1.selectbox("Silinecek kayıt", [r["id"] for r in kayitlar],
                       format_func=lambda i: next(f"#{r['id']} · {tarih_tr(r['tarih'])} · {r['aciklama']}"
                                                  for r in kayitlar if r["id"] == i))
    if c2.button("🗑️ Sil", width="stretch"):
        planli_islem_sil(sec, firma_id)  # yalnızca kendi firmasının kaydı silinir
        st.session_state.planli_mesaj = ("info", f"#{sec} silindi.")
        st.rerun()


# ---------- 2b) ASİSTAN (sohbet) ----------
def sohbet_temizle():
    st.session_state.mesajlar = []
    st.session_state.bekleyen = None
    st.session_state.thread_id = None


def asistan_bolumu(k, firma_id):
    with st.container(key="asistan_kart"):
        html('<div class="asistan-bas"><div class="avatar">🤖</div><div>'
             '<div class="ad">Muhasebe Asistanınız <span class="canli">Hazır</span></div>'
             '<div class="aciklama">Kayıtlarınıza bakarak cevaplar, kaynağını gösterir. E-posta gönderme '
             'gibi işlemleri muhasebeci onayına iletir.</div></div></div>')
        st.write("")

        kutu = st.container(height=420, border=False, key="sohbet_kutu", autoscroll=True)
        with kutu:
            if not st.session_state.mesajlar:
                with st.chat_message("assistant", avatar="🤖"):
                    st.markdown(f"Merhaba **{k['ad']}** 👋  \nÖdemeleriniz, vergi ve primleriniz, maaşlar ve "
                                "planladığınız tahsilatlar hakkında sorabilirsiniz. Aşağıdaki önerilerden birine "
                                "tıklayarak başlayın ya da kendi sorunuzu yazın.")
            for m in st.session_state.mesajlar:  # önceki mesajları yeniden çiz
                with st.chat_message(m["rol"], avatar="🤖" if m["rol"] == "assistant" else "🧑‍💼"):
                    st.write(m["metin"])
                    if m.get("kaynak"):
                        st.caption(m["kaynak"])

        # Asistan bir soru sorduysa (LangGraph interrupt) sonraki mesaj o soruya CEVAP olarak gider
        bekleyen = st.session_state.get("bekleyen")
        soru = None
        with st.container(horizontal=True, gap="small", key="oneriler"):
            if bekleyen and bekleyen.get("tur") == "onay":  # onay sorusunda butonlar da var
                if st.button("✅ Evet", key="evet"):
                    soru = "evet"
                if st.button("❌ Hayır", key="hayir"):
                    soru = "hayır"
            elif bekleyen:
                if st.button("↩️ Vazgeç", key="vazgec"):
                    soru = "vazgeç"
            else:
                for i, oneri in enumerate(ONERILER):
                    if st.button(oneri, key=f"oneri_{i}"):
                        soru = oneri
                if st.session_state.mesajlar:
                    st.button("🧹 Temizle", key="temizle", on_click=sohbet_temizle)

        ipucu = "Cevabınızı yazın (iptal için: vazgeç)" if bekleyen else "Asistana bir soru sorun…"
        yazilan = st.chat_input(ipucu, key="sohbet_girdi")
        soru = yazilan or soru

        if soru:
            st.session_state.mesajlar.append({"rol": "user", "metin": soru})
            with kutu:
                with st.chat_message("user", avatar="🧑‍💼"):
                    st.write(soru)
                with st.chat_message("assistant", avatar="🤖"):
                    with st.spinner("Kayıtlarınıza bakıyorum..."):
                        if bekleyen:  # KALDIĞI YERDEN devam (Command(resume=...))
                            s = devam(soru, st.session_state.thread_id)
                        else:         # yeni soru, yeni thread
                            s = sor(soru, firma_id, k["id"])
                    if s["bekleyen"]:
                        kaynak = "Yol: soru · Cevabınız bekleniyor"
                    else:
                        kaynak = f"Yol: {s['arac']} · Kaynak: {', '.join(s['kaynaklar']) or '—'}"
                    st.write(s["cevap"])
                    st.caption(kaynak)
            st.session_state.mesajlar.append({"rol": "assistant", "metin": s["cevap"], "kaynak": kaynak})
            st.session_state.bekleyen = s["bekleyen"]
            st.session_state.thread_id = s["thread_id"] if s["bekleyen"] else None
            st.rerun()  # butonlar / ipucu güncel duruma göre yeniden çizilsin


# ---------- 2c) GELİR–GİDER GRAFİĞİ ----------
def durum_html(df):
    gelir, gider = df["gelir"].sum(), df["gider"].sum()
    net = gelir - gider
    iyi = net >= 0
    return (f'<div class="durum {"iyi" if iyi else "kotu"}"><div class="ikon">{"✅" if iyi else "⚠️"}</div><div>'
            f'<div class="ust">{"Artıdasınız" if iyi else "Eksidesiniz"} · '
            f'<span class="rakam">{"+" if net > 0 else ""}{tl(net)}</span></div>'
            f'<div class="detay">Gelir {tl(gelir)} − Gider {tl(gider)}</div></div></div>')


def grafik_bolumu(df):
    with st.container(key="grafik_kart"):
        html('<div class="kart-baslik">📈 Gelir – Gider</div>'
             '<div class="kart-alt">Artıda mıyız, ekside mi? Ay ay görün.</div>')
        st.segmented_control("Dönem", list(PENCERELER), default="Son 3 ay", key="pencere", required=True,
                             label_visibility="collapsed", width="stretch")
        if df.empty:
            st.info("Bu dönem için gelir/gider kaydı yok.")
            return
        html(durum_html(df))
        st.altair_chart(grafik(df), width="stretch")
        st.caption("Mavi: gelir (satış faturaları + planlı tahsilatlar) · Kırmızı: gider (alış faturaları + net "
                   "maaşlar + vergi/prim + planlı ödemeler) · Koyu çizgi: net. Bu ay ve sonrası bekleyen ödemeleri "
                   "ve planlı kayıtları içerir; soluk çubuklar plandır.")
        with st.expander("Tablo olarak gör"):
            st.dataframe(df[["etiket", "Gelir ", "Gider ", "Net ", "Gelir kalemleri", "Gider kalemleri"]]
                         .rename(columns={"etiket": "Ay"}), hide_index=True, width="stretch")


# ---------- 2) FİRMA PANELİ ----------
def firma_paneli(k):
    firma_id = k["firma_id"]  # Kural 2: firma_id OTURUMDAN; kullanıcı değiştiremez
    html(f'<div class="hero"><div><div class="baslik">🏢 {k["unvan"]}</div>'
         '<div class="alt">Finansal durumunuz ve kişisel muhasebe asistanınız tek ekranda</div></div>'
         f'<div class="tarih">📅 {bugun_tr()}</div></div>')
    st.write("")

    satirlar = yukumlulukler(firma_id)
    bu_ay = [s for s in satirlar if s["son_odeme_tarihi"][:7] == BUGUN[:7] and s["durum"] != "Ödendi"]
    geciken = [s for s in satirlar if s["durum"] == "Gecikti"]
    yaklasan = sorted((s for s in satirlar if s["durum"] != "Ödendi" and s["son_odeme_tarihi"] >= BUGUN),
                      key=lambda s: s["son_odeme_tarihi"])
    pencere = st.session_state.get("pencere") or "Son 3 ay"
    df = aylik_tablo(firma_id, pencere)

    c1, c2, c3, c4 = st.columns(4)
    kpi(c1, "Bu ay ödenecek", tl(sum(s["tutar_tl"] for s in bu_ay)), f"{len(bu_ay)} ödeme")
    kpi(c2, "Geciken ödeme", len(geciken), tl(sum(s["tutar_tl"] for s in geciken)) if geciken else "Gecikme yok 👍",
        "kotu" if geciken else "")
    if yaklasan:
        kpi(c3, "En yakın son tarih", tarih_tr(yaklasan[0]["son_odeme_tarihi"]),
            f"{yaklasan[0]['tur']} · {tl(yaklasan[0]['tutar_tl'])}")
    else:
        kpi(c3, "En yakın son tarih", "—", "Bekleyen ödeme yok")
    if not df.empty:
        net = df["net"].sum()
        kpi(c4, f"Net durum · {pencere.lower()}", ("+" if net > 0 else "") + kisa_tl(net),
            "Artıdasınız ✅" if net >= 0 else "Eksidesiniz ⚠️", "iyi" if net >= 0 else "kotu")
    st.write("")

    sol, sag = st.columns([1.25, 1], gap="large")
    with sol:
        asistan_bolumu(k, firma_id)
    with sag:
        grafik_bolumu(df)

    st.write("")
    with st.container(key="alt_kart"):
        t1, t2, t3 = st.tabs(["📋 Yükümlülükler", "📅 Planlı ödeme ve tahsilatlarım", "📨 Taleplerim"])
        with t1:
            st.dataframe([{"Tür": s["tur"], "Dönem": donem_tr(s["donem"]), "Tutar": tl(s["tutar_tl"]),
                           "Son ödeme": tarih_tr(s["son_odeme_tarihi"]),
                           "Durum": DURUM_ROZET.get(s["durum"], s["durum"]),
                           "Ödeme tarihi": tarih_tr(s["odeme_tarihi"])} for s in satirlar],
                         hide_index=True, width="stretch")
        with t2:
            planli_bolumu(k, firma_id)
        with t3:
            talepler = firma_talepleri(firma_id)
            if talepler:
                st.dataframe(talepler, hide_index=True, width="stretch")
            else:
                st.caption("Henüz talebiniz yok.")


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
    talepler = bekleyen_talepler()
    html('<div class="hero"><div><div class="baslik">🧾 Onay kuyruğu</div>'
         '<div class="alt">Asistanın firmalardan topladığı işlem talepleri; siz onaylamadan hiçbiri yapılmaz</div>'
         f'</div><div class="tarih">⏳ {len(talepler)} talep bekliyor</div></div>')
    st.write("")
    mesaj = st.session_state.pop("onay_mesaji", None)  # st.rerun sonrası sonucu göster
    if mesaj:
        getattr(st, mesaj[0])(mesaj[1])
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
            if c1.button("✅ Onayla", key=f"onay_{t['id']}", type="primary"):
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
        st.markdown(f"### 👤 {k['ad']}")
        st.caption(k["eposta"])
        st.caption(f"Rol: {'Muhasebeci' if k['rol'] == 'muhasebeci' else 'Firma yetkilisi'}")
        if st.button("Çıkış yap", width="stretch"):
            st.session_state.clear()
            st.rerun()
    if k["rol"] == "muhasebeci":
        muhasebeci_paneli(k)
    else:
        firma_paneli(k)
