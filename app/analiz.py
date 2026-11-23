"""Analiz araçları: uyarılar, ödeme takvimi, yaşlandırma, cari hesaplar, finansal göstergeler ve senaryo.

Ön muhasebe programlarında (Paraşüt, Faturaport, Xero ...) yaygın panel özelliklerinin bu projedeki karşılığı.
Hepsi app/nakit.hareketler() ve yükümlülük kayıtlarından KOD ile hesaplanır; model kullanılmaz, rakam uydurulmaz.
Gösterge ve puanların formülleri açıktır (arayüzde de yazılır); resmî bir derecelendirme DEĞİLDİR.

Kontrol (proje klasöründen):  python -m pytest -q tests/test_analiz.py
"""
from datetime import date, timedelta

from app import db
from app.kayit import donem_tr, tarih_tr, tl
from app.nakit import _ay_ekle, hareketler

GERCEK_KODLAR = {10, 37, 38, 52, 53, 54, 58}  # planlı kayıtlar (19, 70) göstergelere katılmaz


def _bugun():
    return date.fromisoformat(db.BUGUN)


def _son_aylar(n):
    """Bu ay dahil son n takvim ayı."""
    bu = db.BUGUN[:7]
    return [_ay_ekle(bu, -i) for i in range(n - 1, -1, -1)]


# ---------- 1) Uyarılar ----------
def uyarilar(firma_id):
    """Panelde gösterilecek uyarılar, önem sırasıyla: [{"seviye": kritik|uyari|bilgi|iyi, "baslik", "detay"}]"""
    bugun = _bugun()
    y = db.yukumlulukler(firma_id)
    sonuc = []
    geciken = [s for s in y if s["durum"] == "Gecikti"]
    if geciken:
        sonuc.append({"seviye": "kritik", "baslik": f"{len(geciken)} gecikmiş ödeme · "
                                                    f"{tl(round(sum(s['tutar_tl'] for s in geciken), 2))}",
                      "detay": ", ".join(f"{s['tur']} ({tarih_tr(s['son_odeme_tarihi'])})" for s in geciken)
                      + " — gecikme zammı işliyor"})
    yakin = [s for s in y if s["durum"] == "Bekliyor"
             and 0 <= (date.fromisoformat(s["son_odeme_tarihi"]) - bugun).days <= 7]
    if yakin:
        sonuc.append({"seviye": "uyari", "baslik": f"7 gün içinde {len(yakin)} ödeme · "
                                                   f"{tl(round(sum(s['tutar_tl'] for s in yakin), 2))}",
                      "detay": ", ".join(f"{s['tur']} {tarih_tr(s['son_odeme_tarihi'])}" for s in
                                         sorted(yakin, key=lambda s: s["son_odeme_tarihi"]))})
    cari = cari_ozet(firma_id, 10, 6)
    if cari and cari[0]["pay"] >= 0.35:
        sonuc.append({"seviye": "uyari", "baslik": f"Satışların %{cari[0]['pay'] * 100:.0f}'i tek müşteriden",
                      "detay": f"{cari[0]['karsi_taraf']} — müşteri yoğunlaşması tahsilat riskini artırır"})
    aylar = _son_aylar(3)[:-1]  # tamamlanmış son 2 ay
    eksi = [a for a in aylar if _ay_neti(firma_id, a) < 0]
    if eksi:
        sonuc.append({"seviye": "uyari", "baslik": f"{len(eksi)} ayda gider gelirden fazla",
                      "detay": ", ".join(donem_tr(a) for a in eksi)})
    sinir = (bugun + timedelta(days=30)).isoformat()
    buyuk = [p for p in db.planli_islemler(firma_id) if p["yon"] == "Gider" and db.BUGUN <= p["tarih"] <= sinir]
    if buyuk:
        sonuc.append({"seviye": "bilgi", "baslik": f"30 gün içinde {len(buyuk)} planlı ödeme",
                      "detay": ", ".join(f"{p['aciklama']} {tl(p['tutar_tl'])} ({tarih_tr(p['tarih'])})"
                                         for p in buyuk)})
    if not sonuc:
        sonuc.append({"seviye": "iyi", "baslik": "Her şey yolunda", "detay": "Gecikmiş ya da yaklaşan ödeme yok."})
    return sonuc


