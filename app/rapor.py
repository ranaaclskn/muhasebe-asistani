"""Aylık yönetici raporu (PDF): firmanın bir aylık özeti tek dosyada.

İçerik: ayın tahsilat/ödeme/net özeti (önceki aya göre değişim), uyarılar, son 6 ayın gelir–gider grafiği,
ayın kalem dağılımı, en büyük müşteri ve satıcılar, nakit akış tablosu (6 ay), finansal sağlık puanı ve
yaklaşan ödemeler.

İki aşama, iki fonksiyon:
  rapor_verisi(firma_id, ay) -> dict   : TÜM rakamlar mevcut fonksiyonlardan (app/nakit, app/analiz) gelir.
                                         Model kullanılmaz; panel ve asistanla aynı kaynak, aynı sonuç (test edilir).
  rapor_pdf(firma_id, ay)    -> bytes  : yalnızca yerleşim (fpdf2). Hesap yapmaz, veriyi yazar.

İki tür bilgi vardır ve PDF'te ayrı başlıklarla yazılır:
  - Rapor AYI (seçilen, tamamlanmış ay): tahsilat, ödeme, kalemler, müşteri/satıcı.
  - Rapor TARİHİ itibarıyla güncel durum: uyarılar, sağlık puanı, yaklaşan/geciken ödemeler.

Kontrol (proje klasöründen):  python -m pytest -q tests/test_rapor.py
Komut satırından:              python scripts/06_aylik_rapor.py
"""
from datetime import date, datetime, timedelta
from pathlib import Path

from fpdf import FPDF
from fpdf.fonts import FontFace

from app import alacak, analiz, db
from app.kayit import AYLAR, donem_tr, tarih_tr, tl
from app.nakit import KODLAR, _ay_ekle, hareketler, nakit_akis_tablosu

FONT_DIR = Path(__file__).resolve().parent / "fonts"  # DejaVu: Türkçe karakterler (ş, ğ, İ, ı) için
AY_SAYISI = 6  # grafik ve nakit akış tablosu: rapor ayı dahil son 6 ay


def varsayilan_ay():
    """Rapor ayı: bugünden önceki son TAMAMLANMIŞ ay (her ayın 1'inde geçen ayın raporu alınır)."""
    return _ay_ekle(db.BUGUN[:7], -1)


def secilebilir_aylar(n=6):
    """Arayüzdeki seçim listesi: tamamlanmış son n ay, en yenisi başta."""
    return [_ay_ekle(db.BUGUN[:7], -i) for i in range(1, n + 1)]



