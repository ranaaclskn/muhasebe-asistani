"""Analiz ekranlarının görünümü: uyarılar, ödeme takvimi, yaşlandırma, cari hesaplar, finansal sağlık, senaryo.
Hesaplar app/analiz.py'de; burada yalnızca HTML/grafik üretilir."""
import calendar
from datetime import date
from html import escape

import altair as alt
import pandas as pd

from app.config import BUGUN
from app.kayit import AYLAR, tarih_tr, tl
from app.analiz import KOVALAR

GUNLER = ["Pzt", "Sal", "Çar", "Per", "Cum", "Cmt", "Paz"]

ANALIZ_CSS = """
<style>
.uyari-kutu { display:flex; gap:10px; align-items:flex-start; padding:9px 12px; border-radius:6px; margin-bottom:6px;
         border:1px solid #e2e6ec; border-left-width:4px; background:#fff; }
.uyari-kutu .ikon { font-family:'Material Symbols Rounded'; font-size:20px; line-height:1.1; }
.uyari-kutu .b { font-weight:700; font-size:.86rem; color:#1f2937; } .uyari-kutu .d { font-size:.78rem; color:#6b7280; }
.uyari-kutu.s-kritik { border-left-color:#b42318; background:#fdf6f5; } .uyari-kutu.s-kritik .ikon { color:#b42318; }
.uyari-kutu.s-uyari { border-left-color:#d29b00; background:#fffbf0; } .uyari-kutu.s-uyari .ikon { color:#9a6700; }
.uyari-kutu.s-bilgi { border-left-color:#2a78d6; background:#f5f9fe; } .uyari-kutu.s-bilgi .ikon { color:#2a78d6; }
.uyari-kutu.s-iyi { border-left-color:#1a7f37; background:#f3faf5; } .uyari-kutu.s-iyi .ikon { color:#1a7f37; }

.takvim { display:grid; grid-template-columns:repeat(7, 1fr); border:1px solid #e2e6ec; border-radius:6px;
          overflow:hidden; font-size:.76rem; }
.takvim .gb { background:#12355b; color:#fff; font-weight:600; text-align:center; padding:6px 0; font-size:.74rem; }
.takvim .gun { min-height:78px; border-top:1px solid #eef0f4; border-left:1px solid #eef0f4; padding:4px 5px;
               background:#fff; }
.takvim .gun:nth-child(7n+1) { border-left:none; }
.takvim .gun.disari { background:#f8f9fb; color:#b5bcc6; }
.takvim .gun.hs { background:#fbfcfd; }
.takvim .gun .no { font-weight:600; color:#52606d; margin-bottom:3px; }
.takvim .gun.bugun { box-shadow: inset 0 0 0 2px #12355b; } .takvim .gun.bugun .no { color:#12355b; }
.takvim .olay { border-radius:3px; padding:1px 5px; margin-bottom:2px; white-space:nowrap; overflow:hidden;
                text-overflow:ellipsis; font-size:.7rem; border-left:3px solid; }
.olay.Gecikti { background:#fdecea; border-color:#b42318; color:#8a1c12; }
.olay.Bekliyor { background:#fff6db; border-color:#d29b00; color:#7a5300; }
.olay.Ödendi { background:#eef7f0; border-color:#8cc79b; color:#52606d; }
.olay.Plan { background:#eef4fc; border-color:#2a78d6; color:#1c4f8f; }
.olay.Tahsilat { background:#e8f6ee; border-color:#1a7f37; color:#14632b; }
.lejant { display:flex; gap:12px; flex-wrap:wrap; font-size:.74rem; color:#52606d; margin:6px 0; }
.lejant span::before { content:""; display:inline-block; width:10px; height:10px; border-radius:2px;
                       margin-right:5px; vertical-align:-1px; background:var(--r); }

.kova { display:grid; grid-template-columns:repeat(4, 1fr); gap:8px; margin:4px 0 10px; }
.kova div { border:1px solid #e2e6ec; border-radius:6px; padding:8px 10px; background:#fff; }
.kova .e { font-size:.7rem; color:#6b7280; font-weight:600; text-transform:uppercase; letter-spacing:.04em; }
.kova .t { font-weight:700; font-variant-numeric:tabular-nums; } .kova .a { font-size:.74rem; color:#6b7280; }
.kova .k1 { border-top:3px solid #8cc79b; } .kova .k2 { border-top:3px solid #d29b00; }
.kova .k3 { border-top:3px solid #e0703a; } .kova .k4 { border-top:3px solid #b42318; }

.saglik { display:grid; grid-template-columns:210px 1fr; gap:22px; align-items:center; }
.halka { width:170px; height:170px; border-radius:50%; display:grid; place-items:center; margin:auto;
         background:conic-gradient(var(--renk) calc(var(--p) * 1%), #e9edf2 0); }
.halka > div { width:128px; height:128px; border-radius:50%; background:#fff; display:grid; place-items:center;
               text-align:center; }
.halka .p { font-size:2.3rem; font-weight:800; color:#1f2937; line-height:1; }
.halka .l { font-size:.78rem; font-weight:700; color:var(--renk); text-transform:uppercase; letter-spacing:.06em; }
.bilesen { margin-bottom:9px; } .bilesen .ust { display:flex; justify-content:space-between; font-size:.82rem; }
.bilesen .ust b { color:#1f2937; } .bilesen .ust span { color:#6b7280; font-variant-numeric:tabular-nums; }
.bilesen .cubuk { height:7px; background:#eef1f5; border-radius:4px; overflow:hidden; margin:3px 0 2px; }
.bilesen .cubuk i { display:block; height:100%; background:#12355b; border-radius:4px; }
.bilesen .ac { font-size:.72rem; color:#8a94a3; }
.metrikler { display:grid; grid-template-columns:repeat(3, 1fr); gap:8px; margin-top:12px; }
.metrik { border:1px solid #e2e6ec; border-radius:6px; padding:9px 12px; background:#fff; }
.metrik .e { font-size:.7rem; color:#6b7280; font-weight:600; text-transform:uppercase; letter-spacing:.04em; }
.metrik .d { font-size:1.15rem; font-weight:800; color:#1f2937; font-variant-numeric:tabular-nums; }
.metrik .a { font-size:.72rem; color:#8a94a3; }
.pay { display:inline-block; height:8px; background:#2a78d6; border-radius:2px; vertical-align:middle; margin-right:6px; }
</style>
"""

