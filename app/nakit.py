"""Nakit akış tablosu ve hareket dökümü (hocanın Excel "N.AKIŞI" ve "HAREKET" sayfalarının karşılığı).

Excel'de satırlar KODLU kalemlerdir (tahsilatlar üstte, ödemeler altta), sütunlar dönemlerdir;
HAREKET sayfası her girişi/çıkışı tek satır olarak listeler. Burada:
  hareketler(firma_id)          -> HAREKET: faturalar, maaşlar, vergi/prim ve planlı kayıtlar tek listede
  nakit_akis_tablosu(...)       -> N.AKIŞI: kod × ay matrisi, ara toplamlar, net, devir ve kümülatif
Rakamların hepsi SQL'den gelir, toplamları Python hesaplar; model kullanılmaz.
Kaynaklar gelir–gider grafiğiyle (db.aylik_gelir_gider) aynıdır: ay toplamları birebir tutar (test edilir).

Kontrol (proje klasöründen):  python -m pytest -q tests/test_nakit.py
"""
from app import db as _db  # "bugün" çağrı anında _db.BUGUN'dan okunur (testler ve analiz modülüyle aynı kaynak)
from app.db import _firma_kontrol, baglan, planli_islemler, yukumlulukler
from app.kayit import donem_tr

# Kod planı (Excel'deki KOD sayfası gibi). Tahsilat kodları 1x, ödeme kodları 3x–7x.
KODLAR = {
    10: ("Müşteri tahsilatları", "Giriş"),
    19: ("Planlı tahsilatlar", "Giriş"),
    37: ("Personel maaşları (net)", "Çıkış"),
    38: ("SGK primi", "Çıkış"),
    52: ("Muhtasar", "Çıkış"),
    53: ("KDV", "Çıkış"),
    54: ("Geçici vergi", "Çıkış"),
    58: ("Satıcılar (alış faturaları)", "Çıkış"),
    70: ("Planlı ödemeler", "Çıkış"),
}
VERGI_KODU = {"SGK primi": 38, "Muhtasar": 52, "KDV": 53, "Geçici vergi": 54}
ALT_KIRILIM = {10, 58}  # bu kodlarda her müşteri / satıcı ayrı satırda gösterilir (Excel'deki gibi)
DURUMLAR = ("Gerçekleşti", "Bekliyor", "Gecikti", "Plan")


def _hareket(tarih, kod, islem, karsi, tutar, durum, vade=None, kaynak="", belge_tarihi=None):
    """tarih/ay: paranın el değiştirdiği gün. belge_tarihi/belge_ay: işlemin doğduğu gün (satışta FATURA tarihi;
    satış hızı, büyüme ve müşteri payları buna göre hesaplanır — tahsilat gecikmesinden etkilenmesin)."""
    belge = belge_tarihi or tarih
    return {"tarih": tarih, "vade": vade or tarih, "ay": tarih[:7], "kod": kod, "kalem": KODLAR[kod][0],
            "yon": KODLAR[kod][1], "islem": islem, "karsi_taraf": karsi, "tutar": round(tutar, 2),
            "durum": durum, "kaynak": kaynak, "belge_tarihi": belge, "belge_ay": belge[:7]}


def hareketler(firma_id):
    """Firmanın tüm para giriş/çıkış hareketleri, tarih sırasıyla (HAREKET sayfası).
    Tarih = paranın girdiği/çıktığı gün: satış faturasında TAHSİL günü (tahsil edilmediyse vade günü), alış
    faturasında fatura tarihi, maaş ödeme günü, vergide ödendiyse ödeme günü, ödenmediyse son ödeme günü.
    Tahsil edilmemiş satış faturası vergi borcu gibi "Bekliyor" (vadesi gelmedi) / "Gecikti" (vadesi geçti) olur."""
    _firma_kontrol(firma_id)
    bugun = _db.BUGUN
    con = baglan()
    try:
        faturalar = con.execute("SELECT id, tip, karsi_taraf, tarih, tutar_tl, vade_tarihi, odeme_tarihi "
                                "FROM faturalar WHERE firma_id = ?", (firma_id,)).fetchall()
        maaslar = con.execute(
            "SELECT donem, MAX(odeme_tarihi) AS tarih, COUNT(*) AS kisi, SUM(net_tl) AS net FROM bordrolar "
            "WHERE firma_id = ? GROUP BY donem", (firma_id,)).fetchall()
    finally:
        con.close()

    liste = []
    for f in faturalar:
        satis = f["tip"] == "Satış"
        tarih, vade, durum = f["tarih"], f["vade_tarihi"] or f["tarih"], None
        if satis and f["vade_tarihi"]:  # alacak takibi: para tahsil günü girer
            if f["odeme_tarihi"] and f["odeme_tarihi"] <= bugun:
                tarih, durum = f["odeme_tarihi"], "Gerçekleşti"
            elif f["tarih"] > bugun:
                tarih, durum = vade, "Plan"  # henüz kesilmemiş (ileri tarihli) fatura
            else:
                tarih, durum = vade, ("Gecikti" if vade < bugun else "Bekliyor")
        liste.append(_hareket(tarih, 10 if satis else 58, f"{f['tip']} faturası {f['id']}",
                              (f["karsi_taraf"] or "").replace(" (kurgusal)", ""), f["tutar_tl"],
                              durum or ("Gerçekleşti" if f["tarih"] <= bugun else "Plan"), vade=vade, kaynak=f["id"],
                              belge_tarihi=f["tarih"]))
    for m in maaslar:
        liste.append(_hareket(m["tarih"], 37, f"{donem_tr(m['donem'])} maaş ödemesi ({m['kisi']} çalışan)",
                              "Çalışanlar", m["net"], "Gerçekleşti" if m["tarih"] <= bugun else "Plan",
                              kaynak=f"bordro {m['donem']}"))
    for y in yukumlulukler(firma_id):
        tarih = y["odeme_tarihi"] or y["son_odeme_tarihi"]
        durum = {"Ödendi": "Gerçekleşti"}.get(y["durum"], y["durum"])  # Bekliyor / Gecikti aynen kalır
        liste.append(_hareket(tarih, VERGI_KODU.get(y["tur"], 54), f"{y['tur']} · {donem_tr(y['donem'])} dönemi",
                              "SGK" if y["tur"] == "SGK primi" else "Vergi dairesi", y["tutar_tl"], durum,
                              vade=y["son_odeme_tarihi"], kaynak=y["id"]))
    for p in planli_islemler(firma_id):
        liste.append(_hareket(p["tarih"], 19 if p["yon"] == "Gelir" else 70, p["aciklama"], p["karsi_taraf"] or "—",
                              p["tutar_tl"], "Plan", kaynak=f"plan#{p['id']}"))
    return sorted(liste, key=lambda h: (h["tarih"], h["kod"]))


