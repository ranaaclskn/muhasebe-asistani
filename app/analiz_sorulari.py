"""Asistanın analiz soruları: finansal sağlık, cari hesaplar (müşteri/satıcı), senaryo ("ne olur?") ve uyarılar.

Panelde sekme olarak duran analizler (app/analiz.py) sohbetten de sorulabilsin diye:
  analiz_kalibi(soru)   -> soru bu türlerden biri mi? (KOD tanır; modele sorulmadan önce, bordro ve
                           "varsayım -> belge" kurallarından ÖNCE: "2 kişi işe alırsam" bordroya,
                           "satışlar düşerse ne olur" belgeye gitmesin)
  analiz_cevabi(...)    -> cevabı KOD üretir; rakamlar panelle aynı fonksiyonlardan gelir, model rakam üretmez.
Bu dosyanın üst kısmı yalnızca `re` kullanır (niyet.py'den döngüsüz içe aktarılabilsin); hesaplar fonksiyon
içinde içe aktarılır.

Kontrol (proje klasöründen):  python -m pytest -q tests/test_analiz_sorulari.py
"""
import re

SAYILAR = {"bir": 1, "iki": 2, "üç": 3, "dört": 4, "beş": 5, "altı": 6, "yedi": 7, "sekiz": 8, "dokuz": 9, "on": 10}
_SAYI = r"(\d+|bir|iki|üç|dört|beş|altı|yedi|sekiz|dokuz|on)"
# "yüksek", "eşek" gibi -sek/-sak ile biten kelimeler koşul değildir ("en yüksek maaşlı çalışan" senaryo sanılıyordu)
KOSUL = (r"\w+(?:ırsa|irse|ursa|ürse|arsa|erse)\w*|\b(?!yüksek\b|alçak\b|kısak\b)\w+(?:sam|sem|sak|sek)\b|\bolsa\b|\bsenaryo|"
         r"\bne olur\b|varsay")
# "gelir" kelime olarak ("denk gelirse" fiili senaryo değişkeni değil: "son gün tatile denk gelirse ne olur")
DEGISKEN = r"satış|ciro|\bgelir(?!se)|hasılat|maliyet|alış|tedarik|hammadde|satıcı|personel|çalışan|eleman|işçi|kişi"
ALACAK_KALIBI = (r"vadesi (?:geç|dol)\w* (?:\w+ )?(?:alacak|fatura|tahsilat)|(?:alacak|fatura)\w* vadesi (?:geç|dol)|"
                 r"tahsil edilme(?:miş|yen|di)|tahsil edeme|tahsil olma|açık (?:fatura|alacak)|ödenmemiş satış|"
                 r"(?:ödenmemiş|ödenmeyen|parası gelmeyen) fatura|parasını (?:almadı|alamadı)|ödemesini (?:almadı|alamadı)|"
                 r"kim(?:ler)? borçlu|borçlu (?:müşteri|olan)|bana borcu|borcu olan müşteri|"
                 r"alacak yaşlandır|alacak devir|ortalama tahsil|tahsil süre|tahsilat süre|"
                 r"kaç gün\w*\s+(?:içinde\s+)?tahsil|tahsil\w*\s+(?:\w+\s+)?kaç gün|ortalama\s+(?:\w+\s+){0,2}tahsil|"
                 # 'Ege Otel bize ne kadar borçlu': üçüncü kişi BORÇLU = bizim alacağımız ('borçluyum/kime borçlu' bizim borcumuz)
                 r"\b(?:bize|bana)\b.*\bborç|\bborçlu\b(?!.*\bkime\b)|"
                 # "Moda Butik'in borcu": kesme işaretli tamlayan + borcu = üçüncü kişinin bize borcu
                 r"\w+['’](?:n?[ıiuü]n) borc")
MUSTERI_ODEME = r"kaç günde|ne kadar sürede|geç öd|zamanında öd|ödemiyor|ödemeyen|ödemedi|borçlu|borcu|gecik"
# "Moda Butik'ten ne kadar alacağım var?": -den/-dan + alacak, TUTAR YOK (tutar varsa planlı tahsilat kaydıdır)
KISIDEN_ALACAK = r"\w+'?(?:ten|tan|den|dan)\s+(?:\w+\s+){0,2}(?:alacağ|alaca[kğ]ım|alacak)"


def _kucuk(metin):
    return metin.replace("İ", "i").replace("I", "ı").lower()


def _sayi(deger):
    return int(deger) if deger.isdigit() else SAYILAR.get(deger, 0)