UYARI_IKON = {"kritik": "error", "uyari": "warning", "bilgi": "info", "iyi": "check_circle"}
DURUM_RENK = {"Gecikti": "#b42318", "Bekliyor": "#d29b00", "Ödendi": "#8cc79b", "Plan": "#2a78d6",
              "Tahsilat": "#1a7f37"}


def kisa(t):
    t = abs(t)
    return f"{t / 1_000_000:.1f} mn".replace(".", ",") if t >= 1_000_000 else (
        f"{t / 1000:.0f} bin" if t >= 1000 else f"{t:.0f}")


def uyarilar_html(liste):
    return ANALIZ_CSS + "".join(
        f'<div class="uyari-kutu s-{u["seviye"]}"><span class="ikon">{UYARI_IKON[u["seviye"]]}</span><div>'
        f'<div class="b">{escape(u["baslik"])}</div><div class="d">{escape(u["detay"])}</div></div></div>'
        for u in liste)


def takvim_html(yil, ay, olaylar, firma_kisa=None):
    """Ay takvimi: her gün hücresinde o gün son tarihi olan ödemeler (durum renginde)."""
    gunluk = {}
    for o in olaylar:
        gunluk.setdefault(o["tarih"], []).append(o)
    bugun = date.fromisoformat(BUGUN)
    hucreler = [f'<div class="gb">{g}</div>' for g in GUNLER]
    for hafta in calendar.Calendar(firstweekday=0).monthdatescalendar(yil, ay):
        for g in hafta:
            sinif = "gun" + (" disari" if g.month != ay else "") + (" bugun" if g == bugun else "") + \
                    (" hs" if g.weekday() >= 5 else "")
            ic = ""
            if g.month == ay:
                for o in gunluk.get(g.isoformat(), []):
                    onek = f"{firma_kisa[o['firma_id']]} · " if firma_kisa else ""
                    ipucu = (f"{onek}{o['baslik']} {o['donem']} — {tl(o['tutar'])} · {o['durum']}").strip()
                    ic += (f'<div class="olay {o["durum"]}" title="{escape(ipucu)}">{escape(onek + o["baslik"])} '
                           f'<b>{kisa(o["tutar"])}</b></div>')
            hucreler.append(f'<div class="{sinif}"><div class="no">{g.day}</div>{ic}</div>')
    lejant = "".join(f'<span style="--r:{r}">{d}</span>' for d, r in DURUM_RENK.items())
    return ANALIZ_CSS + f'<div class="lejant">{lejant}</div><div class="takvim">{"".join(hucreler)}</div>'


