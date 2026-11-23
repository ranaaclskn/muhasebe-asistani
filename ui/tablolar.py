"""Excel benzeri tablolar: nakit akış tablosu (HTML), Excel (.xlsx) raporu ve muhasebeci firma portföyü.
Veri app/nakit.py'den gelir; burada yalnızca GÖSTERİM vardır (hesap yok)."""
from datetime import date, datetime
from html import escape
from io import BytesIO

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from app.config import BUGUN
from app.kayit import AYLAR, tarih_tr
from app.nakit import KODLAR

SATIR_SINIFI = {"devir": "devir", "baslik": "baslik", "kalem": "kalem", "alt": "alt", "toplam_giris": "t-giris",
                "toplam_cikis": "t-cikis", "net": "net", "kumulatif": "kumulatif"}

NAKIT_CSS = """
<style>
.nakit-kap { overflow:auto; border:1px solid var(--line, #e2e6ec); border-radius:6px; max-height:520px; }
table.nakit { border-collapse:separate; border-spacing:0; width:100%; font-size:.82rem; color:#1f2937;
              font-variant-numeric:tabular-nums; }
table.nakit th, table.nakit td { padding:6px 10px; border-bottom:1px solid #eef0f4; white-space:nowrap; }
table.nakit thead th { position:sticky; top:0; z-index:2; background:#12355b; color:#fff; font-weight:600;
                       text-align:right; font-size:.78rem; }
table.nakit thead th small { display:block; font-weight:400; color:#b9c8d8; font-size:.68rem; }
table.nakit th.kod, table.nakit td.kod { position:sticky; left:0; z-index:1; width:44px; text-align:center; }
table.nakit th.ad, table.nakit td.ad { position:sticky; left:44px; z-index:1; text-align:left; min-width:210px;
                                        border-right:1px solid #e2e6ec; }
table.nakit thead th.kod, table.nakit thead th.ad { z-index:3; }
table.nakit td { text-align:right; background:#fff; }
table.nakit td.kod, table.nakit td.ad { background:#fff; }
table.nakit td.plan { background:#fafbfd; }
table.nakit td.top { font-weight:700; border-left:1px solid #e2e6ec; }
table.nakit .eksi { color:#b42318; }
table.nakit .bos { color:#c3c8d0; }
table.nakit tr.baslik td { background:#eef1f5 !important; color:#52606d; font-weight:700; font-size:.72rem;
                           letter-spacing:.07em; }
table.nakit tr.kalem td { font-weight:600; }
table.nakit tr.alt td { color:#52606d; font-size:.8rem; }
table.nakit tr.alt td.ad { padding-left:26px; }
table.nakit tr.devir td { background:#f8f9fb !important; color:#52606d; font-style:italic; }
table.nakit tr.t-giris td { background:#eaf5ec !important; font-weight:700; border-top:1px solid #b9dfc3; }
table.nakit tr.t-cikis td { background:#fbeceb !important; font-weight:700; border-top:1px solid #f2c4c0; }
table.nakit tr.net td { background:#fff7df !important; font-weight:800; border-top:2px solid #12355b; }
table.nakit tr.kumulatif td { background:#f4f7fb !important; font-weight:700; color:#12355b; }
table.portfoy td { text-align:left; } table.portfoy td.sayi { text-align:right; }
.durum-rozet { display:inline-block; font-size:.72rem; font-weight:600; padding:2px 8px; border-radius:4px; }
.durum-rozet.kirmizi { color:#b42318; background:#fdf3f2; border:1px solid #f2c4c0; }
.durum-rozet.sari { color:#9a6700; background:#fff8e6; border:1px solid #f1dc9c; }
.durum-rozet.yesil { color:#1a7f37; background:#f1f8f3; border:1px solid #b9dfc3; }
</style>
"""


def ay_etiketi(ay):
    y, a = ay.split("-")
    return f"{AYLAR[int(a) - 1][:3]} {y}"


def ay_durumu(ay):
    bu_ay = BUGUN[:7]
    return "Plan" if ay > bu_ay else ("Bu ay" if ay == bu_ay else "Gerçekleşen")


def tl_tam(tutar):
    """Tabloda kuruşsuz yazım: -54938.65 -> '−54.939'. Sıfır -> '–'."""
    if abs(tutar) < 0.5:
        return '<span class="bos">–</span>'
    metin = f"{abs(tutar):,.0f}".replace(",", ".")
    return f'<span class="eksi">−{metin}</span>' if tutar < 0 else metin