def analiz_kalibi(soru):
    """Analiz sorusu ise niyet sözlüğü, değilse None."""
    s = _kucuk(soru)
    # SENARYO: koşul eki + iş değişkeni ("satışlar %10 düşerse", "2 kişi işe alırsam", "maliyetler artarsa")
    if re.search(KOSUL, s) and re.search(DEGISKEN, s) and not re.search(r"ödersem|ödemezsem|verirsem|vermezsem", s):
        return {"niyet": "kayit", "sorgu": "senaryo", "parametreler": [], "duzeltme": "senaryo kalıbı"}
    # FİNANSAL SAĞLIK: puan / genel durum
    if re.search(r"(?:finansal|mali)\s+(?:sağl[ıi][kğ]|durum)|sağlık puan|puanım|puanı\b|skor|nasıl gidiyor|"
                 r"\bmarj|k[aâ]r marj|k[aâ]rlılı|nakit dayanıklı|"
                 r"genel durum|şirketimin durumu|işletmemin durumu|firmamın durumu|"
                 r"(?:şirket|işletme|firma)\w*\s+(?:şu an\w*\s+)?(?:ne|nasıl)\s+durum", s):
        return {"niyet": "kayit", "sorgu": "saglik", "parametreler": [], "duzeltme": "finansal sağlık kalıbı"}
    # ALACAK (fatura alacakları): vadesi geçmiş / tahsil edilmemiş faturalar, borçlu müşteri, tahsil süresi.
    # "Alacaklarım ne kadar", "tahsilat bekliyorum" gibi genel sorular kullanıcının PLANLI tahsilatlarıdır
    # (niyet.py _planli_kalibi); burada yalnızca açıkça fatura alacağını soran kalıplar var.
    if re.search(ALACAK_KALIBI, s) or (re.search(r"müşteri", s) and re.search(MUSTERI_ODEME, s)) \
            or (re.search(KISIDEN_ALACAK, s) and not re.search(r"\d", s)):
        return {"niyet": "kayit", "sorgu": "alacak", "parametreler": [], "duzeltme": "alacak kalıbı"}
    # CARİ: en büyük müşteri / satıcı, müşteri payları, cari ekstre (tahsilat BEKLEME soruları planlı kayıttır)
    # 'En çok alım yaptığım firma': mal alımı -> satıcı cari (işe alım değil)
    if re.search(r"(?:en çok|en fazla|en büyük|kimden|hangi \w+den)\s+(?:\w+\s+)?(?:alım|alış|satın al|mal al)\w*|"
                 r"(?:alım|alış) yaptığım", s) and not re.search(r"işe|personel|eleman|çalışan", s):
        return {"niyet": "kayit", "sorgu": "cari", "parametreler": ["satici"], "duzeltme": "alım -> satıcı cari"}
    if re.search(r"müşteri|tedarikçi|satıcı|\bcari", s) and not re.search(r"tahsil|alaca[kğ]|bekliyor|bekledi", s) \
            and re.search(r"en çok|en fazla|en büyük|en az|hangi|kim|pay|ekstre|listele|sırala|dağılım|kaç|"
                          r"ne kadar|toplam|liste", s):
        tur = "satici" if re.search(r"tedarikçi|satıcı|alış yaptığım|aldığım", s) else "musteri"
        return {"niyet": "kayit", "sorgu": "cari", "parametreler": [tur], "duzeltme": "cari hesap kalıbı"}
    # "X ekstresi" / "cari hesabım": müşteri mi satıcı mı cevapta adından bulunur
    if re.search(r"\bekstre|cari hesab", s):
        return {"niyet": "kayit", "sorgu": "cari", "parametreler": ["musteri"], "duzeltme": "cari ekstre kalıbı"}
    # UYARILAR: nelere dikkat etmeliyim / riskler
    if re.search(r"uyarı|dikkat etme|neye dikkat|nelere dikkat|risk|acil|öncelik", s):
        return {"niyet": "kayit", "sorgu": "uyarilar", "parametreler": [], "duzeltme": "uyarı kalıbı"}
    return None