def _ay_neti(firma_id, ay):
    return sum((h["tutar"] if h["yon"] == "Giriş" else -h["tutar"]) for h in hareketler(firma_id) if h["ay"] == ay)


# ---------- 2) Ödeme takvimi ----------
def takvim_olaylari(firma_idler):
    """Son ödeme günleri (vergi/prim) ve planlı kayıtlar: [{"tarih", "baslik", "tutar", "durum", "firma_id"}]"""
    olaylar = []
    for fid in firma_idler:
        for s in db.yukumlulukler(fid):
            olaylar.append({"tarih": s["son_odeme_tarihi"], "baslik": s["tur"], "tutar": s["tutar_tl"],
                            "durum": s["durum"], "firma_id": fid, "donem": donem_tr(s["donem"])})
        for p in db.planli_islemler(fid):
            olaylar.append({"tarih": p["tarih"], "baslik": p["aciklama"], "tutar": p["tutar_tl"],
                            "durum": "Tahsilat" if p["yon"] == "Gelir" else "Plan", "firma_id": fid, "donem": ""})
    return sorted(olaylar, key=lambda o: o["tarih"])


# ---------- 3) Yaşlandırma (ödenmemiş yükümlülükler) ----------
KOVALAR = ["Vadesi gelmemiş", "1–30 gün gecikmiş", "31–60 gün gecikmiş", "60+ gün gecikmiş"]


def yaslandirma(firma_id):
    """Ödenmemiş vergi/prim borçları gecikme gününe göre: {kova: {"adet", "tutar"}}"""
    bugun = _bugun()
    kovalar = {k: {"adet": 0, "tutar": 0.0} for k in KOVALAR}
    for s in db.yukumlulukler(firma_id):
        if s["durum"] == "Ödendi":
            continue
        gun = (bugun - date.fromisoformat(s["son_odeme_tarihi"])).days
        k = KOVALAR[0] if gun <= 0 else KOVALAR[1] if gun <= 30 else KOVALAR[2] if gun <= 60 else KOVALAR[3]
        kovalar[k]["adet"] += 1
        kovalar[k]["tutar"] = round(kovalar[k]["tutar"] + s["tutar_tl"], 2)
    return kovalar


# ---------- 4) Cari hesaplar ----------
def cari_ozet(firma_id, kod, son_n=None):
    """Müşteri (kod 10) ya da satıcı (kod 58) bazında toplam, pay, işlem sayısı, ortalama ve son işlem.
    son_n verilirse yalnızca bu ay dahil son n ay."""
    aylar = set(_son_aylar(son_n)) if son_n else None
    gruplar = {}
    for h in hareketler(firma_id):
        if h["kod"] != kod or (aylar and h["ay"] not in aylar):
            continue
        g = gruplar.setdefault(h["karsi_taraf"], {"karsi_taraf": h["karsi_taraf"], "toplam": 0.0, "adet": 0,
                                                   "ilk": h["tarih"], "son": h["tarih"]})
        g["toplam"] += h["tutar"]
        g["adet"] += 1
        g["son"] = max(g["son"], h["tarih"])
        g["ilk"] = min(g["ilk"], h["tarih"])
    genel = sum(g["toplam"] for g in gruplar.values()) or 1
    for g in gruplar.values():
        g["toplam"] = round(g["toplam"], 2)
        g["pay"] = g["toplam"] / genel
        g["ortalama"] = round(g["toplam"] / g["adet"], 2)
    return sorted(gruplar.values(), key=lambda g: -g["toplam"])


def cari_ekstre(firma_id, karsi_taraf):
    """Bir müşteri/satıcının tüm hareketleri, tarih sırasıyla ve yürüyen toplamla (cari hesap ekstresi)."""
    satirlar, toplam = [], 0.0
    for h in hareketler(firma_id):
        if h["karsi_taraf"] == karsi_taraf and h["kod"] in (10, 58):
            toplam += h["tutar"]
            satirlar.append({**h, "bakiye": round(toplam, 2)})
    return satirlar


