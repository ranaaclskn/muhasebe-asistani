"""Alacak takibi verisi: faturalara vade ve ödeme (satışta TAHSİL) tarihi ekler -> data/csv/faturalar.csv.

Neden? Önceden satış faturası kesildiği gün tahsil edilmiş sayılıyordu. Gerçekte müşteri vadede (15–60 gün)
ve kimi zaman geç öder, kimi fatura hiç tahsil edilmez. Bu veriyle:
  - nakit akışında satış parası TAHSİL günü girer; tahsil edilmemiş fatura vadesinde "Bekliyor/Gecikti" görünür
  - açık alacaklar, alacak yaşlandırması ve "müşteriler ortalama kaç günde ödüyor" hesaplanır (app/alacak.py)

Kurallar (KURGUSAL, sabit tohumlu: her çalıştırmada aynı sonuç):
  - Her müşterinin bir ödeme profili var: vade (gün) ve vadeden sonra gecikme aralığı (gün).
  - Tahsil tarihi = vade + gecikme. VERI_SONU'ndan sonraya düşen tahsilat "henüz yok" (boş) kalır.
  - Birkaç fatura bilerek hiç tahsil edilmemiştir (SORUNLU): yaşlandırmanın 31–60 / 60+ kovaları dolsun.
  - Veri Mayıs'ta başladığından "açılış alacakları" eklenir: Mayıs–Haziran faturalarının aynı müşterilere %95'i,
    61 gün önce (Mart–Nisan; id FA..), yalnızca Mayıs'tan sonra tahsil edilenler. Yoksa ilk aylar yapay olarak
    boş, dönem sonundaki açık alacak da nakitten düşülmüş ama başta devralınan alacak eklenmemiş olurdu.
  - Alış faturaları kesildiği gün ödenmiş sayılır (vade = ödeme = fatura tarihi; davranış değişmez).
Satır sonları (CRLF) ve sütun sırası korunur; yeni sütunlar sona eklenir.

Çalıştır (proje klasöründen):  python scripts/08_alacak_verisi.py
Sonra mevcut veritabanı kendiliğinden güncellenir (app/db.py _sema_guncelle) ya da:  python scripts/01_veritabani_kur.py
"""
import csv
import hashlib
import sys
from datetime import date, timedelta
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
DOSYA = KOK / "data" / "csv" / "faturalar.csv"
VERI_BASI = date(2026, 5, 1)    # kayıtların başladığı gün (bundan önce tahsil edilen açılış faturası tutulmaz)
VERI_SONU = date(2026, 11, 23)  # bu günden sonraki tahsilatlar henüz gerçekleşmemiştir

# müşteri -> (vade günü, en az gecikme, en çok gecikme); eksi gecikme = vadeden önce ödeme
PROFIL = {
    "Kent Market Zinciri": (30, -3, 1), "Lezzet Lokantası": (15, -2, 1), "Ege Otel Grubu": (45, 12, 30),
    "Okul Kantinleri Birliği": (30, -2, 2), "Anadolu Toptan Gıda": (60, -5, 3),
    "Kuzey Bankacılık": (30, -3, 1), "Şehir Hastanesi Bilişim": (60, 20, 40), "Delta Sigorta": (30, -3, 0),
    "Anadolu Lojistik": (45, 0, 6), "Mavi Perakende": (30, -2, 4),
    "Avrupa İhracat Ltd.": (60, -5, 2), "Kent AVM Mağazaları": (30, 8, 20), "Marmara Konfeksiyon": (30, -3, 1),
    "Moda Butik": (15, 20, 45), "Trend Giyim": (30, -2, 3),
}
SORUNLU = set()  # elle eklenecek kimlikler; ayrıca aşağıda geç ödeyen 3 müşterinin birer faturası seçilir
ACILIS_ORANI = 0.95


def _ad(karsi):
    return (karsi or "").replace(" (kurgusal)", "")