# ---------- Senaryo parametreleri sorudan ----------
def senaryo_parametreleri(soru):
    """'Satışlar %10 düşer ve 2 kişi işe alırsam 1 yıl sonra?' -> {"satis": -10, "alis": 0, "kisi": 2, "ay": 12}"""
    s = _kucuk(soru)
    p = {"satis": 0, "alis": 0, "kisi": 0, "ay": 6}
    for parca in re.split(r"\s+ve\s+|,|;|\s+ama\s+|\s+fakat\s+", s):
        yuzde = re.search(r"%\s*(\d+)|(\d+)\s*%|yüzde\s*(\d+)", parca)
        eksi = bool(re.search(r"düş|azal|eksil|kayb|geriler|küçül|ucuzla|ind", parca))
        arti = bool(re.search(r"art|yüksel|büyü|pahalan|zamlan|çoğal", parca))
        if yuzde and (eksi or arti):
            deger = int(next(g for g in yuzde.groups() if g)) * (-1 if eksi else 1)
            if re.search(r"maliyet|alış|tedarik|hammadde|satıcı", parca):
                p["alis"] = deger
            elif re.search(r"satış|ciro|gelir|hasılat", parca):
                p["satis"] = deger
        kisi = re.search(_SAYI + r"\s*(?:kişi|personel|çalışan|eleman|işçi)", parca)
        if kisi:
            n = _sayi(kisi.group(1))
            p["kisi"] = -n if re.search(r"çıkar|ayrıl|azalt|eksilt|işten", parca) else n
    sure = re.search(r"(\d+)\s*ay\b|(\d+)\s*aylık", s)
    if re.search(r"\b(?:1|bir)\s*(?:yıl|sene)|yıl sonra|sene sonra|yıllık", s):
        p["ay"] = 12
    elif sure:
        p["ay"] = max(1, min(24, int(next(g for g in sure.groups() if g))))
    # Panel kaydırıcılarıyla aynı sınırlar
    p["satis"], p["alis"] = max(-50, min(50, p["satis"])), max(-50, min(50, p["alis"]))
    return p


# ---------- Cevaplar ----------
def _yuzde(x):
    return f"%{x * 100:.0f}"


def _ondalik(x):
    """23.5 -> '23,5' (Türkçe ondalık virgül)."""
    return f"{x:.1f}".replace(".", ",")


def _tl(x):
    """tl() ama eksi tutarda düzgün eksi işareti: -51365.08 -> '−51.365,08 TL'."""
    from app.kayit import tl
    return ("−" + tl(abs(x))) if x < 0 else tl(x)


def _ay_adi(ay):
    from app.kayit import donem_tr
    return donem_tr(ay)


ONERI = {
    "Zamanında ödeme": "Son tarihi geçen yükümlülükleri kapatmak bu bileşeni hemen yükseltir.",
    "Kârlılık": "Gider kalemlerini (özellikle satıcı ve personel) satışla birlikte izleyin; %15 net marj hedeflenir.",
    "Gecikme": "Gecikmiş her ödeme 7 puan düşürür ve gecikme zammı işletir; önce bunları ödeyin.",
    "Müşteri dağılımı": "Satışların tek müşteride yoğunlaşması riskli; en büyük müşterinin payını %25'in altına indirmeyi hedefleyin.",
    "Nakit dayanıklılığı": "Birikmiş nakdin en az 3 aylık gideri karşılaması önerilir.",
}


def saglik_cevabi(firma_id):
    from app.analiz import gostergeler
    from app.kayit import tl
    g = gostergeler(firma_id)
    bilesenler = "\n".join(f"- {a}: **{_ondalik(p)} / {m}** — {ac}" for a, p, m, ac in g["bilesenler"])
    zayif = sorted(g["bilesenler"], key=lambda b: b[1] / b[2])[:2]
    oneriler = "\n".join(f"- **{a}** ({_ondalik(p)}/{m}): {ONERI[a]}" for a, p, m, _ in zayif)
    buyume = "—" if g["buyume"] is None else ("+" if g["buyume"] > 0 else "−") + _yuzde(abs(g["buyume"]))
    metin = (f"Finansal sağlık puanınız **{g['puan']} / 100 ({g['etiket']})**.\n\n{bilesenler}\n\n"
             f"**Göstergeler (son {g['ay_sayisi']} ay):** net marj {_yuzde(g['net_marj'])}, gelir büyümesi "
             f"{buyume}, personel gider oranı {_yuzde(g['personel_orani'])}, vergi yükü {_yuzde(g['vergi_orani'])}, "
             f"zamanında ödeme {_yuzde(g['zamaninda_oran'])}, birikmiş nakit {tl(g['birikmis'])} "
             f"({_ondalik(g['karsilama_ay'])} aylık gider).\n\n**Puanı en çok düşüren iki alan:**\n{oneriler}\n\n"
             "Bu puan kayıtlarınızdan kurallarla hesaplanan bir demo göstergedir, resmî bir derecelendirme değildir. "
             "Ayrıntılar panelin **Finansal sağlık** sekmesinde.")
    return {"cevap": metin, "kaynaklar": ["analiz: finansal sağlık"], "satirlar": [],
            "yontem": "analiz"}