def nakit_html(satirlar, aylar, kirilim=True):
    """Nakit akış tablosu (HTML). Ödemeler kırmızı ve eksi; ileri tarihli aylar 'Plan'."""
    bas = ('<th class="kod">Kod</th><th class="ad">Açıklama</th>'
           + "".join(f"<th>{ay_etiketi(a)}<small>{ay_durumu(a)}</small></th>" for a in aylar)
           + "<th>Toplam<small>dönem</small></th>")
    govde = []
    for s in satirlar:
        if s["tip"] == "alt" and not kirilim:
            continue
        sinif = SATIR_SINIFI[s["tip"]]
        if s["tip"] == "baslik":
            govde.append(f'<tr class="{sinif}"><td class="kod"></td><td class="ad">{s["ad"]}</td>'
                         + "<td></td>" * (len(aylar) + 1) + "</tr>")
            continue
        hucreler = "".join(f'<td class="{"plan" if ay_durumu(a) == "Plan" else ""}">{tl_tam(s["degerler"][a])}</td>'
                           for a in aylar)
        kod = s["kod"] if s["kod"] and s["tip"] == "kalem" else ""
        govde.append(f'<tr class="{sinif}"><td class="kod">{kod}</td><td class="ad">{escape(s["ad"])}</td>'
                     f'{hucreler}<td class="top">{tl_tam(s["toplam"])}</td></tr>')
    return (NAKIT_CSS + f'<div class="nakit-kap"><table class="nakit"><thead><tr>{bas}</tr></thead>'
            f'<tbody>{"".join(govde)}</tbody></table></div>')


def portfoy_html(satirlar):
    """Muhasebeci için firma portföyü tablosu."""
    bas = "".join(f"<th style='text-align:left'>{b}</th>" for b in
                  ["Firma", "Çalışan", "Bu ay ödenecek", "Geciken", "En yakın son tarih", "Net (3 ay)",
                   "Talep", "Durum"])
    govde = "".join(
        f"<tr><td><b>{escape(r['unvan'])}</b><br><small style='color:#6b7280'>{escape(r['sektor'] or '')}</small></td>"
        f"<td class='sayi'>{r['calisan']}</td><td class='sayi'>{r['bu_ay']}</td><td class='sayi'>{r['geciken']}</td>"
        f"<td>{r['en_yakin']}</td><td class='sayi'>{r['net']}</td><td class='sayi'>{r['talep']}</td>"
        f"<td><span class='durum-rozet {r['ton']}'>{r['durum']}</span></td></tr>" for r in satirlar)
    return (NAKIT_CSS + '<div class="nakit-kap"><table class="nakit portfoy"><thead><tr>' + bas
            + f"</tr></thead><tbody>{govde}</tbody></table></div>")


# ---------- Excel (.xlsx) ----------
_INCE = Side(style="thin", color="D9DEE5")
_KENAR = Border(bottom=_INCE)
_SAYI = '#,##0.00;[Red]-#,##0.00;"–"'
_DOLGU = {"baslik": "EEF1F5", "devir": "F8F9FB", "toplam_giris": "EAF5EC", "toplam_cikis": "FBECEB",
          "net": "FFF7DF", "kumulatif": "F4F7FB"}
_BASLIK = PatternFill("solid", fgColor="12355B")


