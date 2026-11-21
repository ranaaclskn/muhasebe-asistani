"""Kurgusal çalışan ve aylık bordro verisi üret: data/csv/calisanlar.csv + data/csv/bordrolar.csv

Kullanım (proje klasöründen):  python scripts/00_bordro_uret.py
Sonra:  python scripts/01_veritabani_kur.py  (ya da mevcut DB'de app.db tabloları kendisi ekler)
        python scripts/02_belge_uret.py      (MUHSGK beyannamelerine net ücret özeti yazılır)
        python scripts/03_indeksle.py

Rakamlar mevcut verilerle TUTARLI üretilir (deterministik, seed sabit):
- Bir ayın brüt ücret toplamı = Muhtasar / 0,15 (02_belge_uret.py'deki "Brüt ücret toplamı" ile aynı).
- Çalışan sayısı = firmalar.csv'deki calisan_sayisi.
- Gelir vergisi kesintilerinin toplamı = o ayın Muhtasar tutarı (yukumlulukler) — kuruşu kuruşuna.
- Net = Brüt − SGK işçi payı (%14) − işsizlik işçi payı (%1) − gelir vergisi − damga vergisi (%0,759).
Tüm isimler ve tutarlar KURGUSALDIR.
"""
import calendar
import csv
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import CSV_DIR  # noqa: E402

SGK_ISCI, ISSIZLIK_ISCI, GV_ORANI, DAMGA = 0.14, 0.01, 0.15, 0.00759

# İsimler: firma içinde ADLAR benzersiz olsun ki "Ayşe'ye ne kadar ödedim" tek kişiyi bulsun.
# Gündelik kelimeyle karışan adlar (Can, Gül, Barış, Umut, Deniz...) bilerek yok.
ADLAR = ["Ayşe", "Mehmet", "Fatma", "Ahmet", "Zeynep", "Mustafa", "Elif", "Emre", "Hatice", "Murat",
         "Merve", "Burak", "Esra", "Hakan", "Gizem", "Serkan", "Büşra", "Oğuz", "Selin", "Tolga",
         "Derya", "Kemal", "Sibel", "Onur", "Ebru", "Volkan", "Pınar", "Cem", "Gamze", "Erkan",
         "Melike", "Sinan", "Tuba", "Kaan", "Yasemin", "Halil", "Özge", "Levent", "Sevgi", "Taner",
         "Nermin", "Orhan", "Aslı", "Cengiz", "Filiz"]
SOYADLAR = ["Yılmaz", "Kaya", "Demir", "Şahin", "Çelik", "Yıldız", "Yıldırım", "Öztürk", "Aydın",
            "Özdemir", "Arslan", "Doğan", "Kılıç", "Aslan", "Çetin", "Koç", "Özkan", "Şimşek", "Polat",
            "Korkmaz", "Aksoy", "Tekin", "Ünal", "Erdem", "Bulut", "Karaca", "Uçar", "Avcı"]

# Sektöre göre görevler: (görev, kişi sayısı, ücret ağırlığı). Kalan kişiler son görevi alır.
GOREVLER = {
    "F001": [("Genel müdür", 1, 3.0), ("Üretim şefi", 1, 1.8), ("Muhasebe uzmanı", 1, 1.4),
             ("Kalite kontrol uzmanı", 2, 1.3), ("Satış temsilcisi", 2, 1.2), ("Depo sorumlusu", 1, 1.1),
             ("Şoför", 2, 1.0), ("Paketleme elemanı", 4, 0.85), ("Üretim operatörü", 0, 0.9)],
    "F002": [("Genel müdür", 1, 3.0), ("Yazılım ekip lideri", 3, 2.0), ("Proje yöneticisi", 2, 1.7),
             ("Kıdemli yazılım geliştirici", 8, 1.6), ("Test uzmanı", 4, 1.1), ("İnsan kaynakları uzmanı", 1, 1.1),
             ("Muhasebe uzmanı", 1, 1.1), ("Destek uzmanı", 4, 0.95), ("Yazılım geliştirici", 0, 1.2)],
    "F003": [("Atölye ustası", 2, 1.3), ("Büro elemanı", 1, 1.1), ("Ütü ve paket elemanı", 2, 0.9),
             ("Dikiş operatörü", 0, 1.0)],
}


def csv_oku(ad):
    with open(CSV_DIR / ad, encoding="utf-8") as f:
        return list(csv.DictReader(f))


def csv_yaz(ad, satirlar, alanlar):
    with open(CSV_DIR / ad, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=alanlar)
        w.writeheader()
        w.writerows(satirlar)


def gorev_listesi(firma_id, n):
    liste = []
    for gorev, adet, agirlik in GOREVLER[firma_id][:-1]:
        liste += [(gorev, agirlik)] * adet
    son_gorev, _, son_agirlik = GOREVLER[firma_id][-1]
    liste += [(son_gorev, son_agirlik)] * max(0, n - len(liste))
    return liste[:n]