def cari_cevabi(firma_id, soru, tur="musteri"):
    from app.analiz import cari_ekstre, cari_ozet
    from app.kayit import tarih_tr, tl
    kod = 58 if tur == "satici" else 10
    ad = "satıcı" if kod == 58 else "müşteri"
    s = _kucuk(soru)
    kelimeler = set(re.findall(r"[a-zçğıöşü]+", s))

    def adi_geciyor(c):  # ilk kelimesi (4+ harf) soruda geçiyor mu: "Ege Otel" -> "ege" kısa, "otel" ikinci kelime
        parca = [k for k in re.findall(r"[a-zçğıöşü]+", _kucuk(c["karsi_taraf"])) if len(k) > 3]
        return bool(parca) and parca[0] in kelimeler
    # Soruda bir carinin adı geçiyorsa o carinin ekstresi; müşteri listesinde yoksa satıcılarda da aranır
    bulunan = None
    for k in ((kod, 58 if kod == 10 else 10)):
        bulunan = next((c for c in cari_ozet(firma_id, k) if adi_geciyor(c)), None)
        if bulunan:
            kod, ad = k, ("satıcı" if k == 58 else "müşteri")
            break
    tum = cari_ozet(firma_id, kod)
    if not tum:
        return {"cevap": f"Kayıtlarınızda {ad} hareketi yok.", "kaynaklar": [], "satirlar": [], "yontem": "analiz"}
    if bulunan:
        e = cari_ekstre(firma_id, bulunan["karsi_taraf"])
        son = "\n".join(f"- {tarih_tr(x['tarih'])} · {x['islem']} · {tl(x['tutar'])}" for x in e[-3:])
        metin = (f"**{bulunan['karsi_taraf']}** ile {bulunan['adet']} işlem, toplam **{tl(bulunan['toplam'])}** "
                 f"(tüm {ad} hareketleri içindeki payı {_yuzde(bulunan['pay'])}). Ortalama fatura {tl(bulunan['ortalama'])}; ilk işlem "
                 f"{tarih_tr(bulunan['ilk'])}, son işlem {tarih_tr(bulunan['son'])}.\n\nSon işlemler:\n{son}\n\n"
                 "Tam ekstre panelin **Cari hesaplar** sekmesinde.")
        return {"cevap": metin, "kaynaklar": [x["kaynak"] for x in e], "satirlar": e, "yontem": "analiz"}
    son6 = not re.search(r"tüm|bütün|toplam|bu yıl|hepsi|şimdiye kadar", s)
    liste = cari_ozet(firma_id, kod, 6) if son6 else tum
    donem = "son 6 ayda" if son6 else "tüm kayıtlarda"
    satirlar = "\n".join(f"{i}. **{c['karsi_taraf']}** — {tl(c['toplam'])} ({_yuzde(c['pay'])}, {c['adet']} fatura)"
                         for i, c in enumerate(liste, 1))
    ilk = liste[0]
    metin = f"{donem.capitalize()} {ad} bazında dağılım:\n\n{satirlar}\n\n" \
            f"En büyük {ad}: **{ilk['karsi_taraf']}** ({_yuzde(ilk['pay'])})."
    if kod == 10 and ilk["pay"] >= 0.35:
        metin += " Satışların bu kadarının tek müşteriden gelmesi tahsilat riskini artırır."
    metin += "\n\nAyrıntılar ve cari ekstre panelin **Cari hesaplar** sekmesinde."
    return {"cevap": metin, "kaynaklar": [f"cari: {c['karsi_taraf']}" for c in liste], "satirlar": liste,
            "yontem": "analiz"}


