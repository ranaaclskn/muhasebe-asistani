"""Gelir–gider grafiği (firma paneli). Veri: app.db.aylik_gelir_gider -> ay ay toplamlar -> Altair.

Gelir çubukları sıfırın ÜSTÜNE, gider çubukları ALTINA çizilir; koyu çizgi her ayın NET'idir
(gelir − gider). Çizgi sıfırın üstündeyse o ay artıdayız, altındaysa eksideyiz.
"""
import altair as alt
import pandas as pd

from app.config import BUGUN
from app.db import aylik_gelir_gider
from app.kayit import AYLAR, tl

RENK = {"Gelir": "#2a78d6", "Gider": "#e34948", "Net": "#1e1b4b"}
PENCERELER = {"Son 3 ay": 3, "Son 6 ay": 6, "Tümü": None}


def _ay_ekle(ay, n):
    y, a = map(int, ay.split("-"))
    a += n
    y, a = y + (a - 1) // 12, (a - 1) % 12 + 1
    return f"{y:04d}-{a:02d}"


def kisa_tl(tutar):
    """-224310.5 -> '−224 bin TL'; 1250000 -> '1,25 mn TL' (kart ve grafik için kısa yazım)."""
    isaret = "−" if tutar < 0 else ""
    t = abs(tutar)
    if t >= 1_000_000:
        return f"{isaret}{t / 1_000_000:.2f}".replace(".", ",") + " mn TL"
    if t >= 1_000:
        return f"{isaret}{t / 1_000:,.0f}".replace(",", ".") + " bin TL"
    return f"{isaret}{t:,.0f} TL"


def aylik_tablo(firma_id, pencere="Son 3 ay"):
    """Seçilen pencere için ay başına bir satır: gelir, gider, net ve kalem ayrıntısı.
    Pencere = bu ay dahil son N takvim ayı + ileri tarihli planlı/bekleyen aylar."""
    satirlar = [r for r in aylik_gelir_gider(firma_id) if r["ay"]]
    bu_ay = BUGUN[:7]
    if not satirlar:
        return pd.DataFrame()
    ilk = min(r["ay"] for r in satirlar)
    son = max(max(r["ay"] for r in satirlar), bu_ay)

    n = PENCERELER[pencere]
    bas = _ay_ekle(bu_ay, -(n - 1)) if n else ilk
    aylar, ay = [], bas
    while ay <= son:
        aylar.append(ay)
        ay = _ay_ekle(ay, 1)

    tek_yil = len({ay[:4] for ay in aylar}) == 1  # tek yılsa etikette yıl yazmaya gerek yok
    kayit = []
    for ay in aylar:
        kalemler = [r for r in satirlar if r["ay"] == ay]
        gelir = sum(r["tutar"] for r in kalemler if r["yon"] == "Gelir")
        gider = sum(r["tutar"] for r in kalemler if r["yon"] == "Gider")
        y, a = ay.split("-")
        plan = ay > bu_ay
        kayit.append({
            "ay": ay,
            "etiket": AYLAR[int(a) - 1][:3] + ("" if tek_yil else f" '{y[2:]}") + (" (plan)" if plan else ""),
            "durum": "Planlanan" if plan else "Gerçekleşen",
            "gelir": gelir, "gider": gider, "net": gelir - gider,
            "Gelir ": tl(gelir), "Gider ": tl(gider), "Net ": tl(gelir - gider),
            "net_kisa": ("+" if gelir - gider > 0 else "") + kisa_tl(gelir - gider).removesuffix(" TL"),
            "Gelir kalemleri": " · ".join(f"{r['kalem']}: {tl(r['tutar'])}" for r in kalemler
                                          if r["yon"] == "Gelir") or "—",
            "Gider kalemleri": " · ".join(f"{r['kalem']}: {tl(r['tutar'])}" for r in kalemler
                                          if r["yon"] == "Gider") or "—",
        })
    return pd.DataFrame(kayit)


def grafik(df):
    """Gelir (+) / gider (−) çubukları, net çizgisi ve üst şeritte ay ay net yazısı."""
    sira = list(df["etiket"])
    ipucu = [alt.Tooltip("etiket:N", title="Ay"), alt.Tooltip("Gelir :N"), alt.Tooltip("Gider :N"),
             alt.Tooltip("Net :N"), alt.Tooltip("Gelir kalemleri:N"), alt.Tooltip("Gider kalemleri:N")]

    uzun = pd.concat([df.assign(seri="Gelir", deger=df["gelir"]),
                      df.assign(seri="Gider", deger=-df["gider"])])
    tepe = max(df["gelir"].max(), df["net"].max(), 1)
    dip = min(-df["gider"].max(), df["net"].min(), -1)

    x = alt.X("etiket:N", sort=sira, title=None,
              axis=alt.Axis(labelAngle=0, domain=False, ticks=False, labelPadding=8, labelFontSize=12,
                            labelOverlap=False))
    y_ekseni = alt.Axis(labelExpr="datum.value == 0 ? '0' : format(datum.value / 1000, ',.0f') + ' bin'",
                        domain=False, ticks=False, tickCount=5, gridColor="#eceef4")
    y_olcek = alt.Scale(domain=[dip * 1.08, tepe * 1.28], nice=False)
    renk = alt.Color("seri:N", scale=alt.Scale(domain=list(RENK), range=list(RENK.values())),
                     legend=alt.Legend(orient="bottom", title=None, direction="horizontal",
                                       symbolType="circle", labelFontSize=12))
    saydam = alt.Opacity("durum:N", scale=alt.Scale(domain=["Gerçekleşen", "Planlanan"], range=[1, 0.45]),
                         legend=None)

    cubuk = alt.Chart(uzun).mark_bar(width=alt.RelativeBandSize(0.5), cornerRadiusEnd=4).encode(
        x=x, y=alt.Y("deger:Q", title=None, axis=y_ekseni, scale=y_olcek), color=renk, opacity=saydam,
        tooltip=ipucu)
    sifir = alt.Chart(pd.DataFrame({"y": [0]})).mark_rule(color="#94a3b8", strokeWidth=1).encode(y="y:Q")
    net = alt.Chart(df.assign(seri="Net"))
    cizgi = net.mark_line(strokeWidth=2).encode(x=x, y="net:Q", color=renk)
    nokta = net.mark_point(filled=True, size=110, stroke="white", strokeWidth=2, opacity=1).encode(
        x=x, y="net:Q", color=renk, tooltip=ipucu)
    serit = net.mark_text(fontSize=11, fontWeight=600, color="#334155", baseline="top").encode(
        x=x, y=alt.value(4), text="net_kisa:N")

    katmanlar = [cubuk, sifir, cizgi, nokta]
    if len(df) <= 4:  # çok ayda yazılar sığmaz; net yine çizgide ve ipucunda (fareyle üzerine gelince)
        katmanlar.append(serit)
    return (alt.layer(*katmanlar)
            .properties(height=330)
            .configure_view(stroke=None)
            .configure_axis(labelColor="#64748b", labelFont="sans-serif"))
