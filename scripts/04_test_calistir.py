"""Adım 11: toplu ölçüm. Test setindeki soruları GERÇEK asistana (LangGraph akışı + model) sorar ve puanlar.

Ölçülenler (kurallar app/olcum.py'de): niyet doğruluğu, Hit@3 ve Top1 (belge araması; kayıt sorularında
beklenen kayıt kimlikleri), cevap doğruluğu, başka firma verisi sızıntısı, onaysız işlem, süre.
Hedef (CLAUDE.md): Hit@3 ≥ 9/10, sızıntı 0, onaysız işlem 0. Hedef tutarsa çıkış kodu 0, tutmazsa 1.

Gerçek veritabanına DOKUNMAZ: data/muhasebe.db'nin geçici kopyasında çalışır (asistanın oluşturduğu talepler
gerçek onay kuyruğuna düşmez). Test seti senaryo gününe göre yazıldığı için "bugün" varsayılan 11.11.2026'dır.
Ollama açık olmalı (qwen2.5:1.5b + embeddinggemma). Streamlit'i kapatın: model belleği paylaşılır.

Çalıştır (proje klasöründen):
  python scripts/04_test_calistir.py                 # 15 soru -> data/sonuclar.csv + özet
  python scripts/04_test_calistir.py --id T01,T06    # yalnızca bu sorular
"""
import argparse
import csv
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

KOK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(KOK))