def senaryo_cevabi(firma_id, soru):
    from app.analiz import senaryo
    from app.kayit import tl
    p = senaryo_parametreleri(soru)
    s = senaryo(firma_id, p["satis"], p["alis"], p["kisi"], p["ay"])
    son = s["aylar"][-1]
    varsayim = []
    if p["satis"]:
        varsayim.append(f"satışlar %{abs(p['satis'])} {'azalır' if p['satis'] < 0 else 'artar'}")
    if p["alis"]:
        varsayim.append(f"satıcı maliyetleri %{abs(p['alis'])} {'azalır' if p['alis'] < 0 else 'artar'}")
    if p["kisi"]:
        varsayim.append(f"{abs(p['kisi'])} kişi {'işe alınır' if p['kisi'] > 0 else 'ayrılır'} "
                        f"({s['calisan']} → {s['calisan'] + p['kisi']} çalışan)")
    if not varsayim:
        return {"cevap": ("Senaryoyu anlayamadım. Örnek: “Satışlar %10 düşerse 6 ay sonra durumum ne olur?”, "
                          "“2 kişi işe alırsam?”, “Satıcı maliyetleri %5 artarsa 1 yıl sonra?”. Panelin **Senaryo** "
                          "sekmesinde kaydırıcılarla da deneyebilirsiniz."),
                "kaynaklar": [], "satirlar": [], "yontem": "analiz"}
    fark = s["fark"]
    aylik0 = sum(r["net_mevcut"] - r["planli"] for r in s["aylar"]) / len(s["aylar"])
    aylik1 = sum(r["net_senaryo"] - r["planli"] for r in s["aylar"]) / len(s["aylar"])
    metin = (f"**Varsayım:** {', '.join(varsayim)}.\n\n"
             f"{p['ay']} ay sonra ({_ay_adi(son['ay'])}) birikmiş nakit:\n"
             f"- Mevcut gidişat: **{_tl(son['kumulatif_mevcut'])}**\n"
             f"- Senaryo: **{_tl(son['kumulatif_senaryo'])}**\n"
             f"- Fark: **{'+' if fark > 0 else ''}{_tl(fark)}**\n\n"
             f"Aylık net (planlı kayıtlar hariç): mevcut {_tl(round(aylik0, 2))}, senaryoda {_tl(round(aylik1, 2))}"
             + (" — senaryoda her ay **eksiye** düşülüyor." if aylik1 < 0 <= aylik0 else ".")
             + f"\n\nBugünkü birikmiş nakit {tl(s['birikmis'])}; taban {', '.join(_ay_adi(a) for a in s['taban_aylar'])} "
               "ortalaması. KDV satışla, SGK ve muhtasar maaşla orantılı değişir. Bu bir tahmindir; panelin "
               "**Senaryo** sekmesinde kaydırıcılarla farklı değerler deneyebilirsiniz.")
    return {"cevap": metin, "kaynaklar": ["analiz: senaryo"], "satirlar": s["aylar"], "yontem": "analiz"}


def uyari_cevabi(firma_id):
    from app.analiz import uyarilar
    etiket = {"kritik": "Acil", "uyari": "Dikkat", "bilgi": "Bilgi", "iyi": "Durum"}
    liste = uyarilar(firma_id)
    metin = "Dikkat etmeniz gerekenler (önem sırasıyla):\n\n" + "\n".join(
        f"- **{etiket[u['seviye']]}: {u['baslik']}** — {u['detay']}" for u in liste)
    return {"cevap": metin, "kaynaklar": ["analiz: uyarılar"], "satirlar": liste, "yontem": "analiz"}