# ---------- 5) Finansal göstergeler ve sağlık puanı ----------
def gostergeler(firma_id, son_n=6):
    """Son n ayın (bu ay dahil, yalnız GERÇEK hareketler) göstergeleri + 0–100 puan ve bileşenleri."""
    aylar = set(_son_aylar(son_n))
    tum = hareketler(firma_id)
    h = [x for x in tum if x["ay"] in aylar and x["kod"] in GERCEK_KODLAR]
    t = {k: sum(x["tutar"] for x in h if x["kod"] == k) for k in GERCEK_KODLAR}
    satis = t[10] or 1
    gider = sum(t[k] for k in GERCEK_KODLAR - {10})
    net = t[10] - gider
    birikmis = sum((x["tutar"] if x["yon"] == "Giriş" else -x["tutar"]) for x in tum
                   if x["kod"] in GERCEK_KODLAR and x["tarih"] <= db.BUGUN)
    aylik_gider = gider / son_n
    karsilama = birikmis / aylik_gider if aylik_gider else 0

    y = db.yukumlulukler(firma_id)
    vadesi_gecen = [s for s in y if s["son_odeme_tarihi"] < db.BUGUN]
    zamaninda = [s for s in vadesi_gecen if s["odeme_tarihi"] and s["odeme_tarihi"] <= s["son_odeme_tarihi"]]
    zamaninda_oran = len(zamaninda) / len(vadesi_gecen) if vadesi_gecen else 1.0
    geciken = sum(1 for s in y if s["durum"] == "Gecikti")
    cari = cari_ozet(firma_id, 10, son_n)
    en_buyuk_pay = cari[0]["pay"] if cari else 0
    bu_ay = db.BUGUN[:7]  # büyüme: son 3 TAMAMLANMIŞ ayın satışı / önceki 3 ay
    son3 = sum(x["tutar"] for x in tum if x["kod"] == 10 and x["ay"] in {_ay_ekle(bu_ay, -i) for i in (1, 2, 3)})
    onceki3 = sum(x["tutar"] for x in tum if x["kod"] == 10 and x["ay"] in {_ay_ekle(bu_ay, -i) for i in (4, 5, 6)})
    buyume = (son3 - onceki3) / onceki3 if onceki3 else None

    def sinirla(x):
        return max(0.0, min(1.0, x))
    bilesenler = [  # (ad, puan, en yüksek, açıklama)
        ("Zamanında ödeme", 25 * zamaninda_oran, 25, f"Son tarihi geçen yükümlülüklerde zamanında ödeme oranı "
                                                    f"%{zamaninda_oran * 100:.0f}"),
        ("Kârlılık (nakit)", 25 * sinirla(net / satis / 0.15), 25, "Net nakit marjı %15 ve üstü tam puan"),
        ("Gecikme", max(0, 20 - 7 * geciken), 20, f"{geciken} gecikmiş ödeme (her biri −7)"),
        ("Müşteri dağılımı", 15 * (1 - sinirla((en_buyuk_pay - 0.25) / 0.5)), 15,
         f"En büyük müşterinin payı %{en_buyuk_pay * 100:.0f} (%25'e kadar tam puan)"),
        ("Nakit dayanıklılığı", 15 * sinirla(karsilama / 3), 15,
         f"Birikmiş nakit {karsilama:.1f}".replace(".", ",") + " aylık gideri karşılıyor (3 ay ve üstü tam puan)"),
    ]
    puan = round(sum(b[1] for b in bilesenler))
    return {
        "satis": round(t[10], 2), "alis": round(t[58], 2), "gider": round(gider, 2), "net": round(net, 2),
        "buyume": buyume, "net_marj": net / satis,
        "personel_orani": (t[37] + t[38] + t[52]) / satis, "vergi_orani": (t[53] + t[54]) / satis,
        "zamaninda_oran": zamaninda_oran, "geciken": geciken, "birikmis": round(birikmis, 2),
        "aylik_gider": round(aylik_gider, 2), "karsilama_ay": karsilama, "en_buyuk_pay": en_buyuk_pay,
        "puan": puan, "bilesenler": [(a, round(p, 1), m, ac) for a, p, m, ac in bilesenler],
        "etiket": "Güçlü" if puan >= 80 else "İyi" if puan >= 60 else "Dikkat" if puan >= 40 else "Riskli",
        "ay_sayisi": son_n,
    }