def _baslik_satiri(ws, satir, basliklar):
    for i, b in enumerate(basliklar, 1):
        c = ws.cell(satir, i, b)
        c.font, c.fill = Font(bold=True, color="FFFFFF"), _BASLIK
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def excel_raporu(unvan, satirlar, aylar, hareket_listesi):
    """Üç sayfalı rapor: 'Nakit Akış' (kod × ay), 'Hareket' (filtreli, toplamlı), 'Kodlar'. Bayt döndürür."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Nakit Akış"
    ws["A1"] = f"{unvan} · Nakit Akış Tablosu (TL)"
    ws["A1"].font = Font(bold=True, size=14, color="12355B")
    ws["A2"] = (f"Dönem: {ay_etiketi(aylar[0])} – {ay_etiketi(aylar[-1])} · Oluşturma: "
                f"{datetime.now():%d.%m.%Y %H:%M} · Ödemeler eksi işaretlidir · Demo veri, kurgusaldır")
    ws["A2"].font = Font(italic=True, color="6B7280")
    _baslik_satiri(ws, 4, ["Kod", "Açıklama"] + [f"{ay_etiketi(a)}\n{ay_durumu(a)}" for a in aylar] + ["Toplam"])
    ws.row_dimensions[4].height = 30
    r = 5
    for s in satirlar:
        ws.cell(r, 1, s["kod"] if s["tip"] == "kalem" else None).alignment = Alignment(horizontal="center")
        ws.cell(r, 2, ("    " if s["tip"] == "alt" else "") + s["ad"])
        if s["tip"] != "baslik":
            for j, a in enumerate(aylar, 3):
                ws.cell(r, j, s["degerler"][a]).number_format = _SAYI
            ws.cell(r, len(aylar) + 3, s["toplam"]).number_format = _SAYI
        kalin = s["tip"] in ("kalem", "baslik", "toplam_giris", "toplam_cikis", "net", "kumulatif")
        for j in range(1, len(aylar) + 4):
            c = ws.cell(r, j)
            c.border = _KENAR
            c.font = Font(bold=kalin, italic=s["tip"] == "devir", color="52606D" if s["tip"] == "alt" else "1F2937")
            if s["tip"] in _DOLGU:
                c.fill = PatternFill("solid", fgColor=_DOLGU[s["tip"]])
        r += 1
    ws.column_dimensions["A"].width = 7
    ws.column_dimensions["B"].width = 34
    for j in range(3, len(aylar) + 4):
        ws.column_dimensions[get_column_letter(j)].width = 15
    ws.freeze_panes = "C5"

    hs = wb.create_sheet("Hareket")
    hs["A1"] = f"{unvan} · Hareket Dökümü"
    hs["A1"].font = Font(bold=True, size=14, color="12355B")
    basliklar = ["Tarih", "Vade", "Yön", "Kod", "Kalem", "İşlem", "Karşı taraf", "Giriş (TL)", "Çıkış (TL)", "Durum"]
    _baslik_satiri(hs, 3, basliklar)
    for i, h in enumerate(hareket_listesi, 4):
        degerler = [date.fromisoformat(h["tarih"]), date.fromisoformat(h["vade"]), h["yon"], h["kod"], h["kalem"],
                    h["islem"], h["karsi_taraf"], h["tutar"] if h["yon"] == "Giriş" else None,
                    h["tutar"] if h["yon"] == "Çıkış" else None, h["durum"]]
        for j, v in enumerate(degerler, 1):
            c = hs.cell(i, j, v)
            c.border = _KENAR
            if j in (1, 2):
                c.number_format = "DD.MM.YYYY"
            elif j in (8, 9):
                c.number_format = '#,##0.00'
    son = len(hareket_listesi) + 3
    hs.cell(son + 1, 7, "TOPLAM").font = Font(bold=True)
    for j in (8, 9):
        harf = get_column_letter(j)
        c = hs.cell(son + 1, j, f"=SUBTOTAL(9,{harf}4:{harf}{son})")  # filtre uygulanınca görünenleri toplar
        c.number_format, c.font = '#,##0.00', Font(bold=True)
    hs.auto_filter.ref = f"A3:J{son}"
    hs.freeze_panes = "A4"
    for harf, gen in zip("ABCDEFGHIJ", [12, 12, 8, 6, 26, 40, 28, 15, 15, 13]):
        hs.column_dimensions[harf].width = gen

    ks = wb.create_sheet("Kodlar")
    _baslik_satiri(ks, 1, ["Kod", "Kalem", "Yön"])
    for i, (kod, (ad, yon)) in enumerate(KODLAR.items(), 2):
        ks.cell(i, 1, kod), ks.cell(i, 2, ad), ks.cell(i, 3, yon)
    ks.column_dimensions["B"].width = 30

    tampon = BytesIO()
    wb.save(tampon)
    return tampon.getvalue()


def hareket_tablosu(liste):
    """Hareket dökümü için ekran satırları (tutarlar Türkçe biçimde metin). Ekranda "Yön" ve "Kalem" yok:
    yön Giriş/Çıkış sütunundan, kalem koddan anlaşılır (Excel dosyasında ikisi de var)."""
    def tl2(x):
        return f"{x:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return [{"Tarih": tarih_tr(h["tarih"]), "Vade": tarih_tr(h["vade"]), "Kod": h["kod"],
             "İşlem": h["islem"], "Karşı taraf": h["karsi_taraf"],
             "Giriş": tl2(h["tutar"]) if h["yon"] == "Giriş" else "", "Çıkış": tl2(h["tutar"]) if h["yon"] == "Çıkış" else "",
             "Durum": h["durum"]} for h in liste]