# ---------- 1) VERİ (hesap burada; PDF yalnızca bunu yazar) ----------
def rapor_verisi(firma_id, ay=None):
    ay = ay or varsayilan_ay()
    firma = db.firma_bilgisi(firma_id)  # bilinmeyen firma -> _firma_kontrol hata verir
    liste = hareketler(firma_id)
    onceki = _ay_ekle(ay, -1)

    def ay_toplami(a, yon):
        return round(sum(h["tutar"] for h in liste if h["ay"] == a and h["yon"] == yon), 2)

    giris, cikis = ay_toplami(ay, "Giriş"), ay_toplami(ay, "Çıkış")
    o_giris, o_cikis = ay_toplami(onceki, "Giriş"), ay_toplami(onceki, "Çıkış")

    def degisim(simdi, once):
        return (simdi - once) / once if once else None

    kalemler = []  # ayın kod bazında dökümü (nakit akış tablosundaki satırlarla aynı adlar)
    for kod, (ad, yon) in KODLAR.items():
        tutar = round(sum(h["tutar"] for h in liste if h["ay"] == ay and h["kod"] == kod), 2)
        if tutar:
            kalemler.append({"kod": kod, "ad": ad, "yon": yon, "tutar": tutar,
                             "pay": tutar / (giris if yon == "Giriş" else cikis)})

    def en_buyukler(kod, n=5):
        g = {}
        for h in liste:
            if h["belge_ay"] == ay and h["kod"] == kod:  # fatura ayına göre (tahsilat gecikmesinden bağımsız)
                g[h["karsi_taraf"]] = g.get(h["karsi_taraf"], 0) + h["tutar"]
        toplam = sum(g.values()) or 1
        return [{"ad": k, "tutar": round(v, 2), "pay": v / toplam}
                for k, v in sorted(g.items(), key=lambda x: -x[1])[:n]]

    aylar = [_ay_ekle(ay, -i) for i in range(AY_SAYISI - 1, -1, -1)]
    grafik = [{"ay": a, "giris": ay_toplami(a, "Giriş"), "cikis": ay_toplami(a, "Çıkış")} for a in aylar]
    for g in grafik:
        g["net"] = round(g["giris"] - g["cikis"], 2)
    tablo = [s for s in nakit_akis_tablosu(liste, aylar) if s["tip"] != "alt"]  # kırılımsız (sayfaya sığsın)

    bugun = date.fromisoformat(db.BUGUN)
    sinir = (bugun + timedelta(days=30)).isoformat()
    odemeler = [{"tarih": s["son_odeme_tarihi"], "ad": s["tur"], "aciklama": donem_tr(s["donem"]),
                 "tutar": s["tutar_tl"], "durum": s["durum"]}
                for s in db.yukumlulukler(firma_id)
                if s["durum"] == "Gecikti" or (s["durum"] == "Bekliyor" and s["son_odeme_tarihi"] <= sinir)]
    odemeler += [{"tarih": p["tarih"], "ad": p["aciklama"], "aciklama": "Planlı ödeme", "tutar": p["tutar_tl"],
                  "durum": "Plan"} for p in db.planli_islemler(firma_id)
                 if p["yon"] == "Gider" and db.BUGUN <= p["tarih"] <= sinir]
    odemeler.sort(key=lambda o: o["tarih"])
    for o in odemeler:
        o["gun"] = (date.fromisoformat(o["tarih"]) - bugun).days

    return {
        "firma_id": firma_id, "unvan": firma.get("unvan", firma_id), "firma": firma,
        "ay": ay, "ay_adi": donem_tr(ay), "onceki_ay_adi": donem_tr(onceki), "rapor_tarihi": db.BUGUN,
        "ozet": {"giris": giris, "cikis": cikis, "net": round(giris - cikis, 2),
                 "onceki_net": round(o_giris - o_cikis, 2),
                 "giris_degisim": degisim(giris, o_giris), "cikis_degisim": degisim(cikis, o_cikis)},
        "kalemler": kalemler, "musteriler": en_buyukler(10), "saticilar": en_buyukler(58),
        "grafik": grafik, "aylar": aylar, "tablo": tablo,
        "uyarilar": analiz.uyarilar(firma_id), "saglik": analiz.gostergeler(firma_id),
        "odemeler": odemeler,
        "alacak": {"ozet": alacak.ozet(firma_id), "acik": alacak.acik_alacaklar(firma_id)},
    }


# ---------- 2) PDF (yerleşim) ----------
LACIVERT, MURE, CIZGI, ZEMIN = (18, 53, 91), (100, 116, 139), (220, 226, 234), (244, 246, 250)
YESIL, KIRMIZI, SARI, MAVI, GRI = (26, 127, 55), (180, 35, 24), (154, 103, 0), (42, 120, 214), (138, 148, 163)
SEVIYE_RENK = {"kritik": KIRMIZI, "uyari": SARI, "bilgi": MAVI, "iyi": YESIL}
SEVIYE_AD = {"kritik": "Kritik", "uyari": "Uyarı", "bilgi": "Bilgi", "iyi": "İyi"}


def _tam(x):
    """1234567.8 -> '1.234.568' (tabloda kuruşsuz)"""
    return f"{x:,.0f}".replace(",", ".").replace("-", "−")


def _kisa(x):
    """Grafik ekseni: 125000 -> '125 bin', 1250000 -> '1,25 mn'"""
    if abs(x) >= 1_000_000:
        return f"{x / 1_000_000:.2f}".replace(".", ",") + " mn"
    return f"{x / 1000:.0f} bin" if x else "0"


