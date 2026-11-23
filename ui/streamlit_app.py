"""Streamlit arayüzü: giriş, firma paneli, muhasebeci paneli.

Çalıştır (proje klasöründen):  streamlit run ui/streamlit_app.py
"""
import sys
from datetime import date
from html import escape
from pathlib import Path

# ui/ klasöründen çalıştırınca "app" paketini bulabilmek için proje kökünü ekle
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from app.akis import devam, sor  # noqa: E402
from app.bildirim import kuyrugu_isle, kuyrukta_bekleyenler, n8n_calisiyor  # noqa: E402
from app.config import BUGUN  # noqa: E402
from app.db import (YONLER, bekleyen_talepler, firma_bilgisi, firma_talepleri, firmalar,  # noqa: E402
                    kullanici_dogrula, planli_islem_ekle, planli_islem_sil, planli_islemler, talep_karar,
                    yukumlulukler)
from app.kayit import AYLAR, donem_tr, tarih_tr, tl  # noqa: E402
from app.onay import onay_ver, son_denetim, talep_gonder  # noqa: E402
from app.nakit import DURUMLAR, KODLAR, donem_aylari, hareketler, nakit_akis_tablosu  # noqa: E402
from ui.grafik import PENCERELER, aylik_tablo, gider_dagilimi, grafik, kisa_tl  # noqa: E402
from ui.tablolar import ay_etiketi, excel_raporu, hareket_tablosu, nakit_html, portfoy_html  # noqa: E402

st.set_page_config(page_title="Muhasebe Asistanı", page_icon=":material/account_balance:", layout="wide",
                   initial_sidebar_state="expanded")

ONERILER = ["Bu ay toplam ne kadar vergi ve prim ödeyeceğim?", "Gecikmiş ödemem var mı?",
            "Ekim SGK primi ödendi mi?", "En yakın son ödeme tarihi hangisi?",
            "Son muhtasar beyannamemi e-postama gönder."]
ASISTAN_AVATAR, KULLANICI_AVATAR = ":material/support_agent:", ":material/person:"

