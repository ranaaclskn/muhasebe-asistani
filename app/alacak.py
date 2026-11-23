"""Alacak takibi: açık (tahsil edilmemiş) satış faturaları, alacak yaşlandırması ve tahsil performansı.

Veri: faturalar.vade_tarihi (müşterinin son ödeme günü) ve faturalar.odeme_tarihi (TAHSİL günü; boş = açık).
"Bugün" db.BUGUN'dur: tahsil günü bugünden sonra olan fatura bugün için hâlâ açıktır.
Hepsi SQL + Python ile hesaplanır; model kullanılmaz, rakam uydurulmaz.

Göstergeler:
  açık alacak          : kesilmiş ama tahsil edilmemiş satış faturalarının toplamı
  vadesi geçen         : açık alacakların vadesi geçmiş kısmı (yaşlandırma: 1–30 / 31–60 / 60+ gün)
  ortalama tahsil süresi: tahsil edilen faturalarda fatura tarihinden tahsile geçen gün (müşteri ne kadar sürede öder)
  ortalama gecikme     : tahsil edilen faturalarda vadeden sonra geçen gün (vadeden önce ödenen = 0)
  zamanında tahsil oranı: vadesinde ya da önce tahsil edilen faturaların payı
  DSO (alacak devir süresi): açık alacak / son 90 günün günlük ortalama satışı — "kaç günlük satış henüz kasada değil"

Kontrol (proje klasöründen):  python -m pytest -q tests/test_alacak.py
"""
from datetime import date, timedelta
from statistics import mean

from app import db

KOVALAR = ["Vadesi gelmemiş", "1–30 gün gecikmiş", "31–60 gün gecikmiş", "60+ gün gecikmiş"]  # analiz.KOVALAR ile aynı


def _satislar(firma_id):
    db._firma_kontrol(firma_id)
    con = db.baglan()
    try:
        return [dict(r) for r in con.execute(
            "SELECT id, karsi_taraf, tarih, tutar_tl, vade_tarihi, odeme_tarihi FROM faturalar "
            "WHERE firma_id = ? AND tip = 'Satış' AND vade_tarihi IS NOT NULL ORDER BY tarih, id", (firma_id,))]
    finally:
        con.close()


def _ad(karsi):
    return (karsi or "").replace(" (kurgusal)", "")


def _gun(a, b):
    return (date.fromisoformat(a) - date.fromisoformat(b)).days


def acik_alacaklar(firma_id):
    """Bugün itibarıyla tahsil edilmemiş satış faturaları; en çok geciken başta.
    Her satır: id, musteri, tarih, vade, tutar, gecikme_gun (vadeden bu yana; eksi = vadeye kalan gün)."""
    bugun = db.BUGUN
    satirlar = [{"id": f["id"], "musteri": _ad(f["karsi_taraf"]), "tarih": f["tarih"], "vade": f["vade_tarihi"],
                 "tutar": round(f["tutar_tl"], 2), "gecikme_gun": _gun(bugun, f["vade_tarihi"])}
                for f in _satislar(firma_id)
                if f["tarih"] <= bugun and not (f["odeme_tarihi"] and f["odeme_tarihi"] <= bugun)]
    return sorted(satirlar, key=lambda s: (-s["gecikme_gun"], s["id"]))


def kova(gecikme_gun):
    return KOVALAR[0] if gecikme_gun <= 0 else KOVALAR[1] if gecikme_gun <= 30 else \
        KOVALAR[2] if gecikme_gun <= 60 else KOVALAR[3]


def yaslandirma(firma_id):
    """{kova: {"adet", "tutar"}} — vergi/prim yaşlandırmasıyla (analiz.yaslandirma) aynı biçim."""
    kovalar = {k: {"adet": 0, "tutar": 0.0} for k in KOVALAR}
    for a in acik_alacaklar(firma_id):
        k = kovalar[kova(a["gecikme_gun"])]
        k["adet"] += 1
        k["tutar"] = round(k["tutar"] + a["tutar"], 2)
    return kovalar


def _performans(faturalar, bugun):
    tahsil = [f for f in faturalar if f["odeme_tarihi"] and f["odeme_tarihi"] <= bugun]
    if not tahsil:
        return {"tahsil_adet": 0, "ort_tahsil_gun": None, "ort_gecikme_gun": None, "zamaninda_oran": None}
    return {"tahsil_adet": len(tahsil),
            "ort_tahsil_gun": mean(_gun(f["odeme_tarihi"], f["tarih"]) for f in tahsil),
            "ort_gecikme_gun": mean(max(0, _gun(f["odeme_tarihi"], f["vade_tarihi"])) for f in tahsil),
            "zamaninda_oran": sum(1 for f in tahsil if f["odeme_tarihi"] <= f["vade_tarihi"]) / len(tahsil)}


def musteri_performansi(firma_id):
    """Müşteri bazında: fatura sayısı, satış, açık alacak, vadesi geçen, ortalama tahsil süresi/gecikme.
    En çok vadesi geçen, sonra en çok açık alacağı olan müşteri başta."""
    bugun = db.BUGUN
    acik = acik_alacaklar(firma_id)
    gruplar = {}
    for f in _satislar(firma_id):
        if f["tarih"] <= bugun:
            gruplar.setdefault(_ad(f["karsi_taraf"]), []).append(f)
    sonuc = []
    for musteri, liste in gruplar.items():
        m_acik = [a for a in acik if a["musteri"] == musteri]
        sonuc.append({"musteri": musteri, "fatura_adet": len(liste),
                      "satis": round(sum(f["tutar_tl"] for f in liste), 2),
                      "acik": round(sum(a["tutar"] for a in m_acik), 2),
                      "vadesi_gecen": round(sum(a["tutar"] for a in m_acik if a["gecikme_gun"] > 0), 2),
                      "en_uzun_gecikme": max([a["gecikme_gun"] for a in m_acik if a["gecikme_gun"] > 0], default=0),
                      **_performans(liste, bugun)})
    return sorted(sonuc, key=lambda m: (-m["vadesi_gecen"], -m["acik"], m["musteri"]))


def ozet(firma_id):
    """Panel kartları, uyarı, rapor ve asistan cevabı için tek özet."""
    bugun = db.BUGUN
    satislar = [f for f in _satislar(firma_id) if f["tarih"] <= bugun]
    acik = acik_alacaklar(firma_id)
    gecen = [a for a in acik if a["gecikme_gun"] > 0]
    toplam_acik = round(sum(a["tutar"] for a in acik), 2)
    son90 = (date.fromisoformat(bugun) - timedelta(days=90)).isoformat()
    gunluk_satis = sum(f["tutar_tl"] for f in satislar if f["tarih"] > son90) / 90
    return {"acik_adet": len(acik), "acik_tutar": toplam_acik,
            "vadesi_gecen_adet": len(gecen), "vadesi_gecen_tutar": round(sum(a["tutar"] for a in gecen), 2),
            "en_uzun_gecikme": max([a["gecikme_gun"] for a in gecen], default=0),
            "dso_gun": toplam_acik / gunluk_satis if gunluk_satis else None,
            **_performans(satislar, bugun)}