def _yuzde(x, isaretli=False):
    if x is None:
        return "—"
    metin = f"%{abs(x) * 100:.1f}".replace(".", ",")
    return (("+" if x >= 0 else "−") + metin) if isaretli else metin


class _Rapor(FPDF):
    def __init__(self, v):
        super().__init__(format="A4")
        self.v = v
        self.add_font("DejaVu", "", str(FONT_DIR / "DejaVuSans.ttf"))
        self.add_font("DejaVu", "B", str(FONT_DIR / "DejaVuSans-Bold.ttf"))
        self.set_margins(12, 12, 12)
        self.set_auto_page_break(True, 16)
        self.set_title(f"{v['unvan']} - Aylık yönetici raporu - {v['ay_adi']}")
        self.set_author("Kişisel Muhasebe Asistanı")

    def footer(self):
        self.set_y(-11)
        self.set_font("DejaVu", "", 6.5)
        self.set_text_color(*GRI)
        self.cell(0, 4, "Demo prototip · Firmalar ve rakamlar kurgusaldır · Tüm rakamlar veritabanından kodla "
                        "hesaplanmıştır, yapay zekâ modeli rakam üretmemiştir", align="L")
        self.cell(0, 4, f"Sayfa {self.page_no()}/{{nb}}", align="R", new_x="LMARGIN", new_y="NEXT")

    # --- küçük yardımcılar ---
    def yazi(self, boyut, kalin=False, renk=(31, 41, 55)):
        self.set_font("DejaVu", "B" if kalin else "", boyut)
        self.set_text_color(*renk)

    def bolum(self, baslik, aciklama=""):
        if self.get_y() > self.h - 50:
            self.add_page()
        self.ln(3)
        self.yazi(10.5, True, LACIVERT)
        self.cell(0, 6, baslik, new_x="LMARGIN", new_y="NEXT")
        if aciklama:
            self.yazi(7, renk=MURE)
            self.cell(0, 3.5, aciklama, new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*CIZGI)
        self.line(self.l_margin, self.get_y() + 1, self.w - self.r_margin, self.get_y() + 1)
        self.ln(3)

    def tablo(self, basliklar, satirlar, genislikler, hizalar, vurgu=None, boyut=7.5):
        """vurgu: satır indeksi -> 'kalin' | 'zemin' | 'kirmizi' (dict)"""
        vurgu = vurgu or {}
        self.yazi(boyut)
        self.set_draw_color(*CIZGI)
        beyaz = (255, 255, 255)
        self.set_fill_color(*beyaz)  # tablo, önceki çizimden kalan dolgu rengini kullanmasın
        baslik_stili = FontFace(emphasis="BOLD", color=beyaz, fill_color=LACIVERT)
        with self.table(col_widths=genislikler, text_align=hizalar, headings_style=baslik_stili,
                        line_height=4.6, padding=(0.8, 1.5), borders_layout="HORIZONTAL_LINES",
                        width=sum(genislikler), align="LEFT") as t:
            r = t.row()
            for b in basliklar:
                r.cell(b)
            for i, satir in enumerate(satirlar):
                stil = {"kalin": FontFace(emphasis="BOLD", fill_color=beyaz),
                        "zemin": FontFace(emphasis="BOLD", fill_color=ZEMIN),
                        "kirmizi": FontFace(color=KIRMIZI, fill_color=beyaz)}.get(vurgu.get(i),
                                                                                 FontFace(fill_color=beyaz))
                r = t.row()
                for hucre in satir:
                    r.cell(str(hucre), style=stil)


def _kpi(pdf, x, y, w, etiket, deger, alt, renk=(31, 41, 55)):
    pdf.set_fill_color(*ZEMIN)
    pdf.rect(x, y, w, 20, style="F")
    pdf.set_xy(x + 3, y + 2.5)
    pdf.yazi(6.8, renk=MURE)
    pdf.cell(w - 6, 3.5, etiket.upper())
    pdf.set_xy(x + 3, y + 7)
    pdf.yazi(12, True, renk)
    pdf.cell(w - 6, 6, deger)
    pdf.set_xy(x + 3, y + 14)
    pdf.yazi(6.8, renk=MURE)
    pdf.cell(w - 6, 3.5, alt)