def _sabit(anahtar, alt, ust):
    """Fatura kimliğinden türetilen sabit 'rastgele' tam sayı (alt..ust)."""
    h = int(hashlib.sha256(anahtar.encode()).hexdigest()[:8], 16)
    return alt + h % (ust - alt + 1)


def _tahsil(s):
    vade_gun, alt, ust = PROFIL[_ad(s["karsi_taraf"])]
    return date.fromisoformat(s["tarih"]) + timedelta(days=vade_gun + _sabit(s["id"], alt, ust))


def main():
    with open(DOSYA, encoding="utf-8", newline="") as f:
        okuyucu = csv.DictReader(f)
        temel = [k for k in okuyucu.fieldnames if k not in ("vade_tarihi", "odeme_tarihi")]
        satirlar = [s for s in okuyucu if not s["id"].startswith("FA")]  # yeniden çalıştırılabilir

    # Açılış alacakları (Mart–Nisan): Mayıs–Haziran satışlarının aynı müşterilere %95'i, 61 gün önce.
    # Yalnızca VERI_BASI'ndan sonra tahsil edilenler tutulur: firma Mayıs'a gerçekçi bir alacak defteriyle girer
    # (45–60 gün vadeli müşterilerin Mart–Nisan faturaları Mayıs–Haziran'da tahsil edilir).
    acilis = []
    for s in sorted((s for s in satirlar if s["tip"] == "Satış" and s["tarih"][:7] in ("2026-05", "2026-06")),
                    key=lambda s: s["id"]):
        t = date.fromisoformat(s["tarih"]) - timedelta(days=61)
        acilis.append({**s, "id": "FA" + s["id"][2:], "tarih": t.isoformat(),
                       "tutar_tl": f"{float(s['tutar_tl']) * ACILIS_ORANI:.2f}"})

    # Sorunlu (hiç tahsil edilmeyen) faturalar: geç ödeyen müşterilerin Ağustos–Eylül'deki ilk faturası
    sorunlu = set(SORUNLU)
    for musteri in ("Moda Butik", "Ege Otel Grubu", "Şehir Hastanesi Bilişim"):
        aday = sorted((s for s in satirlar if s["tip"] == "Satış" and _ad(s["karsi_taraf"]) == musteri
                       and s["tarih"][:7] in ("2026-08", "2026-09")), key=lambda s: s["tarih"])
        if aday:
            sorunlu.add(aday[0]["id"])

    tahsil_edilen = acik = 0
    acilis = [s for s in acilis if _tahsil(s) >= VERI_BASI]
    for s in acilis + satirlar:
        t = date.fromisoformat(s["tarih"])
        if s["tip"] != "Satış":
            s["vade_tarihi"] = s["odeme_tarihi"] = s["tarih"]
            continue
        vade_gun, alt, ust = PROFIL[_ad(s["karsi_taraf"])]
        vade = t + timedelta(days=vade_gun)
        tahsil = vade + timedelta(days=_sabit(s["id"], alt, ust))
        s["vade_tarihi"] = vade.isoformat()
        if s["id"] in sorunlu or tahsil > VERI_SONU:
            s["odeme_tarihi"] = ""
            acik += 1
        else:
            s["odeme_tarihi"] = tahsil.isoformat()
            tahsil_edilen += 1

    sira = sorted(acilis, key=lambda s: (s["firma_id"], s["tarih"])) + satirlar
    with open(DOSYA, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=temel + ["vade_tarihi", "odeme_tarihi"], lineterminator="\r\n")
        w.writeheader()
        w.writerows(sira)
    print(f"{DOSYA.relative_to(KOK)}: {len(sira)} fatura ({len(acilis)} açılış) · satış: {tahsil_edilen} tahsil "
          f"edildi, {acik} açık (hiç tahsil edilmeyen: {', '.join(sorted(sorunlu))})")


if __name__ == "__main__":
    sys.exit(main())
