"""Adım 4: Belgeleri parçala, embedding'e çevir ve Chroma'ya kaydet.

Kullanım (proje klasöründen):  python scripts/03_indeksle.py

Atölye karşılığı:
  d5_01_documents.py -> belgeleri_yukle()  (metadata meta.json yerine belgeler tablosundan)
  d5_02_chunks.py    -> parcala()           (200/40 TOKEN, cl100k_base, deterministik chunk_id)
  d5_04_index.py     -> indeksle()          (Chroma persist; aynı id = üzerine yazar, kopya oluşmaz)
  d5_05_search.py    -> kontrol()           (firma filtresiyle arama)
"""
import sqlite3
import sys
from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app.config import (BELGE_DIR, CHROMA_DIR, CHUNK_BOYUT, CHUNK_ORTUSME, DB_YOLU,  # noqa: E402
                        EMBED_MODEL, TOKENIZER)
from app.rag import ara, vektor_deposu  # noqa: E402

AYLAR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz",
         "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]


def belgeleri_yukle():
    """Her .txt için Document; metadata = {kaynak, firma_id, tur, donem}."""
    con = sqlite3.connect(DB_YOLU)
    satirlar = con.execute("SELECT dosya_adi, firma_id, tur, donem FROM belgeler ORDER BY id").fetchall()
    con.close()
    docs = []
    for dosya_adi, firma_id, tur, donem in satirlar:
        metin = (BELGE_DIR / dosya_adi).read_text(encoding="utf-8").strip()
        docs.append(Document(
            page_content=metin,
            # Chroma metadata'da None kabul etmez -> ortak belgelerde donem = ""
            metadata={"kaynak": dosya_adi, "firma_id": firma_id, "tur": tur, "donem": donem or ""},
        ))
    return docs


def baslik(meta):
    """Her parçanın başına eklenen kısa bağlam satırı.
    Böylece belgenin ortasından kesilen bir parça da hangi firma/dönem/tür olduğunu taşır
    (ör. 'Ödenecek KDV' satırı tek başına kalsa bile 'Eylül 2026 KDV' bilgisi kaybolmaz)."""
    donem = meta["donem"]
    if donem:
        y, a = donem.split("-")
        donem = f"{AYLAR[int(a) - 1]} {y}"
    return f"[{meta['kaynak']}] {meta['tur']} {donem}".strip()


def parcala(docs):
    # Atölye d5_02 ile aynı: boyut ve örtüşme TOKEN olarak ölçülür (karakter değil)
    splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        encoding_name=TOKENIZER, chunk_size=CHUNK_BOYUT, chunk_overlap=CHUNK_ORTUSME)
    parcalar = splitter.split_documents(docs)
    sayac = {}
    for p in parcalar:
        kaynak = p.metadata["kaynak"]
        i = sayac.get(kaynak, 0)
        p.metadata["chunk_id"] = f"{kaynak}:{i:03d}"   # deterministik id
        sayac[kaynak] = i + 1
        p.page_content = baslik(p.metadata) + "\n" + p.page_content
    return parcalar


def indeksle():
    parcalar = parcala(belgeleri_yukle())
    yeni_idler = [p.metadata["chunk_id"] for p in parcalar]
    depo = vektor_deposu()

    # Artık var olmayan eski parçaları sil (belge kısalırsa artık parça kalmasın)
    eski_idler = set(depo.get(include=[])["ids"])
    silinecek = sorted(eski_idler - set(yeni_idler))
    if silinecek:
        depo.delete(ids=silinecek)

    # Aynı id ile eklemek üzerine yazar (upsert) -> tekrar çalıştırınca kopya oluşmaz
    depo.add_documents(parcalar, ids=yeni_idler)
    return depo, parcalar, len(silinecek)


def kontrol(depo, parcalar):
    """CLAUDE.md Adım 4 Kontrol."""
    print("\n--- KONTROL ---")
    tamam = True

    kayit = len(depo.get(include=[])["ids"])
    ok = kayit == len(parcalar)
    tamam &= ok
    print("OK   " if ok else "HATA ", f"koleksiyonda {kayit} kayıt = {len(parcalar)} parça (kopya yok)")

    soru = "Eylül KDV"
    sonuc = ara(soru, "F001", k=8, depo=depo)
    print(f"\nArama: '{soru}' | firma F001 (+ORTAK) | k=8")
    for i, (doc, mesafe) in enumerate(sonuc, 1):
        print(f"  {i}. {doc.metadata['chunk_id']:<32} firma={doc.metadata['firma_id']:<5} mesafe={mesafe:.3f}")

    ilk = sonuc[0][0].metadata["kaynak"] if sonuc else None
    ok = ilk == "F001_KDV_2026-09.txt"
    tamam &= ok
    print("OK   " if ok else "HATA ", f"ilk sırada: {ilk} (beklenen F001_KDV_2026-09.txt)")

    yabanci = [d.metadata["chunk_id"] for d, _ in sonuc if d.metadata["firma_id"] not in ("F001", "ORTAK")]
    ok = not yabanci
    tamam &= ok
    print("OK   " if ok else "HATA ", "F002/F003 parçası yok" if ok else f"SIZINTI: {yabanci}")

    print("\nSONUÇ:", "Adım 4 Kontrol GEÇTİ ✅" if tamam else "Kontrol GEÇMEDİ ❌")
    print("İpucu: scripti bir kez daha çalıştır; kayıt sayısı aynı kalmalı (kopya oluşmaz).")
    return tamam


if __name__ == "__main__":
    if not DB_YOLU.exists() or not any(BELGE_DIR.glob("*.txt")):
        sys.exit("Önce: python scripts/01_veritabani_kur.py && python scripts/02_belge_uret.py")
    print(f"Embedding modeli: {EMBED_MODEL} | parça: {CHUNK_BOYUT}/{CHUNK_ORTUSME} token ({TOKENIZER})")
    print("İndeksleniyor (birkaç dakika sürebilir)...")
    depo, parcalar, silinen = indeksle()
    print(f"{len(parcalar)} parça kaydedildi -> {CHROMA_DIR}" + (f" ({silinen} eski parça silindi)" if silinen else ""))
    print("Örnek parça:", repr(parcalar[0].page_content[:150]))
    basarili = kontrol(depo, parcalar)
    sys.exit(0 if basarili else 1)