def dagit(toplam, agirliklar):
    """toplam'ı ağırlıklara göre kuruş hassasiyetinde böl; yuvarlama farkı en büyük paya eklenir."""
    w = sum(agirliklar)
    paylar = [round(toplam * a / w, 2) for a in agirliklar]
    fark = round(toplam - sum(paylar), 2)
    i = paylar.index(max(paylar))
    paylar[i] = round(paylar[i] + fark, 2)
    return paylar


def uret():
    firmalar = csv_oku("firmalar.csv")
    muhtasarlar = {}  # (firma, donem) -> muhtasar tutarı
    for y in csv_oku("yukumlulukler.csv"):
        if y["tur"] == "Muhtasar":
            muhtasarlar[(y["firma_id"], y["donem"])] = float(y["tutar_tl"])

    calisanlar, bordrolar = [], []
    for f in firmalar:
        fid, n = f["id"], int(f["calisan_sayisi"])
        rnd = random.Random(f"bordro-{fid}")  # firma başına sabit seed: her çalıştırmada aynı veri
        adlar = rnd.sample(ADLAR, n)
        kisiler = []
        for (gorev, agirlik), ad in zip(gorev_listesi(fid, n), adlar):
            cid = f"C{len(calisanlar) + 1:03d}"
            giris = f"{rnd.randint(2016, 2025)}-{rnd.randint(1, 12):02d}-{rnd.randint(1, 28):02d}"
            calisanlar.append({"id": cid, "firma_id": fid, "ad_soyad": f"{ad} {rnd.choice(SOYADLAR)}",
                               "gorev": gorev, "ise_giris": giris})
            kisiler.append((cid, agirlik * rnd.uniform(0.92, 1.08)))  # aynı görevde küçük kıdem farkı

        for donem in sorted(d for (fi, d) in muhtasarlar if fi == fid):
            muhtasar = muhtasarlar[(fid, donem)]
            brut_toplam = round(muhtasar / GV_ORANI, 2)  # 02_belge_uret.py ile AYNI formül
            # Ay içi değişim (fazla mesai, prim): her ay kişi başı %±4
            brutler = dagit(brut_toplam, [w * rnd.uniform(0.96, 1.04) for _, w in kisiler])
            gvler = dagit(muhtasar, brutler)  # gelir vergisi toplamı = muhtasar (kuruşu kuruşuna)
            yil, ay = map(int, donem.split("-"))
            odeme = f"{donem}-{calendar.monthrange(yil, ay)[1]:02d}"  # maaş ay sonunda ödenir
            for (cid, _), brut, gv in zip(kisiler, brutler, gvler):
                sgk = round(brut * SGK_ISCI, 2)
                iss = round(brut * ISSIZLIK_ISCI, 2)
                damga = round(brut * DAMGA, 2)
                bordrolar.append({"id": f"BR{len(bordrolar) + 1:04d}", "firma_id": fid, "calisan_id": cid,
                                  "donem": donem, "brut_tl": brut, "sgk_isci_tl": sgk, "issizlik_isci_tl": iss,
                                  "gelir_vergisi_tl": gv, "damga_vergisi_tl": damga,
                                  "net_tl": round(brut - sgk - iss - gv - damga, 2), "odeme_tarihi": odeme})

    csv_yaz("calisanlar.csv", calisanlar, ["id", "firma_id", "ad_soyad", "gorev", "ise_giris"])
    csv_yaz("bordrolar.csv", bordrolar, ["id", "firma_id", "calisan_id", "donem", "brut_tl", "sgk_isci_tl",
                                         "issizlik_isci_tl", "gelir_vergisi_tl", "damga_vergisi_tl",
                                         "net_tl", "odeme_tarihi"])
    return firmalar, muhtasarlar, calisanlar, bordrolar


def kontrol(firmalar, muhtasarlar, calisanlar, bordrolar):
    print("\n--- KONTROL ---")
    tamam = True
    for f in firmalar:
        n = sum(c["firma_id"] == f["id"] for c in calisanlar)
        ok = n == int(f["calisan_sayisi"])
        tamam &= ok
        print("OK   " if ok else "HATA ", f"{f['id']}: {n} çalışan (beklenen {f['calisan_sayisi']})")
    for (fid, donem), muh in sorted(muhtasarlar.items()):
        satir = [b for b in bordrolar if b["firma_id"] == fid and b["donem"] == donem]
        brut = round(sum(b["brut_tl"] for b in satir), 2)
        gv = round(sum(b["gelir_vergisi_tl"] for b in satir), 2)
        ok = brut == round(muh / GV_ORANI, 2) and gv == muh
        tamam &= ok
        if not ok:
            print("HATA ", fid, donem, "brüt", brut, "gv", gv, "muhtasar", muh)
    print("OK   " if tamam else "HATA ", "her ay: brüt toplam = muhtasar/0,15 ve gelir vergisi toplamı = muhtasar")
    print("SONUÇ:", "Bordro Kontrol GEÇTİ ✅" if tamam else "Kontrol GEÇMEDİ ❌")
    return tamam


if __name__ == "__main__":
    sonuc = uret()
    print(f"{len(sonuc[2])} çalışan, {len(sonuc[3])} bordro satırı -> {CSV_DIR}")
    sys.exit(0 if kontrol(*sonuc) else 1)