# ---------- GÖRÜNÜM (CSS) ----------
# Sade kurumsal tema: lacivert ana renk, gri zemin, ince çerçeveli kartlar, degrade/emoji yok.
# st.container(key="x") öğesi sayfada "st-key-x" sınıfını alır; kartları bu sınıflarla biçimliyoruz.
st.markdown("""
<style>
:root { --brand:#12355b; --ink:#1f2937; --muted:#6b7280; --line:#e2e6ec; --bg:#f4f6f9;
        --good:#1a7f37; --bad:#b42318; --warn:#9a6700; }
.stApp { background: var(--bg); }
.block-container { padding-top: 1rem; padding-bottom: 2rem; max-width: 1420px; }
[data-testid="stHeader"] { background: transparent; }
.sayisal { font-variant-numeric: tabular-nums; }

/* Sayfa başlığı */
.ust-bar { background:#fff; border:1px solid var(--line); border-top:3px solid var(--brand); border-radius:8px;
           padding:10px 20px; margin-bottom:14px; display:flex; justify-content:space-between; align-items:center; gap:16px; flex-wrap:wrap; }
.ust-bar .ust-etiket { color:var(--muted); font-size:.72rem; font-weight:600; letter-spacing:.08em; text-transform:uppercase; }
.ust-bar .unvan { font-size:1.25rem; font-weight:700; color:var(--ink); line-height:1.25; }
.ust-bar .meta { color:var(--muted); font-size:.86rem; margin-top:2px; }
.ust-bar .sag { text-align:right; color:var(--muted); font-size:.85rem; line-height:1.5; }
.ust-bar .sag b { color:var(--ink); font-weight:600; }

/* Özet kartları */
.kpi { background:#fff; border:1px solid var(--line); border-radius:8px; padding:12px 16px; height:100%; }
.kpi .etiket { color:var(--muted); font-size:.72rem; font-weight:600; letter-spacing:.07em; text-transform:uppercase; }
.kpi .deger { color:var(--ink); font-size:1.45rem; font-weight:700; margin-top:4px; font-variant-numeric:tabular-nums; }
.kpi .alt { color:var(--muted); font-size:.83rem; margin-top:2px; }
.kpi.kotu { border-left:3px solid var(--bad); } .kpi.kotu .deger { color:var(--bad); }
.kpi.iyi { border-left:3px solid var(--good); } .kpi.iyi .deger { color:var(--good); }

/* Kartlar */
.st-key-asistan_kart, .st-key-grafik_kart, .st-key-yaklasan_kart, .st-key-alt_kart, .st-key-giris_kart {
    background:#fff; border:1px solid var(--line); border-radius:8px; padding:18px 20px; }
.st-key-asistan_kart { border-top:3px solid var(--brand); }
.kart-bas { display:flex; justify-content:space-between; align-items:flex-start; gap:12px;
            border-bottom:1px solid var(--line); padding-bottom:12px; }
.kart-bas .baslik { font-size:1.05rem; font-weight:700; color:var(--ink); }
.kart-bas .aciklama { color:var(--muted); font-size:.84rem; margin-top:2px; }
.rozet { font-size:.72rem; font-weight:600; padding:3px 9px; border-radius:4px; border:1px solid var(--line);
         color:var(--muted); white-space:nowrap; letter-spacing:.02em; }
.rozet.yesil { color:var(--good); border-color:#b9dfc3; background:#f1f8f3; }
.rozet.kirmizi { color:var(--bad); border-color:#f2c4c0; background:#fdf3f2; }
.bolum-etiket { color:var(--muted); font-size:.72rem; font-weight:600; letter-spacing:.07em; text-transform:uppercase;
                margin:4px 0 2px; }

/* Asistan */
.st-key-sohbet_kutu { background:#f8f9fb; border:1px solid var(--line); border-radius:6px; }
/* Asistan (giriş kutusu dahil) ilk ekrana sığsın: sohbet alanının yüksekliği ekran boyuna göre.
   Streamlit sabit yüksekliği kutunun üst katmanına (stLayoutWrapper) flex ile verir; onu eziyoruz. */
[data-testid="stLayoutWrapper"]:has(> .st-key-sohbet_kutu) {
    flex:0 0 max(260px, calc(100vh - 365px)) !important; height:max(260px, calc(100vh - 365px)) !important; }
/* Sekme değişince sayfa kaymasın: sekme içerikleri sabit yükseklikte, taşan kısım kendi içinde kayar */
.st-key-alt_kart [role="tabpanel"] { height:640px; overflow-y:auto; overflow-x:hidden; }
.st-key-grafik_kart [role="tabpanel"] { height:150px; overflow-y:auto; overflow-x:hidden; }
.st-key-sohbet_kutu [data-testid="stChatMessage"] { background:#fff; border:1px solid var(--line); border-radius:6px;
                                                    padding:10px 14px; }
.st-key-sohbet_kutu [data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]) {
    background:#eef3f9; border-color:#d5e0ee; }
.st-key-oneriler button { border-radius:4px !important; background:#fff !important; border:1px solid var(--line) !important;
                          color:var(--ink) !important; min-height:0 !important; padding:3px 12px !important; }
.st-key-oneriler button:hover { border-color:var(--brand) !important; color:var(--brand) !important; }
.st-key-oneriler button p { font-size:.83rem !important; }

/* Gelir–gider özeti ve dağılım */
.ozet3 { display:grid; grid-template-columns:repeat(3, 1fr); border:1px solid var(--line); border-radius:6px; margin:12px 0 6px; }
.ozet3 > div { padding:9px 10px; min-width:0; } .ozet3 > div + div { border-left:1px solid var(--line); }
.ozet3 .e { color:var(--muted); font-size:.68rem; font-weight:600; letter-spacing:.06em; text-transform:uppercase; }
.ozet3 .d { color:var(--ink); font-weight:700; font-size:.9rem; font-variant-numeric:tabular-nums; white-space:nowrap; }
.ozet3 .d.iyi { color:var(--good); } .ozet3 .d.kotu { color:var(--bad); }
.dagilim .satir { padding:6px 0; font-size:.84rem; color:var(--ink); }
.dagilim .ust { display:flex; justify-content:space-between; gap:10px; margin-bottom:4px; }
.dagilim .ust .t { font-variant-numeric:tabular-nums; font-weight:600; }
.dagilim .ust .o { color:var(--muted); font-weight:400; margin-left:8px; }
.dagilim .cubuk { height:6px; background:#eef1f5; border-radius:2px; overflow:hidden; }
.dagilim .cubuk span { display:block; height:100%; background:#e34948; border-radius:2px; }

/* Yaklaşan ödemeler */
.odeme { display:grid; grid-template-columns:1fr auto; gap:1px 12px; padding:9px 0; border-bottom:1px solid var(--line); }
.odeme:last-child { border-bottom:none; }
.odeme .tur { font-weight:600; color:var(--ink); font-size:.9rem; }
.odeme .tutar { font-weight:600; color:var(--ink); text-align:right; font-variant-numeric:tabular-nums; font-size:.9rem; }
.odeme .tarih { color:var(--muted); font-size:.8rem; }
.odeme .kalan { font-size:.78rem; text-align:right; color:var(--muted); }
.odeme .kalan.kotu { color:var(--bad); font-weight:600; } .odeme .kalan.uyari { color:var(--warn); font-weight:600; }

/* Yan menü (lacivert) */
[data-testid="stSidebar"] { background:var(--brand); }
[data-testid="stSidebar"] p, [data-testid="stSidebar"] span, [data-testid="stSidebar"] div,
[data-testid="stSidebar"] small { color:#dbe4ee; }
[data-testid="stSidebar"] button { background:transparent !important; border:1px solid rgba(255,255,255,.35) !important; }
[data-testid="stSidebar"] button:hover { background:rgba(255,255,255,.08) !important; }
.yan-logo { display:flex; align-items:center; gap:10px; padding-bottom:16px; border-bottom:1px solid rgba(255,255,255,.15); }
.yan-logo .kutu { width:34px; height:34px; border-radius:6px; background:#fff; color:var(--brand) !important;
                  display:grid; place-items:center; font-weight:800; font-size:.95rem; }
.yan-logo .ad { font-weight:700; color:#fff !important; font-size:1rem; line-height:1.15; }
.yan-logo .alt { font-size:.72rem; color:#9fb3c8 !important; }
.yan-bolum { font-size:.68rem; font-weight:600; text-transform:uppercase; letter-spacing:.09em; color:#9fb3c8 !important;
             margin:20px 0 6px; }
.yan-satir { display:flex; justify-content:space-between; gap:10px; font-size:.84rem; padding:3px 0; }
.yan-satir .s { color:#9fb3c8 !important; } .yan-satir .d { color:#fff !important; text-align:right; }

/* Giriş ekranı */
.giris-sol { background:var(--brand); color:#fff; border-radius:8px; padding:36px 32px; min-height:430px;
             display:flex; flex-direction:column; justify-content:space-between; }
.giris-sol .marka { font-size:.75rem; letter-spacing:.12em; text-transform:uppercase; color:#9fb3c8; font-weight:600; }
.giris-sol h2 { color:#fff; font-size:1.7rem; font-weight:700; margin:10px 0 8px; padding:0; line-height:1.25; }
.giris-sol p { color:#c9d6e3; font-size:.95rem; margin:0; }
.giris-sol ul { list-style:none; padding:0; margin:22px 0 0; }
.giris-sol li { margin:0; padding:8px 0; border-top:1px solid rgba(255,255,255,.12); color:#dbe4ee; font-size:.9rem; }
.giris-sol .not { font-size:.75rem; color:#9fb3c8; }
.alt-not { color:var(--muted); font-size:.76rem; text-align:center; margin-top:18px; }
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


def kart_basligi(baslik, aciklama="", rozet="", rozet_ton=""):
    sag = f'<span class="rozet {rozet_ton}">{rozet}</span>' if rozet else ""
    html(f'<div class="kart-bas"><div><div class="baslik">{baslik}</div>'
         f'<div class="aciklama">{aciklama}</div></div>{sag}</div>')


def csv_indir(df, dosya, etiket="CSV indir"):
    st.download_button(etiket, df.to_csv(index=False).encode("utf-8-sig"), file_name=dosya, mime="text/csv",
                       icon=":material/download:", type="tertiary")


# ---------- 1) GİRİŞ ----------
def giris_ekrani():
    _, orta, _ = st.columns([0.35, 2, 0.35])
    with orta:
        st.write("")
        st.write("")
        sol, sag = st.columns([1.1, 1], gap="medium")
        with sol:
            html('<div class="giris-sol"><div><div class="marka">Kişisel Muhasebe Asistanı</div>'
                 '<h2>Vergi, prim ve ödemeleriniz tek ekranda</h2>'
                 '<p>Kayıtlarınızı Türkçe sorun; asistan cevabı kaynağıyla birlikte versin.</p>'
                 '<ul><li>Ödeme takvimi ve gecikme uyarıları</li><li>Aylık gelir–gider ve net durum</li>'
                 '<li>Muhasebeci onaylı işlem talepleri</li><li>Tamamen yerel çalışan yapay zekâ</li></ul></div>'
                 '<div class="not">Demo prototip — tüm firmalar ve rakamlar kurgusaldır.</div></div>')
        with sag:
            with st.container(key="giris_kart"):
                html('<div class="kart-bas" style="border:none;padding-bottom:0"><div><div class="baslik">'
                     'Oturum aç</div><div class="aciklama">Firma veya muhasebeci hesabınızla giriş yapın.</div>'
                     '</div></div>')
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
                with st.expander("Demo hesapları"):
                    st.markdown("Şifre hepsinde `Demo2026!`  \n"
                                "Firma: `gida@demo.local`, `yazilim@demo.local`, `tekstil@demo.local`  \n"
                                "Muhasebeci: `muhasebe@demo.local`")


# ---------- 2a) KULLANICININ KENDİ EKLEDİĞİ PLANLI ÖDEME / TAHSİLATLAR ----------
def planli_bolumu(k, firma_id):
    """Form -> db.planli_islem_ekle (doğrulama orada) -> planli_islemler tablosu.
    Eklenen kayıtlar sohbetten sorulabilir ve gelir–gider grafiğine de yansır."""
    mesaj = st.session_state.pop("planli_mesaj", None)
    if mesaj:
        getattr(st, mesaj[0])(mesaj[1])
    sol, sag = st.columns([1, 1.6], gap="large")
    with sol:
        html('<div class="bolum-etiket">Yeni kayıt</div>')
        with st.form("planli_ekle", clear_on_submit=True, border=False):
            yon = st.radio("Tür", list(YONLER), format_func=YONLER.get, horizontal=True)
            c1, c2 = st.columns(2)
            tarih = c1.date_input("Tarih", value=date.fromisoformat(BUGUN), format="DD.MM.YYYY")
            tutar = c2.number_input("Tutar (TL)", min_value=0.0, step=100.0, format="%.2f")
            aciklama = st.text_input("Açıklama", placeholder="ör. Aralık kirası, X müşterisi faturası")
            karsi = st.text_input("Karşı taraf (isteğe bağlı)", placeholder="ör. Ev sahibi, ABC Ltd.")
            if st.form_submit_button("Kaydı ekle", type="primary", icon=":material/add:"):
                try:
                    no = planli_islem_ekle(firma_id, k["id"], yon, tarih.isoformat(), tutar, aciklama, karsi)
                    st.session_state.planli_mesaj = ("success", f"Kayıt eklendi (#{no}). Asistana sorabilir, "
                                                     "grafikte görebilirsiniz.")
                except ValueError as e:
                    st.session_state.planli_mesaj = ("error", f"Eklenemedi: {e}")
                st.rerun()
    with sag:
        html('<div class="bolum-etiket">Kayıtlarım</div>')
        kayitlar = planli_islemler(firma_id)
        if not kayitlar:
            st.caption("Henüz kayıt eklemediniz.")
            return
        df = pd.DataFrame([{"No": r["id"], "Tür": YONLER[r["yon"]], "Tarih": tarih_tr(r["tarih"]),
                            "Tutar": tl(r["tutar_tl"]), "Açıklama": r["aciklama"],
                            "Karşı taraf": r["karsi_taraf"] or ""} for r in kayitlar])
        st.dataframe(df, hide_index=True, width="stretch")
        c1, c2, c3 = st.columns([3, 1, 1], vertical_alignment="bottom")
        sec = c1.selectbox("Silinecek kayıt", [r["id"] for r in kayitlar],
                           format_func=lambda i: next(f"#{r['id']} · {tarih_tr(r['tarih'])} · {r['aciklama']}"
                                                      for r in kayitlar if r["id"] == i))
        if c2.button("Sil", icon=":material/delete:", width="stretch"):
            planli_islem_sil(sec, firma_id)  # yalnızca kendi firmasının kaydı silinir
            st.session_state.planli_mesaj = ("info", f"#{sec} silindi.")
            st.rerun()
        with c3:
            csv_indir(df, "planli_kayitlar.csv", "CSV")


# ---------- 2b) ASİSTAN (sohbet) ----------
def sohbet_temizle():
    st.session_state.mesajlar = []
    st.session_state.bekleyen = None
    st.session_state.thread_id = None


def asistan_bolumu(k, firma_id):
    with st.container(key="asistan_kart"):
        bekleyen = st.session_state.get("bekleyen")
        kart_basligi("Muhasebe Asistanı",
                     "Kayıtlarınıza bakarak cevaplar ve kaynağını gösterir. Dışarıya etkisi olan işlemler "
                     "muhasebeci onayına iletilir.",
                     "Cevabınız bekleniyor" if bekleyen else "Çevrimiçi", "" if bekleyen else "yesil")

        kutu = st.container(height=640, border=False, key="sohbet_kutu", autoscroll=True)
        with kutu:
            if not st.session_state.mesajlar:
                with st.chat_message("assistant", avatar=ASISTAN_AVATAR):
                    st.markdown(f"Merhaba, {k['ad']}. Ödemeleriniz, vergi ve primleriniz, maaşlar, faturalar ve "
                                "planladığınız tahsilatlar hakkında soru sorabilirsiniz. Aşağıdaki sık sorulan "
                                "sorulardan biriyle başlayabilir ya da kendi sorunuzu yazabilirsiniz.")
            for m in st.session_state.mesajlar:  # önceki mesajları yeniden çiz
                with st.chat_message(m["rol"], avatar=ASISTAN_AVATAR if m["rol"] == "assistant" else KULLANICI_AVATAR):
                    st.write(m["metin"])
                    if m.get("kaynak"):
                        st.caption(m["kaynak"])

            # Butonlar sohbet kutusunun İÇİNDE, son mesajın altında: kutunun altında yalnızca yazma alanı kalır,
            # böylece asistan (yazma alanı dahil) sayfa açılır açılmaz ekrana sığar.
            # Asistan bir soru sorduysa (LangGraph interrupt) sonraki mesaj o soruya CEVAP olarak gider.
            soru = None
            html(f'<div class="bolum-etiket">{"Hızlı cevap" if bekleyen else "Sık sorulanlar"}</div>')
            with st.container(horizontal=True, gap="small", key="oneriler"):
                if bekleyen and bekleyen.get("tur") == "onay":  # onay sorusunda butonlar da var
                    if st.button("Evet", key="evet", icon=":material/check:"):
                        soru = "evet"
                    if st.button("Hayır", key="hayir", icon=":material/close:"):
                        soru = "hayır"
                elif bekleyen:
                    if st.button("Vazgeç", key="vazgec", icon=":material/undo:"):
                        soru = "vazgeç"
                else:
                    for i, oneri in enumerate(ONERILER):
                        if st.button(oneri, key=f"oneri_{i}"):
                            soru = oneri
                    if st.session_state.mesajlar:
                        st.button("Sohbeti temizle", key="temizle", icon=":material/restart_alt:",
                                  on_click=sohbet_temizle)

        ipucu = "Cevabınızı yazın (iptal için: vazgeç)" if bekleyen else "Sorunuzu yazın…"
        yazilan = st.chat_input(ipucu, key="sohbet_girdi")
        soru = yazilan or soru

        if soru:
            st.session_state.mesajlar.append({"rol": "user", "metin": soru})
            with kutu:
                with st.chat_message("user", avatar=KULLANICI_AVATAR):
                    st.write(soru)
                with st.chat_message("assistant", avatar=ASISTAN_AVATAR):
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


# ---------- 2c) GELİR–GİDER ----------
def ozet_html(df):
    gelir, gider = df["gelir"].sum(), df["gider"].sum()
    net = gelir - gider
    ton = "iyi" if net >= 0 else "kotu"
    return (f'<div class="ozet3"><div><div class="e">Toplam gelir</div><div class="d">{tl(gelir)}</div></div>'
            f'<div><div class="e">Toplam gider</div><div class="d">{tl(gider)}</div></div>'
            f'<div><div class="e">Net ({"artı" if net >= 0 else "eksi"})</div>'
            f'<div class="d {ton}">{"+" if net > 0 else ""}{tl(net)}</div></div></div>')


def dagilim_html(satirlar):
    return '<div class="dagilim">' + "".join(
        f'<div class="satir"><div class="ust"><span>{escape(k)}</span><span class="t">{tl(t)}'
        f'<span class="o">%{o * 100:.0f}</span></span></div>'
        f'<div class="cubuk"><span style="width:{o * 100:.1f}%"></span></div></div>'
        for k, t, o in satirlar) + "</div>"


def grafik_bolumu(firma_id, df, pencere):
    with st.container(key="grafik_kart"):
        net = df["net"].sum() if not df.empty else 0
        kart_basligi("Gelir – Gider", "Aylık para girişi, çıkışı ve net durum",
                     ("Artıda" if net >= 0 else "Ekside") if not df.empty else "",
                     "yesil" if net >= 0 else "kirmizi")
        st.write("")
        st.segmented_control("Dönem", list(PENCERELER), default="Son 3 ay", key="pencere", required=True,
                             label_visibility="collapsed", width="stretch")
        if df.empty:
            st.info("Bu dönem için gelir/gider kaydı yok.")
            return
        html(ozet_html(df))
        st.altair_chart(grafik(df), width="stretch")
        st.caption("Gelir: satış faturaları ve planlı tahsilatlar. Gider: alış faturaları, net maaşlar, vergi/prim ve "
                   "planlı ödemeler. Açık renkli çubuklar ileri tarihli (planlanan) aylardır.")
        t1, t2 = st.tabs(["Gider dağılımı", "Tablo"])
        with t1:
            html(dagilim_html(gider_dagilimi(firma_id, set(df["ay"]))))
        with t2:
            tablo = df[["etiket", "Gelir ", "Gider ", "Net "]].rename(
                columns={"etiket": "Ay", "Gelir ": "Gelir", "Gider ": "Gider", "Net ": "Net"})
            st.dataframe(tablo, hide_index=True, width="stretch")
            csv_indir(tablo, f"gelir_gider_{pencere.lower().replace(' ', '_')}.csv")


# ---------- 2d) YAKLAŞAN ÖDEMELER ----------
def yaklasan_bolumu(firma_id, satirlar):
    """Ödenmemiş yükümlülükler + kullanıcının planlı ödemeleri, en yakın tarihten (gecikenler en üstte)."""
    bugun = date.fromisoformat(BUGUN)
    kalemler = [(s["son_odeme_tarihi"], s["tur"], donem_tr(s["donem"]), s["tutar_tl"])
                for s in satirlar if s["durum"] != "Ödendi"]
    kalemler += [(p["tarih"], p["aciklama"], "Planlı ödeme", p["tutar_tl"])
                 for p in planli_islemler(firma_id) if p["yon"] == "Gider" and p["tarih"] >= BUGUN]
    kalemler.sort()
    with st.container(key="yaklasan_kart"):
        kart_basligi("Yaklaşan ödemeler", "Ödenmemiş vergi/prim ve planlı ödemeleriniz",
                     f"{len(kalemler)} kalem" if kalemler else "")
        if not kalemler:
            st.caption("Bekleyen ödeme yok.")
            return
        parcalar = []
        for tarih, tur, aciklama, tutar in kalemler[:6]:
            gun = (date.fromisoformat(tarih) - bugun).days
            if gun < 0:
                kalan, ton = f"{-gun} gün gecikti", "kotu"
            elif gun == 0:
                kalan, ton = "Bugün", "uyari"
            else:
                kalan, ton = f"{gun} gün kaldı", "uyari" if gun <= 7 else ""
            parcalar.append(f'<div class="odeme"><div class="tur">{escape(tur)}</div>'
                            f'<div class="tutar">{tl(tutar)}</div>'
                            f'<div class="tarih">{escape(aciklama)} · Son tarih {tarih_tr(tarih)}</div>'
                            f'<div class="kalan {ton}">{kalan}</div></div>')
        html("".join(parcalar))
        if len(kalemler) > 6:
            st.caption(f"+{len(kalemler) - 6} kalem daha · tamamı Yükümlülükler sekmesinde")


# ---------- 2e) NAKİT AKIŞ TABLOSU ve HAREKET DÖKÜMÜ (hocanın Excel'i: N.AKIŞI ve HAREKET sayfaları) ----------
NAKIT_PENCERE = {"Son 3 ay": 3, "Son 6 ay": 6, "Tümü": None}


def nakit_bolumu(k, liste):
    c1, c2, c3 = st.columns([1.6, 1, 1], vertical_alignment="center")
    secim = c1.segmented_control("Nakit dönemi", list(NAKIT_PENCERE), default="Son 6 ay", key="nakit_pencere",
                                 required=True, label_visibility="collapsed")
    kirilim = c2.toggle("Müşteri / satıcı kırılımı", value=True, key="nakit_kirilim")
    aylar = donem_aylari(liste, NAKIT_PENCERE[secim or "Son 6 ay"])
    if not aylar:
        st.caption("Henüz hareket yok.")
        return
    satirlar = nakit_akis_tablosu(liste, aylar)
    with c3:
        st.download_button("Excel olarak indir", excel_raporu(k["unvan"], satirlar, aylar, liste),
                           file_name=f"nakit_akis_{k['firma_id']}_{BUGUN}.xlsx", icon=":material/table_view:",
                           mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                           width="stretch")
    html(nakit_html(satirlar, aylar, kirilim))
    st.caption(f"TL, kuruşlar yuvarlanmıştır · Ödemeler eksi (kırmızı) · {ay_etiketi(aylar[0])} – "
               f"{ay_etiketi(aylar[-1])} · “Plan” sütunları bekleyen ödemeler ve planlı kayıtlardır · Excel dosyasında "
               "kuruşlu tutarlar, hareket dökümü ve kod listesi de vardır.")


def hareket_bolumu(k, liste):
    aylar = sorted({h["ay"] for h in liste}, reverse=True)
    c1, c2, c3, c4 = st.columns([1, 1, 1.4, 1.4])
    ay = c1.selectbox("Ay", ["Tümü"] + aylar, format_func=lambda a: a if a == "Tümü" else ay_etiketi(a),
                      key="hareket_ay")
    yon = c2.selectbox("Yön", ["Tümü", "Giriş", "Çıkış"], key="hareket_yon")
    kodlar = c3.multiselect("Kalem", list(KODLAR), format_func=lambda x: f"{x} · {KODLAR[x][0]}",
                            placeholder="Tüm kalemler", key="hareket_kod")
    ara = c4.text_input("Ara", placeholder="Firma, işlem, açıklama…", key="hareket_ara").strip().lower()
    secili = [h for h in liste
              if (ay == "Tümü" or h["ay"] == ay) and (yon == "Tümü" or h["yon"] == yon)
              and (not kodlar or h["kod"] in kodlar)
              and (not ara or ara in f"{h['islem']} {h['karsi_taraf']} {h['kalem']}".lower())]
    giris = sum(h["tutar"] for h in secili if h["yon"] == "Giriş")
    cikis = sum(h["tutar"] for h in secili if h["yon"] == "Çıkış")
    html(f'<div class="ozet3" style="grid-template-columns:repeat(4,1fr)">'
         f'<div><div class="e">Kayıt</div><div class="d">{len(secili)}</div></div>'
         f'<div><div class="e">Giriş</div><div class="d">{tl(giris)}</div></div>'
         f'<div><div class="e">Çıkış</div><div class="d">{tl(cikis)}</div></div>'
         f'<div><div class="e">Net</div><div class="d {"iyi" if giris >= cikis else "kotu"}">'
         f'{"+" if giris > cikis else ""}{tl(giris - cikis)}</div></div></div>')
    if not secili:
        st.caption("Seçilen filtrelere uyan hareket yok.")
        return
    renk = {"Gecikti": "color:#b42318;font-weight:600", "Bekliyor": "color:#9a6700;font-weight:600",
            "Plan": "color:#52606d;font-style:italic", "Gerçekleşti": "color:#1a7f37"}
    df = pd.DataFrame(hareket_tablosu(secili))
    st.dataframe(df.style.map(lambda d: renk.get(d, ""), subset=["Durum"])
                 .map(lambda d: "color:#b42318" if d else "", subset=["Çıkış"]),
                 hide_index=True, width="stretch", height=430,
                 column_config={"Giriş": st.column_config.TextColumn(alignment="right", width="small"),
                                "Çıkış": st.column_config.TextColumn(alignment="right", width="small"),
                                "Tarih": st.column_config.TextColumn(width="small"),
                                "Vade": st.column_config.TextColumn(width="small"),
                                "Kod": st.column_config.NumberColumn(width="small", help=" · ".join(
                                    f"{k} {v[0]}" for k, v in KODLAR.items())),
                                "Durum": st.column_config.TextColumn(width="small")})
    st.caption("Durum: " + " · ".join(DURUMLAR) + " — “Plan”: ileri tarihli ya da sizin eklediğiniz planlı kayıt. "
               "Excel dosyasında (Nakit akış sekmesindeki düğme) bu döküm filtrelenebilir ve toplamlıdır.")


# ---------- 2) FİRMA PANELİ ----------
def firma_paneli(k):
    firma_id = k["firma_id"]  # Kural 2: firma_id OTURUMDAN; kullanıcı değiştiremez
    firma = firma_bilgisi(firma_id)
    meta = " · ".join(x for x in [firma.get("tur"), firma.get("sektor"),
                                  f"Vergi No {firma['vergi_no']}" if firma.get("vergi_no") else ""] if x)
    html(f'<div class="ust-bar"><div><div class="ust-etiket">Genel bakış</div>'
         f'<div class="unvan">{escape(k["unvan"])}</div><div class="meta">{escape(meta)}</div></div>'
         f'<div class="sag"><b>{bugun_tr()}</b><br>{escape(k["ad"])}</div></div>')

    satirlar = yukumlulukler(firma_id)
    bu_ay = [s for s in satirlar if s["son_odeme_tarihi"][:7] == BUGUN[:7] and s["durum"] != "Ödendi"]
    geciken = [s for s in satirlar if s["durum"] == "Gecikti"]
    yaklasan = sorted((s for s in satirlar if s["durum"] != "Ödendi" and s["son_odeme_tarihi"] >= BUGUN),
                      key=lambda s: s["son_odeme_tarihi"])
    pencere = st.session_state.get("pencere") or "Son 3 ay"
    df = aylik_tablo(firma_id, pencere)

    sol, sag = st.columns([1.2, 1], gap="medium")
    with sol:  # asistan sayfa açılır açılmaz görünür (yüksekliği ekrana göre CSS ile ayarlanır)
        asistan_bolumu(k, firma_id)
    with sag:
        c1, c2 = st.columns(2)
        kpi(c1, "Bu ay ödenecek", tl(sum(s["tutar_tl"] for s in bu_ay)), f"{len(bu_ay)} ödeme")
        kpi(c2, "Geciken ödeme", len(geciken),
            tl(sum(s["tutar_tl"] for s in geciken)) if geciken else "Gecikme yok", "kotu" if geciken else "")
        c3, c4 = st.columns(2)
        if yaklasan:
            kpi(c3, "En yakın son tarih", tarih_tr(yaklasan[0]["son_odeme_tarihi"]),
                f"{yaklasan[0]['tur']} · {tl(yaklasan[0]['tutar_tl'])}")
        else:
            kpi(c3, "En yakın son tarih", "—", "Bekleyen ödeme yok")
        if not df.empty:
            net = df["net"].sum()
            kpi(c4, f"Net durum · {pencere.lower()}", ("+" if net > 0 else "") + kisa_tl(net),
                "Gelir giderden fazla" if net >= 0 else "Gider gelirden fazla", "iyi" if net >= 0 else "kotu")
        grafik_bolumu(firma_id, df, pencere)
        yaklasan_bolumu(firma_id, satirlar)

    st.write("")
    with st.container(key="alt_kart"):
        liste = hareketler(firma_id)
        t0, th, t1, t2, t3 = st.tabs([":material/table_chart: Nakit akış tablosu", ":material/list_alt: Hareket dökümü",
                                      ":material/receipt_long: Yükümlülükler",
                                      ":material/event: Planlı ödeme ve tahsilatlar",
                                      ":material/outgoing_mail: Taleplerim"])
        with t0:
            nakit_bolumu(k, liste)
        with th:
            hareket_bolumu(k, liste)
        with t1:
            df_y = pd.DataFrame([{"Tür": s["tur"], "Dönem": donem_tr(s["donem"]), "Tutar": tl(s["tutar_tl"]),
                                  "Son ödeme": tarih_tr(s["son_odeme_tarihi"]), "Durum": s["durum"],
                                  "Ödeme tarihi": tarih_tr(s["odeme_tarihi"])} for s in satirlar])
            renk = {"Gecikti": "color:#b42318;font-weight:600", "Bekliyor": "color:#9a6700;font-weight:600",
                    "Ödendi": "color:#1a7f37"}
            st.dataframe(df_y.style.map(lambda d: renk.get(d, ""), subset=["Durum"]),
                         hide_index=True, width="stretch", height=400)
            csv_indir(df_y, "yukumlulukler.csv")
        with t2:
            planli_bolumu(k, firma_id)
        with t3:
            talepler = firma_talepleri(firma_id)
            if talepler:
                st.dataframe(pd.DataFrame(talepler).rename(columns={
                    "id": "No", "talep": "Talep", "durum": "Durum", "olusturma_tarihi": "Oluşturma"}),
                    hide_index=True, width="stretch")
            else:
                st.caption("Henüz talebiniz yok.")
    html('<div class="alt-not">Demo prototip · Tüm firmalar ve rakamlar kurgusaldır · '
         'Veriler bu bilgisayarda işlenir</div>')


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
    # Onaydan SONRA e-postayı n8n gönderir (app/bildirim.py). n8n kapalıysa gönderim kuyrukta kalır.
    sonuclar = kuyrugu_isle(talep_id)
    if not sonuclar:  # zaten gönderilmiş (tekrar istek)
        return ("info", f"#{talep_id} daha önce işlenmiş; yeni e-posta gönderilmedi.")
    r = sonuclar[0]
    if r["ok"]:
        return ("success", f"#{talep_id} onaylandı ve e-posta n8n ile gönderildi → {r['eposta']}")
    return ("warning", f"#{talep_id} onaylandı, ama e-posta henüz gönderilemedi: {r['hata']}. "
                       "Gönderim kaybolmadı; aşağıdaki “E-posta kuyruğu” bölümünden tekrar deneyebilirsiniz.")


def kuyruk_bolumu():
    """Onaylanmış ama e-postası henüz gitmemiş talepler (n8n kapalıyken onaylananlar)."""
    bekleyen = kuyrukta_bekleyenler()
    acik = n8n_calisiyor()
    with st.container(key="yaklasan_kart"):
        kart_basligi("E-posta kuyruğu", "Onaylanmış, e-postası n8n ile gönderilmeyi bekleyen talepler",
                     "n8n açık" if acik else "n8n kapalı", "yesil" if acik else "kirmizi")
        if not bekleyen:
            st.caption("Kuyrukta bekleyen e-posta yok.")
            return
        st.dataframe([{"Talep": f"#{b['talep_id']}", "Firma": b["unvan"], "Özet": b["ozet"],
                       "Alıcı": b["eposta"] or "kayıtlı adres", "Onay zamanı": b["tarih"]} for b in bekleyen],
                     hide_index=True, width="stretch")
        if not acik:
            st.caption("n8n kapalı. Başlatmak için proje klasöründe: bash n8n/baslat.sh")
        if st.button(f"Kuyruktaki {len(bekleyen)} e-postayı gönder", icon=":material/send:", type="primary",
                     disabled=not acik):
            sonuclar = kuyrugu_isle()
            basarili = sum(r["ok"] for r in sonuclar)
            hatalar = [f"#{r['talep_id']}: {r['hata']}" for r in sonuclar if not r["ok"]]
            st.session_state.onay_mesaji = (("success" if not hatalar else "warning"),
                                            f"{basarili} e-posta gönderildi." + (" Gönderilemeyen: " +
                                                                                  "; ".join(hatalar) if hatalar else ""))
            st.rerun()


def firma_portfoyu(talepler):
    """Muhasebecinin tüm müşteri firmaları tek tabloda (rakamlar SQL'den; firma panelindekilerle aynı fonksiyonlar)."""
    bugun = date.fromisoformat(BUGUN)
    satirlar = []
    for fid in firmalar():
        f = firma_bilgisi(fid)
        y = yukumlulukler(fid)
        bu_ay = [s for s in y if s["son_odeme_tarihi"][:7] == BUGUN[:7] and s["durum"] != "Ödendi"]
        geciken = [s for s in y if s["durum"] == "Gecikti"]
        yakin = sorted((s for s in y if s["durum"] != "Ödendi" and s["son_odeme_tarihi"] >= BUGUN),
                       key=lambda s: s["son_odeme_tarihi"])
        df = aylik_tablo(fid, "Son 3 ay")
        net = df["net"].sum() if not df.empty else 0
        gun = (date.fromisoformat(yakin[0]["son_odeme_tarihi"]) - bugun).days if yakin else None
        if geciken:
            durum, ton = f"{len(geciken)} gecikme", "kirmizi"
        elif gun is not None and gun <= 7:
            durum, ton = f"{gun} gün içinde ödeme", "sari"
        else:
            durum, ton = "Sorunsuz", "yesil"
        satirlar.append({
            "unvan": f.get("unvan", fid), "sektor": f.get("sektor"), "calisan": f.get("calisan_sayisi") or "–",
            "bu_ay": f"{tl(sum(s['tutar_tl'] for s in bu_ay))} <small>({len(bu_ay)})</small>",
            "geciken": (f'<span style="color:#b42318;font-weight:600">{tl(sum(s["tutar_tl"] for s in geciken))}'
                        f"</span> <small>({len(geciken)})</small>") if geciken else "–",
            "en_yakin": (f"{tarih_tr(yakin[0]['son_odeme_tarihi'])} · {yakin[0]['tur']}") if yakin else "–",
            "net": (f'<span style="color:{"#1a7f37" if net >= 0 else "#b42318"};font-weight:600">'
                    f'{"+" if net > 0 else ""}{kisa_tl(net)}</span>'),
            "talep": sum(1 for t in talepler if t["unvan"] == f.get("unvan")) or "–",
            "durum": durum, "ton": ton})
    with st.container(key="grafik_kart"):
        kart_basligi("Firma portföyü", "Tüm müşteri firmalarınızın ödeme durumu tek bakışta",
                     f"{len(satirlar)} firma")
        st.write("")
        html(portfoy_html(satirlar))
        st.caption("Net (son 3 ay): gelir − gider (satış/alış faturaları, net maaş, vergi/prim, planlı kayıtlar). "
                   "Durum: gecikmiş ödeme varsa kırmızı, 7 gün içinde son tarih varsa sarı.")


def muhasebeci_paneli(k):
    talepler = bekleyen_talepler()
    html('<div class="ust-bar"><div><div class="ust-etiket">Muhasebeci paneli</div>'
         '<div class="unvan">Onay kuyruğu</div>'
         '<div class="meta">Asistanın firmalardan topladığı işlem talepleri; onaylanmadan hiçbiri yapılmaz.</div></div>'
         f'<div class="sag"><b>{bugun_tr()}</b><br>{escape(k["ad"])}</div></div>')
    st.write("")
    kuyrukta = len(kuyrukta_bekleyenler())
    c1, c2, c3, _ = st.columns([1, 1, 1, 1])
    kpi(c1, "Bekleyen talep", len(talepler), "Onayınızı bekliyor", "kotu" if talepler else "")
    kpi(c2, "Firma", len({t["unvan"] for t in talepler}), "Talebi olan firma sayısı")
    kpi(c3, "E-posta kuyruğu", kuyrukta, "Gönderilmeyi bekliyor" if kuyrukta else "Bekleyen e-posta yok",
        "kotu" if kuyrukta else "")
    st.write("")

    mesaj = st.session_state.pop("onay_mesaji", None)  # st.rerun sonrası sonucu göster
    if mesaj:
        getattr(st, mesaj[0])(mesaj[1])
    firma_portfoyu(talepler)
    st.write("")
    with st.container(key="alt_kart"):
        kart_basligi("Bekleyen talepler", "Her talebi inceleyip onaylayın ya da reddedin",
                     f"{len(talepler)} talep")
        if not talepler:
            st.info("Onay bekleyen talep yok.")
        for t in talepler:
            with st.container(border=True):
                c1, c2 = st.columns([4, 1.3], vertical_alignment="center")
                with c1:
                    st.markdown(f"**#{t['id']} · {t['unvan']}**")
                    if t.get("ozet"):  # muhasebeci NE onayladığını açıkça görür
                        st.markdown(t["ozet"])
                        st.caption(f"Firmanın yazdığı: “{t['talep_metni']}” · {t['olusturma_tarihi']}")
                    else:  # eski (emir bilgisi olmayan) talepler
                        st.write(t["talep_metni"])
                        st.caption(t["olusturma_tarihi"])
                with c2:
                    if st.button("Onayla", key=f"onay_{t['id']}", type="primary", icon=":material/check:",
                                 width="stretch"):
                        st.session_state.onay_mesaji = onayla(t["id"], k["id"])
                        st.rerun()
                    if st.button("Reddet", key=f"red_{t['id']}", icon=":material/close:", width="stretch"):
                        talep_karar(t["id"], "Reddedildi", k["id"])
                        st.session_state.onay_mesaji = ("info", f"#{t['id']} reddedildi; hiçbir işlem yapılmadı.")
                        st.rerun()

    st.write("")
    kuyruk_bolumu()

    st.write("")
    with st.expander("Denetim kaydı (son 15 olay)", icon=":material/history:"):
        kayitlar = son_denetim(15)
        if kayitlar:
            st.dataframe([{"Talep": d["talep_id"], "Olay": d["olay"], "Ayrıntı": d["detay"], "Zaman": d["tarih"]}
                          for d in kayitlar], hide_index=True, width="stretch")
        else:
            st.caption("Henüz kayıt yok.")


# ---------- YAN MENÜ ----------
def yan_menu(k):
    with st.sidebar:
        html('<div class="yan-logo"><div class="kutu">MA</div><div><div class="ad">Muhasebe Asistanı</div>'
             '<div class="alt">Kişisel muhasebe paneli</div></div></div>')
        html('<div class="yan-bolum">Kullanıcı</div>'
             f'<div class="yan-satir"><span class="d" style="text-align:left">{escape(k["ad"])}</span></div>'
             f'<div class="yan-satir"><span class="s">{escape(k["eposta"])}</span></div>'
             f'<div class="yan-satir"><span class="s">Rol</span><span class="d">'
             f'{"Muhasebeci" if k["rol"] == "muhasebeci" else "Firma yetkilisi"}</span></div>')
        if k["rol"] != "muhasebeci":
            f = firma_bilgisi(k["firma_id"])
            satir = [("Unvan", f.get("unvan")), ("Tür", f.get("tur")), ("Sektör", f.get("sektor")),
                     ("Vergi No", f.get("vergi_no")), ("Çalışan", f.get("calisan_sayisi"))]
            html('<div class="yan-bolum">Firma</div>' + "".join(
                f'<div class="yan-satir"><span class="s">{a}</span><span class="d">{escape(str(d))}</span></div>'
                for a, d in satir if d))
        html('<div class="yan-bolum">Oturum</div>')
        if st.button("Çıkış yap", icon=":material/logout:", width="stretch"):
            st.session_state.clear()
            st.rerun()


# ---------- ANA AKIŞ ----------
if "kullanici" not in st.session_state:
    giris_ekrani()
else:
    k = st.session_state.kullanici
    yan_menu(k)
    if k["rol"] == "muhasebeci":
        muhasebeci_paneli(k)
    else:
        firma_paneli(k)