def _grafik(pdf, veri, x, y, w, h):
    """Son 6 ay: tahsilat (mavi) ve ödeme (gri) çubukları, altında net."""
    tepe = max([max(g["giris"], g["cikis"]) for g in veri] + [1])
    adim = 10 ** (len(str(int(tepe))) - 1)
    tepe = (int(tepe / adim) + 1) * adim  # yuvarlak üst sınır
    sol, alt_bosluk = 16, 11
    gx, gw, gh = x + sol, w - sol, h - alt_bosluk
    pdf.set_draw_color(*CIZGI)
    pdf.yazi(6, renk=GRI)
    for i in range(5):  # yatay ızgara + eksen etiketleri
        deger = tepe * i / 4
        yy = y + gh - gh * i / 4
        pdf.line(gx, yy, gx + gw, yy)
        pdf.set_xy(x, yy - 1.5)
        pdf.cell(sol - 2, 3, _kisa(deger), align="R")
    grup = gw / len(veri)
    cubuk = grup * 0.28
    for i, g in enumerate(veri):
        bx = gx + grup * i + grup * 0.2
        for j, (tutar, renk) in enumerate(((g["giris"], MAVI), (g["cikis"], GRI))):
            yuk = gh * tutar / tepe
            pdf.set_fill_color(*renk)
            pdf.rect(bx + j * (cubuk + 0.8), y + gh - yuk, cubuk, yuk, style="F")
        pdf.set_xy(gx + grup * i, y + gh + 1)
        pdf.yazi(6.5, True)
        pdf.cell(grup, 3.5, f"{AYLAR[int(g['ay'][5:]) - 1][:3]} {g['ay'][2:4]}", align="C")
        pdf.set_xy(gx + grup * i, y + gh + 5)
        pdf.yazi(6.2, renk=YESIL if g["net"] >= 0 else KIRMIZI)
        pdf.cell(grup, 3.5, ("+" if g["net"] > 0 else "") + _kisa(g["net"]), align="C")
    # gösterge
    pdf.set_xy(gx, y - 5)
    for ad, renk in (("Tahsilat", MAVI), ("Ödeme", GRI)):
        pdf.set_fill_color(*renk)
        pdf.rect(pdf.get_x(), pdf.get_y() + 1, 2.5, 2.5, style="F")
        pdf.set_x(pdf.get_x() + 3.5)
        pdf.yazi(6.5, renk=MURE)
        pdf.cell(16, 4.5, ad)
    pdf.yazi(6.5, renk=MURE)
    pdf.cell(0, 4.5, "Altta: aylık net (tahsilat − ödeme)")