def _ay_ekle(ay, n):
    y, a = map(int, ay.split("-"))
    a += n
    return f"{y + (a - 1) // 12:04d}-{(a - 1) % 12 + 1:02d}"


def donem_aylari(liste, son_n=None):
    """Tablo sütunları: bu ay dahil son `son_n` takvim ayı (None = ilk hareketten itibaren) + ileri tarihli aylar.
    Arada hareketi olmayan ay da sütun olarak gösterilir (boşluk görünür olsun)."""
    if not liste:
        return []
    bu_ay = _db.BUGUN[:7]
    ilk, son = min(h["ay"] for h in liste), max(max(h["ay"] for h in liste), bu_ay)
    ay = _ay_ekle(bu_ay, -(son_n - 1)) if son_n else ilk
    aylar = []
    while ay <= son:
        aylar.append(ay)
        ay = _ay_ekle(ay, 1)
    return aylar


def nakit_akis_tablosu(liste, aylar):
    """N.AKIŞI matrisi. Döner: satır listesi; her satır {"tip", "kod", "ad", "degerler": {ay: tutar}, "toplam"}.
    tip: devir | baslik | kalem | alt (müşteri/satıcı kırılımı) | toplam_giris | toplam_cikis | net | kumulatif
    Ödemeler EKSİ işaretlidir (Excel'deki gibi). Devir = seçilen dönemden önceki tüm ayların neti."""
    if not aylar:
        return []
    secili = set(aylar)

    def topla(filtre):
        d = {ay: 0.0 for ay in aylar}
        for h in liste:
            if h["ay"] in secili and filtre(h):
                d[h["ay"]] += h["tutar"] if h["yon"] == "Giriş" else -h["tutar"]
        return {ay: round(t, 2) for ay, t in d.items()}

    def satir(tip, ad, degerler, kod=None):
        return {"tip": tip, "kod": kod, "ad": ad, "degerler": degerler, "toplam": round(sum(degerler.values()), 2)}

    onceki = round(sum((h["tutar"] if h["yon"] == "Giriş" else -h["tutar"]) for h in liste if h["ay"] < aylar[0]), 2)
    satirlar = [satir("devir", "Önceki dönemden devir (net)", {ay: (onceki if i == 0 else 0.0)
                                                                for i, ay in enumerate(aylar)})]
    for yon, baslik, toplam_tipi, toplam_adi in (("Giriş", "TAHSİLATLAR", "toplam_giris", "TOPLAM TAHSİLAT"),
                                                 ("Çıkış", "ÖDEMELER", "toplam_cikis", "TOPLAM ÖDEME")):
        satirlar.append(satir("baslik", baslik, {ay: 0.0 for ay in aylar}))
        for kod, (ad, kod_yonu) in KODLAR.items():
            if kod_yonu != yon or not any(h["kod"] == kod for h in liste):
                continue
            satirlar.append(satir("kalem", ad, topla(lambda h, k=kod: h["kod"] == k), kod))
            if kod in ALT_KIRILIM:
                for karsi in sorted({h["karsi_taraf"] for h in liste if h["kod"] == kod}):
                    satirlar.append(satir("alt", karsi, topla(lambda h, k=kod, c=karsi: h["kod"] == k
                                                              and h["karsi_taraf"] == c), kod))
        satirlar.append(satir(toplam_tipi, toplam_adi, topla(lambda h, y=yon: h["yon"] == y)))
    net = topla(lambda h: True)
    satirlar.append(satir("net", "NET NAKİT AKIŞI", net))
    kumulatif, biriken = {}, onceki
    for ay in aylar:
        biriken += net[ay]
        kumulatif[ay] = round(biriken, 2)
    k = satir("kumulatif", "Kümülatif (devir dahil)", kumulatif)
    k["toplam"] = kumulatif[aylar[-1]]  # kümülatifin "toplamı" dönem sonu bakiyesidir
    satirlar.append(k)
    return satirlar