def alacak_cevabi(firma_id, soru):
    """Açık alacaklar ve tahsil performansı (app/alacak.py); rakamlar paneldeki Alacaklar sekmesiyle aynı."""
    from app.alacak import acik_alacaklar, musteri_performansi, ozet
    from app.kayit import tarih_tr
    o, acik = ozet(firma_id), acik_alacaklar(firma_id)
    s = _kucuk(soru)
    # Soruda müşteri adı geçiyorsa yalnız o müşteri ("Moda Butik'ten ne kadar alacağım var?")
    musteriler = {m["musteri"] for m in musteri_performansi(firma_id)}
    adlar = [m for m in musteriler if _kucuk(m.split()[0]) in s and (len(m.split()) == 1 or
                                                                    _kucuk(m.split()[1])[:4] in s)]
    if len(adlar) == 1:
        m = adlar[0]
        mine = [a for a in acik if a["musteri"] == m]
        perf = next(x for x in musteri_performansi(firma_id) if x["musteri"] == m)
        if not mine:
            metin = f"**{m}** müşterisinden tahsil edilmemiş faturanız yok."
        else:
            gec = [a for a in mine if a["gecikme_gun"] > 0]
            metin = (f"**{m}** müşterisinden **{_tl(round(sum(a['tutar'] for a in mine), 2))}** alacağınız var "
                     f"({len(mine)} fatura" + (f", {len(gec)} tanesinin vadesi geçti" if gec else "") + "):\n\n"
                     + "\n".join(f"- {a['id']}: {_tl(a['tutar'])}, vade {tarih_tr(a['vade'])} — "
                                 + (f"{a['gecikme_gun']} gün gecikti" if a["gecikme_gun"] > 0
                                    else f"{-a['gecikme_gun']} gün kaldı") for a in mine))
        if perf["ort_tahsil_gun"] is not None:
            metin += (f"\n\n{m} faturaları ortalama {perf['ort_tahsil_gun']:.0f} günde (vadeden sonra ortalama "
                      f"{perf['ort_gecikme_gun']:.0f} gün) ödüyor.")
        return {"cevap": metin, "kaynaklar": [a["id"] for a in mine] or ["analiz: alacaklar"], "satirlar": mine,
                "yontem": "analiz"}
    ort = "—" if o["ort_tahsil_gun"] is None else f"{o['ort_tahsil_gun']:.0f} gün"
    if re.search(r"kaç gün|ne kadar süre|süre|geç öd|zamanında|ortalama", s):  # tahsil PERFORMANSI sorusu
        mp = [m for m in musteri_performansi(firma_id) if m["ort_tahsil_gun"] is not None]
        mp.sort(key=lambda m: (-m["ort_gecikme_gun"], -m["ort_tahsil_gun"]))
        metin = (f"Müşterileriniz faturayı **ortalama {ort}** içinde ödüyor. Vadesinde ya da önce tahsil edilen "
                 f"fatura oranı: %{(o['zamaninda_oran'] or 0) * 100:.0f}.\n\n"
                 "Müşteri bazında (vadeye göre en geç ödeyen başta):\n" + "\n".join(
                     f"- {m['musteri']}: vadeden sonra ortalama {m['ort_gecikme_gun']:.0f} gün "
                     f"(faturadan tahsile {m['ort_tahsil_gun']:.0f} gün)" + (f" · vadesi geçen {_tl(m['vadesi_gecen'])}"
                                                       if m["vadesi_gecen"] else "") for m in mp))
        kaynaklar = ["analiz: alacaklar"]
    else:
        gecen = [a for a in acik if a["gecikme_gun"] > 0]
        metin = (f"Tahsil edilmemiş **{o['acik_adet']} satış faturanız** var, toplam **{_tl(o['acik_tutar'])}**."
                 if acik else "Tahsil edilmemiş satış faturanız yok.")
        if gecen:
            metin += (f" Bunların {len(gecen)} tanesinin vadesi geçti ({_tl(o['vadesi_gecen_tutar'])}):\n\n"
                      + "\n".join(f"- **{a['musteri']}** · {a['id']}: {_tl(a['tutar'])}, vade {tarih_tr(a['vade'])} "
                                  f"— {a['gecikme_gun']} gün gecikti" for a in gecen)
                      + "\n\nGeciken müşterileri arayıp ödeme tarihi almanızı öneririm.")
        elif acik:
            metin += " Vadesi geçen alacak yok."
        bekleyen = [a for a in acik if a["gecikme_gun"] <= 0]
        if bekleyen:
            metin += (f"\n\nVadesi gelmemiş {len(bekleyen)} fatura ({_tl(round(sum(a['tutar'] for a in bekleyen), 2))}):\n\n"
                      + "\n".join(f"- {a['musteri']} · {a['id']}: {_tl(a['tutar'])}, vade {tarih_tr(a['vade'])} "
                                  f"({-a['gecikme_gun']} gün kaldı)" for a in sorted(bekleyen, key=lambda a: a['vade'])))
        if acik:
            metin += (f"\n\nMüşterileriniz ortalama {ort} içinde ödüyor." if o["ort_tahsil_gun"] is not None else "\n")
            metin += " Ayrıntı: panelin **Alacaklar** sekmesi."
        kaynaklar = [a["id"] for a in acik] or ["analiz: alacaklar"]
    return {"cevap": metin, "kaynaklar": kaynaklar, "satirlar": acik, "yontem": "analiz"}


def analiz_cevabi(soru, firma_id, sorgu, parametreler):
    if sorgu == "alacak":
        return alacak_cevabi(firma_id, soru)
    if sorgu == "saglik":
        return saglik_cevabi(firma_id)
    if sorgu == "cari":
        return cari_cevabi(firma_id, soru, *(parametreler or ["musteri"]))
    if sorgu == "senaryo":
        return senaryo_cevabi(firma_id, soru)
    return uyari_cevabi(firma_id)