def ay_adi(ay):
    y, a = ay.split("-")
    return f"{AYLAR[int(a) - 1]} {y}"


def yaslandirma_html(kovalar):
    return ANALIZ_CSS + '<div class="kova">' + "".join(
        f'<div class="k{i}"><div class="e">{k}</div><div class="t">{tl(v["tutar"])}</div>'
        f'<div class="a">{v["adet"]} ödeme</div></div>' for i, (k, v) in enumerate(kovalar.items(), 1)) + "</div>"


def yaslandirma_tablo_html(satirlar):
    """Muhasebeci: firma × yaşlandırma kovası."""
    bas = "<th style='text-align:left'>Firma</th>" + "".join(f"<th>{k}</th>" for k in KOVALAR) + "<th>Toplam</th>"
    govde = ""
    for unvan, kv in satirlar:
        hucre = "".join(
            f"<td style='{'color:#b42318;font-weight:700' if i and v['tutar'] else ''}'>"
            f"{tl(v['tutar']) if v['tutar'] else '–'} <small style='color:#8a94a3'>"
            f"{'(' + str(v['adet']) + ')' if v['adet'] else ''}</small></td>"
            for i, v in enumerate(kv.values()))
        toplam = sum(v["tutar"] for v in kv.values())
        govde += f"<tr><td style='text-align:left'><b>{escape(unvan)}</b></td>{hucre}<td><b>{tl(toplam)}</b></td></tr>"
    from ui.tablolar import NAKIT_CSS
    return NAKIT_CSS + f'<div class="nakit-kap"><table class="nakit"><thead><tr>{bas}</tr></thead>' \
                       f'<tbody>{govde}</tbody></table></div>'


def cari_html(liste, baslik):
    from ui.tablolar import NAKIT_CSS
    en_buyuk = max((c["pay"] for c in liste), default=1) or 1
    satir = "".join(
        f"<tr><td style='text-align:left'><b>{escape(c['karsi_taraf'])}</b></td>"
        f"<td style='text-align:left'><span class='pay' style='width:{c['pay'] / en_buyuk * 120:.0f}px'></span>"
        f"%{c['pay'] * 100:.1f}</td><td>{tl(c['toplam'])}</td><td>{c['adet']}</td><td>{tl(c['ortalama'])}</td>"
        f"<td>{tarih_tr(c['ilk'])}</td><td>{tarih_tr(c['son'])}</td></tr>" for c in liste)
    bas = "".join(f"<th{' style=text-align:left' if i < 2 else ''}>{b}</th>" for i, b in enumerate(
        [baslik, "Pay", "Toplam", "Fatura", "Ortalama fatura", "İlk işlem", "Son işlem"]))
    return ANALIZ_CSS + NAKIT_CSS + f'<div class="nakit-kap"><table class="nakit"><thead><tr>{bas}</tr></thead>' \
                                    f'<tbody>{satir}</tbody></table></div>'