def rapor_pdf(firma_id, ay=None, veri=None):
    """Aylık yönetici raporunu PDF baytı olarak döndürür (indirme düğmesi / e-posta eki için)."""
    v = veri or rapor_verisi(firma_id, ay)
    o, g = v["ozet"], v["saglik"]
    pdf = _Rapor(v)
    pdf.add_page()
    genislik = pdf.w - pdf.l_margin - pdf.r_margin

    # --- başlık bandı ---
    pdf.set_fill_color(*LACIVERT)
    pdf.rect(0, 0, pdf.w, 30, style="F")
    pdf.set_xy(12, 7)
    pdf.yazi(8, renk=(159, 179, 200))
    pdf.cell(0, 4, "AYLIK YÖNETİCİ RAPORU", new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(12)
    pdf.yazi(15, True, (255, 255, 255))
    pdf.cell(genislik - 50, 8, v["unvan"])
    pdf.yazi(13, True, (255, 255, 255))
    pdf.cell(50, 8, v["ay_adi"], align="R", new_x="LMARGIN", new_y="NEXT")
    f = v["firma"]
    pdf.set_x(12)
    pdf.yazi(7.5, renk=(200, 214, 229))
    meta = " · ".join(str(x) for x in [f.get("tur"), f.get("sektor"),
                                         f"Vergi No {f['vergi_no']}" if f.get("vergi_no") else None,
                                         f"{f['calisan_sayisi']} çalışan" if f.get("calisan_sayisi") else None] if x)
    pdf.cell(genislik - 60, 5, meta)
    pdf.cell(60, 5, f"Rapor tarihi {tarih_tr(v['rapor_tarihi'])} · {datetime.now():%H:%M}", align="R")
    pdf.set_y(36)

    # --- özet kartları ---
    w4 = (genislik - 9) / 4
    y = pdf.get_y()
    _kpi(pdf, 12, y, w4, f"{v['ay_adi']} tahsilat", tl(o["giris"]),
         f"Önceki aya göre {_yuzde(o['giris_degisim'], True)}")
    _kpi(pdf, 12 + (w4 + 3), y, w4, f"{v['ay_adi']} ödeme", tl(o["cikis"]),
         f"Önceki aya göre {_yuzde(o['cikis_degisim'], True)}")
    _kpi(pdf, 12 + 2 * (w4 + 3), y, w4, "Ayın neti", ("+" if o["net"] > 0 else "") + tl(o["net"]),
         f"{v['onceki_ay_adi']}: {('+' if o['onceki_net'] > 0 else '') + tl(o['onceki_net'])}",
         YESIL if o["net"] >= 0 else KIRMIZI)
    puan_renk = YESIL if g["puan"] >= 80 else MAVI if g["puan"] >= 60 else SARI if g["puan"] >= 40 else KIRMIZI
    _kpi(pdf, 12 + 3 * (w4 + 3), y, w4, "Finansal sağlık", f"{g['puan']} / 100", g["etiket"], puan_renk)
    pdf.set_y(y + 23)

    # --- uyarılar (güncel) ---
    pdf.bolum("Dikkat edilmesi gerekenler", f"Rapor tarihi ({tarih_tr(v['rapor_tarihi'])}) itibarıyla")
    for u in v["uyarilar"]:
        yy = pdf.get_y()
        pdf.set_fill_color(*SEVIYE_RENK[u["seviye"]])
        pdf.rect(12, yy + 0.8, 1.6, 7.5, style="F")
        pdf.set_xy(16, yy)
        pdf.yazi(8, True)
        pdf.cell(18, 4.5, SEVIYE_AD[u["seviye"]].upper(), new_x="RIGHT")
        pdf.cell(0, 4.5, u["baslik"], new_x="LMARGIN", new_y="NEXT")
        pdf.set_x(34)
        pdf.yazi(7, renk=MURE)
        pdf.multi_cell(genislik - 22, 3.8, u["detay"], new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1.5)

    # --- grafik + kalem dağılımı yan yana ---
    pdf.bolum(f"Son {AY_SAYISI} ay gelir ve gider", "Faturalar, net maaş, vergi/prim ve planlı kayıtlar · TL")
    y = pdf.get_y() + 5
    _grafik(pdf, v["grafik"], 12, y, genislik * 0.55, 52)
    kx = 12 + genislik * 0.6
    pdf.set_xy(kx, y - 5)
    pdf.yazi(8, True, LACIVERT)
    pdf.cell(0, 4.5, f"{v['ay_adi']} kalem dağılımı", new_x="LMARGIN", new_y="NEXT")
    pdf.set_left_margin(kx)
    pdf.set_x(kx)
    kalem_satir = [(k["ad"], _tam(k["tutar"]), _yuzde(k["pay"])) for k in v["kalemler"]]
    kalem_satir += [("Toplam tahsilat", _tam(o["giris"]), ""), ("Toplam ödeme", _tam(o["cikis"]), "")]
    n = len(v["kalemler"])
    pdf.tablo(["Kalem", "TL", "Pay"], kalem_satir or [("Bu ay hareket yok", "", "")],
              [genislik * 0.4 - 34, 20, 14], ("LEFT", "RIGHT", "RIGHT"), {n: "zemin", n + 1: "zemin"}, 7)
    pdf.set_left_margin(12)
    pdf.set_y(max(pdf.get_y(), y + 55))

    # --- müşteriler / satıcılar ---
    pdf.bolum(f"{v['ay_adi']} en büyük müşteriler ve satıcılar", "Fatura tutarına göre ilk 5")
    y = pdf.get_y()
    yarim = (genislik - 6) / 2
    for i, (baslik, liste) in enumerate((("Müşteri", v["musteriler"]), ("Satıcı", v["saticilar"]))):
        x = 12 + i * (yarim + 6)
        pdf.set_left_margin(x)
        pdf.set_xy(x, y)
        pdf.tablo([baslik, "TL", "Pay"], [(m["ad"], _tam(m["tutar"]), _yuzde(m["pay"])) for m in liste]
                  or [("Bu ay fatura yok", "", "")], [yarim - 36, 22, 14], ("LEFT", "RIGHT", "RIGHT"))
        if i == 0:
            alt_y = pdf.get_y()
    pdf.set_left_margin(12)
    pdf.set_y(max(pdf.get_y(), alt_y))

    # --- SAYFA 2: nakit akış tablosu ---
    pdf.add_page()
    pdf.bolum(f"Nakit akış tablosu · son {AY_SAYISI} ay",
              "TL, kuruşsuz · Ödemeler eksi · Kümülatif: önceki dönemlerden devir dahil birikmiş nakit")
    ay_sutun = (genislik - 52 - 22) / len(v["aylar"])
    satirlar, vurgu = [], {}
    for s in v["tablo"]:
        if s["tip"] == "baslik" or (s["tip"] == "kalem" and not any(s["degerler"].values())):
            continue  # boş planlı satırlar tabloyu uzatmasın
        if s["tip"] in ("toplam_giris", "toplam_cikis", "net", "kumulatif"):
            vurgu[len(satirlar)] = "zemin"
        satirlar.append([s["ad"]] + [_tam(s["degerler"][a]) if s["degerler"][a] else "–" for a in v["aylar"]]
                        + [_tam(s["toplam"])])
    pdf.tablo(["Kalem"] + [f"{AYLAR[int(a[5:]) - 1][:3]} {a[:4]}" for a in v["aylar"]] + ["Toplam"],
              satirlar, [52] + [ay_sutun] * len(v["aylar"]) + [22],
              ("LEFT",) + ("RIGHT",) * (len(v["aylar"]) + 1), vurgu, 7)

    # --- finansal sağlık ---
    pdf.bolum(f"Finansal sağlık puanı: {g['puan']} / 100 · {g['etiket']}",
              f"Son {g['ay_sayisi']} ayın gerçekleşen hareketlerinden · formül panelde açıktır, resmî bir "
              "derecelendirme değildir")
    for ad, p, m, ac in g["bilesenler"]:
        yy = pdf.get_y()
        pdf.set_xy(12, yy)
        pdf.yazi(7.5, True)
        pdf.cell(36, 4.5, ad)
        pdf.set_fill_color(*CIZGI)
        pdf.rect(48, yy + 1.2, 50, 2.4, style="F")
        pdf.set_fill_color(*(YESIL if p / m >= 0.8 else SARI if p / m >= 0.4 else KIRMIZI))
        pdf.rect(48, yy + 1.2, 50 * p / m, 2.4, style="F")
        pdf.set_x(100)
        pdf.yazi(7.5, True)
        pdf.cell(16, 4.5, f"{p:.1f}".replace(".", ",") + f" / {m}")
        pdf.yazi(7, renk=MURE)
        pdf.cell(0, 4.5, ac, new_x="LMARGIN", new_y="NEXT")
        pdf.ln(0.8)
    pdf.ln(1)
    pdf.yazi(7, renk=MURE)
    buyume = _yuzde(g["buyume"], True)
    pdf.multi_cell(genislik, 3.8,
                   f"Net marj {_yuzde(g['net_marj'])} · Gelir büyümesi {buyume} (son 3 tamamlanmış ay / önceki "
                   f"3 ay) · Personel gider oranı {_yuzde(g['personel_orani'])} · Vergi yükü {_yuzde(g['vergi_orani'])}"
                   f" · Birikmiş nakit {tl(g['birikmis'])}, aylık gideri "
                   + f"{g['karsilama_ay']:.1f}".replace(".", ",") + " ay karşılıyor.",
                   new_x="LMARGIN", new_y="NEXT")

    # --- SAYFA 3: borçlar ve alacaklar (sabit sayfa: içerik veriye göre uzayınca rapor kaymasın) ---
    pdf.add_page()
    pdf.bolum("Geciken ve önümüzdeki 30 günde ödenecekler",
              f"Rapor tarihi ({tarih_tr(v['rapor_tarihi'])}) itibarıyla · vergi/prim ve planlı ödemeler")
    if v["odemeler"]:
        satirlar, vurgu = [], {}
        for i, od in enumerate(v["odemeler"]):
            kalan = f"{-od['gun']} gün gecikti" if od["gun"] < 0 else "Bugün" if od["gun"] == 0 else f"{od['gun']} gün"
            if od["durum"] == "Gecikti":
                vurgu[i] = "kirmizi"
            satirlar.append((tarih_tr(od["tarih"]), od["ad"], od["aciklama"], tl(od["tutar"]), kalan))
        toplam = round(sum(od["tutar"] for od in v["odemeler"]), 2)
        vurgu[len(satirlar)] = "zemin"
        satirlar.append(("", "Toplam", "", tl(toplam), ""))
        pdf.tablo(["Son tarih", "Ödeme", "Dönem / açıklama", "Tutar", "Kalan"], satirlar,
                  [22, 52, 46, 34, genislik - 154], ("LEFT", "LEFT", "LEFT", "RIGHT", "RIGHT"), vurgu)
    else:
        pdf.yazi(8, renk=MURE)
        pdf.cell(0, 5, "Geciken ya da 30 gün içinde son tarihi gelen ödeme yok.", new_x="LMARGIN", new_y="NEXT")

    # --- açık alacaklar ---
    ao, acik = v["alacak"]["ozet"], v["alacak"]["acik"]
    ort = "—" if ao["ort_tahsil_gun"] is None else f"{ao['ort_tahsil_gun']:.0f} gün"
    pdf.bolum("Açık alacaklar (tahsil edilmemiş satış faturaları)",
              f"Rapor tarihi itibarıyla · toplam {tl(ao['acik_tutar'])}, vadesi geçen {tl(ao['vadesi_gecen_tutar'])} · "
              f"müşteriler ortalama {ort} içinde ödüyor")
    if acik:
        satirlar, vurgu = [], {}
        for i, a in enumerate(acik[:10]):  # en çok geciken 10
            g = a["gecikme_gun"]
            if g > 0:
                vurgu[i] = "kirmizi"
            satirlar.append((tarih_tr(a["vade"]), a["musteri"], a["id"], tl(a["tutar"]),
                             f"{g} gün gecikti" if g > 0 else ("Bugün" if g == 0 else f"{-g} gün")))
        if len(acik) > 10:
            satirlar.append(("", f"+{len(acik) - 10} fatura daha · tamamı panelde (Alacaklar)", "", "", ""))
        pdf.tablo(["Vade", "Müşteri", "Fatura", "Tutar", "Durum"], satirlar,
                  [22, 62, 26, 34, genislik - 144], ("LEFT", "LEFT", "LEFT", "RIGHT", "RIGHT"), vurgu)
    else:
        pdf.yazi(8, renk=MURE)
        pdf.cell(0, 5, "Tahsil edilmemiş satış faturası yok.", new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())


def dosya_adi(firma_id, ay):
    return f"aylik_rapor_{firma_id}_{ay}.pdf"