# ---------- 6) Senaryo (ne olur?) ----------
def senaryo(firma_id, satis_yuzde=0, alis_yuzde=0, personel_degisim=0, ay_sayisi=6):
    """Son 3 TAMAMLANMIŞ ayın ortalamasıyla ileriye projeksiyon; mevcut gidişat ile senaryo yan yana.
    Varsayımlar (arayüzde de yazılır): KDV satışla, SGK ve muhtasar maaşla orantılı değişir; geçici vergi son
    6 ayın aylık ortalaması; planlı kayıtlar kendi aylarına eklenir. Rakamlar tahmindir."""
    tum = hareketler(firma_id)
    bu_ay = db.BUGUN[:7]
    taban_aylar = [_ay_ekle(bu_ay, -i) for i in (3, 2, 1)]
    ort = {k: sum(x["tutar"] for x in tum if x["kod"] == k and x["ay"] in taban_aylar) / 3 for k in GERCEK_KODLAR}
    ort[54] = sum(x["tutar"] for x in tum if x["kod"] == 54 and x["ay"] in _son_aylar(7)[:-1]) / 6
    calisan = db.firma_bilgisi(firma_id).get("calisan_sayisi") or 1
    p_kat = max(0.0, 1 + personel_degisim / calisan)
    s_kat, a_kat = 1 + satis_yuzde / 100, 1 + alis_yuzde / 100
    planli = {}
    for x in tum:
        if x["kod"] in (19, 70):
            planli[x["ay"]] = planli.get(x["ay"], 0) + (x["tutar"] if x["kod"] == 19 else -x["tutar"])
    # Başlangıç: bugüne kadar GERÇEKLEŞEN hareketlerin farkı (finansal sağlıktaki "birikmiş nakit" ile aynı tanım);
    # planlı kayıtlar yalnızca ileri aylarda, kendi aylarında eklenir.
    birikmis = sum((x["tutar"] if x["yon"] == "Giriş" else -x["tutar"]) for x in tum
                   if x["kod"] in GERCEK_KODLAR and x["tarih"] <= db.BUGUN)

    def ay_neti(senaryo_mu):
        s, a, p = (s_kat, a_kat, p_kat) if senaryo_mu else (1, 1, 1)
        gelir = ort[10] * s
        gider = ort[58] * a + (ort[37] + ort[38] + ort[52]) * p + ort[53] * s + ort[54]
        return gelir, gider

    satirlar, k_mevcut, k_senaryo = [], birikmis, birikmis
    for i in range(1, ay_sayisi + 1):
        ay = _ay_ekle(bu_ay, i)
        g0, c0 = ay_neti(False)
        g1, c1 = ay_neti(True)
        pl = planli.get(ay, 0) if ay > bu_ay else 0
        k_mevcut += g0 - c0 + pl
        k_senaryo += g1 - c1 + pl
        satirlar.append({"ay": ay, "gelir": round(g1, 2), "gider": round(c1, 2), "planli": round(pl, 2),
                         "net_mevcut": round(g0 - c0 + pl, 2), "net_senaryo": round(g1 - c1 + pl, 2),
                         "kumulatif_mevcut": round(k_mevcut, 2), "kumulatif_senaryo": round(k_senaryo, 2)})
    return {"taban_aylar": taban_aylar, "birikmis": round(birikmis, 2), "calisan": calisan, "aylar": satirlar,
            "fark": round(k_senaryo - k_mevcut, 2)}