def saglik_html(g):
    renk = "#1a7f37" if g["puan"] >= 80 else "#2a78d6" if g["puan"] >= 60 else "#d29b00" if g["puan"] >= 40 else "#b42318"
    bilesen = "".join(
        f'<div class="bilesen"><div class="ust"><b>{a}</b><span>{f"{p:.1f}".replace(".", ",")} / {m}</span></div>'
        f'<div class="cubuk"><i style="width:{p / m * 100:.0f}%"></i></div><div class="ac">{escape(ac)}</div></div>'
        for a, p, m, ac in g["bilesenler"])

    def yuzde(x):
        return f"%{x * 100:.0f}".replace(".", ",")
    buyume = "—" if g["buyume"] is None else ("+" if g["buyume"] > 0 else "−") + yuzde(abs(g["buyume"]))
    metrikler = [
        ("Net nakit marjı", yuzde(g["net_marj"]), f"Son {g['ay_sayisi']} ay: (gelir − gider) / satış"),
        ("Gelir büyümesi", buyume, "Son 3 tamamlanmış ay / önceki 3 ay"),
        ("Personel gider oranı", yuzde(g["personel_orani"]), "(Net maaş + SGK + muhtasar) / satış"),
        ("Vergi yükü", yuzde(g["vergi_orani"]), "(KDV + geçici vergi) / satış"),
        ("Zamanında ödeme", yuzde(g["zamaninda_oran"]), f"{g['geciken']} gecikmiş ödeme var" if g["geciken"]
         else "Gecikmiş ödeme yok"),
        ("Nakit dayanıklılığı", f"{g['karsilama_ay']:.1f} ay".replace(".", ","),
         f"Birikmiş {kisa(g['birikmis'])} TL / aylık gider {kisa(g['aylik_gider'])} TL"),
    ]
    kartlar = "".join(f'<div class="metrik"><div class="e">{e}</div><div class="d">{d}</div><div class="a">{a}</div>'
                      f'</div>' for e, d, a in metrikler)
    return (ANALIZ_CSS + f'<div class="saglik"><div class="halka" style="--p:{g["puan"]};--renk:{renk}"><div>'
            f'<div><div class="p">{g["puan"]}</div><div class="l">{g["etiket"]}</div>'
            f'<div style="font-size:.7rem;color:#8a94a3">/ 100</div></div></div></div><div>{bilesen}</div></div>'
            f'<div class="metrikler">{kartlar}</div>')


def senaryo_grafigi(s):
    """Birikmiş nakit: mevcut gidişat (kesikli) ve senaryo (düz)."""
    satirlar = [{"Ay": ay_adi(r["ay"]), "sira": i, "Seri": seri, "Birikmiş nakit": r[alan]}
                for i, r in enumerate(s["aylar"])
                for seri, alan in (("Mevcut gidişat", "kumulatif_mevcut"), ("Senaryo", "kumulatif_senaryo"))]
    df = pd.DataFrame(satirlar)
    sira = [ay_adi(r["ay"]) for r in s["aylar"]]
    renk = alt.Color("Seri:N", scale=alt.Scale(domain=["Mevcut gidişat", "Senaryo"], range=["#8a94a3", "#2a78d6"]),
                     legend=alt.Legend(orient="bottom", title=None))
    taban = alt.Chart(df).encode(
        x=alt.X("Ay:N", sort=sira, title=None, axis=alt.Axis(labelAngle=0, labelColor="#64748b")),
        y=alt.Y("Birikmiş nakit:Q", title=None, axis=alt.Axis(
            labelExpr="format(datum.value / 1000, ',.0f') + ' bin'", labelColor="#64748b", gridColor="#eceef4")),
        color=renk, strokeDash=alt.StrokeDash("Seri:N", scale=alt.Scale(
            domain=["Mevcut gidişat", "Senaryo"], range=[[5, 4], [1, 0]]), legend=None),
        tooltip=[alt.Tooltip("Ay:N"), alt.Tooltip("Seri:N"), alt.Tooltip("Birikmiş nakit:Q", format=",.0f")])
    sifir = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="#94a3b8").encode(y="y:Q")
    return (alt.layer(taban.mark_line(strokeWidth=2.5), taban.mark_point(filled=True, size=60), sifir)
            .properties(height=250).configure_view(stroke=None))