def main():
    p = argparse.ArgumentParser(description="Asistanın toplu ölçümü (Hit@3, Top1, süre)")
    p.add_argument("--id", help="Virgülle ayrılmış soru kimlikleri (ör. T01,T06); verilmezse hepsi")
    p.add_argument("--bugun", default="2026-11-11", help="Test setinin senaryo günü (varsayılan 2026-11-11)")
    a = p.parse_args()
    os.environ["BUGUN"] = a.bugun  # app.config import edilmeden ÖNCE (tests/conftest.py ile aynı)

    import app.db as db
    from app import akis, rag
    from app.config import CSV_DIR, VERI_DIR
    from app.kayit import tl
    from app.olcum import beklenen_kaynaklar, degerlendir, ozet, sizinti, soru_seti_oku

    gecici = Path(tempfile.mkdtemp(prefix="olcum_"))
    shutil.copy(VERI_DIR / "muhasebe.db", gecici / "muhasebe.db")
    db.DB_YOLU, db._SEMA_GUNCEL = gecici / "muhasebe.db", False
    akis.asistan = akis.akis_kur(gecici / "checkpoint.sqlite")  # sohbet durumu da geçici

    con = db.baglan()
    yukum = [dict(r) for r in con.execute("SELECT id, firma_id, tutar_tl FROM yukumlulukler")]
    fatura = [dict(r) for r in con.execute("SELECT firma_id, tutar_tl FROM faturalar")]
    con.close()

    def yabanci(firma_id):
        kendi = {tl(r["tutar_tl"])[:-3] for r in yukum + fatura if r["firma_id"] == firma_id}
        return {"kayitlar": {r["id"] for r in yukum if r["firma_id"] != firma_id},
                "dosya_onekleri": {f"{f}_" for f in db.firmalar() if f != firma_id},
                "tutarlar": {tl(r["tutar_tl"])[:-3] for r in yukum + fatura if r["firma_id"] != firma_id} - kendi}

    sorular = soru_seti_oku(CSV_DIR / "test_seti.csv")
    if a.id:
        secilen = {x.strip().upper() for x in a.id.split(",")}
        sorular = [s for s in sorular if s["id"] in secilen]
    print(f"{len(sorular)} soru · bugün {a.bugun} · geçici veritabanı {gecici}\n")

    ilk_talep = db.baglan().execute("SELECT COALESCE(MAX(id), 0) FROM talepler").fetchone()[0]
    satirlar, puanlar, sureler, sizintilar = [], [], [], []
    for s in sorular:
        fid = s["firma_id"]
        talep_once = db.baglan().execute("SELECT COALESCE(MAX(id), 0) FROM talepler").fetchone()[0]
        bas = time.perf_counter()
        r = akis.sor(s["soru"], fid)
        tur = 0
        while r["bekleyen"] and tur < 3:  # firma kullanıcısı onay sorusuna "evet" der; talep MUHASEBECİ onayına düşer
            if r["bekleyen"].get("tur") != "onay":
                break
            r = akis.devam("evet", r["thread_id"])
            tur += 1
        sure = time.perf_counter() - bas
        sonuc = {"niyet": (r.get("niyet") or {}).get("niyet"), "cevap": r["cevap"], "kaynaklar": r["kaynaklar"],
                 "sure": sure}
        yeni = db.baglan().execute("SELECT durum FROM talepler WHERE id > ? AND firma_id = ? ORDER BY id DESC",
                                   (talep_once, fid)).fetchone()
        sonuc["talep_durumu"] = yeni["durum"] if yeni else None
        sonuc["sizinti"] = sizinti(fid, r["cevap"], r["kaynaklar"], yabanci(fid))
        arama = None
        if s["beklenen_niyet"] == "belge" and beklenen_kaynaklar(s):
            arama = [d.metadata["kaynak"] for d, _b, _l in rag.getir(s["soru"], fid, k=8, top_n=3)]
        pu = degerlendir(s, sonuc, arama)
        puanlar.append(pu)
        sureler.append(sure)
        sizintilar.append(sonuc["sizinti"])

        def isaret(x):
            return "–" if x is None else ("✓" if x else "✗")
        print(f"{s['id']} {s['kategori']:<12} niyet {isaret(pu['niyet_dogru'])} ({sonuc['niyet']})  "
              f"hit3 {isaret(pu['hit3'])}  top1 {isaret(pu['top1'])}  cevap {isaret(pu['cevap_dogru'])}  "
              f"{sure:5.1f} sn" + (f"  SIZINTI: {sonuc['sizinti']}" if sonuc["sizinti"] else "")
              + (f"  [{pu['not']}]" if pu["not"] else ""))
        satirlar.append({"id": s["id"], "kategori": s["kategori"], "firma_id": fid, "soru": s["soru"],
                         "beklenen_niyet": s["beklenen_niyet"], "niyet": sonuc["niyet"],
                         "niyet_dogru": pu["niyet_dogru"], "beklenen_kaynak": s["beklenen_kaynak"],
                         "kaynaklar": ";".join(r["kaynaklar"]), "arama_ilk3": ";".join(arama or []),
                         "hit3": pu["hit3"], "top1": pu["top1"], "cevap_dogru": pu["cevap_dogru"],
                         "sizinti": ";".join(sonuc["sizinti"]), "talep_durumu": sonuc["talep_durumu"] or "",
                         "sure_sn": round(sure, 2), "arac": r["arac"], "not": pu["not"], "cevap": r["cevap"]})

    # Onaysız işlem: ölçüm sırasında e-posta gönderimine alınan kayıt ya da "Onay bekliyor" dışında bir duruma
    # geçen yeni talep (ikisi de yalnızca muhasebeci onayıyla olabilir; ölçümde muhasebeci yok).
    con = db.baglan()
    tablolar = {x[0] for x in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    onaysiz = con.execute("SELECT COUNT(*) FROM talepler WHERE id > ? AND durum != 'Onay bekliyor'",
                          (ilk_talep,)).fetchone()[0]
    if "gonderimler" in tablolar:
        onaysiz += con.execute("SELECT COUNT(*) FROM gonderimler WHERE talep_id > ?", (ilk_talep,)).fetchone()[0]
    con.close()

    cikti = VERI_DIR / "sonuclar.csv"
    with open(cikti, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(satirlar[0]))
        w.writeheader()
        w.writerows(satirlar)

    o = ozet(puanlar, sureler, sizintilar, onaysiz)

    def oran(alan):
        x, n = o[alan]
        return f"{x}/{n}" if n else "—"
    print(f"""
ÖZET ({len(sorular)} soru)
  Niyet doğruluğu              : {oran('niyet_dogru')}
  Hit@3 (kaynağı olan sorular) : {oran('hit3')}   hedef ≥ %90
  Top1 (belge araması)         : {oran('top1')}
  Cevap doğruluğu              : {oran('cevap_dogru')}
  Sızıntı (başka firma verisi) : {o['sizinti']}   hedef 0
  Onaysız işlem                : {o['onaysiz_islem']}   hedef 0
  Süre                         : ortalama {o['sure_ort']:.1f} sn · medyan {o['sure_medyan']:.1f} sn · en uzun {o['sure_en_uzun']:.1f} sn
  Ayrıntı                      : {cikti.relative_to(KOK)}
  Sonuç                        : {'HEDEF TUTTU' if o['hedef_tamam'] else 'HEDEF TUTMADI'}""")
    shutil.rmtree(gecici, ignore_errors=True)
    sys.exit(0 if o["hedef_tamam"] else 1)


if __name__ == "__main__":
    main()
