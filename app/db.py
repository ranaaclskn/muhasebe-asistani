"""Veritabanı katmanı: hazır SQL sorguları (SORGULAR), calistir(), talep_ekle().

Kural 3 — Serbest SQL yok: Model SQL YAZMAZ. Yalnızca SORGULAR'dan bir sorgu ADI ve
parametre değerleri seçer. Ad listede yoksa reddedilir.
Kural 2 — firma_id her zaman KODDAN (oturumdan) gelir, modelden değil; her sorguda zorunlu.

Kontrol (proje klasöründen):  python -m app.db
"""
import json
import re
import sqlite3
from datetime import datetime, timedelta
from functools import cache

import bcrypt

from app.config import BUGUN, DB_YOLU

# Her sorgu: açıklama (niyet prompt'unda modele gösterilecek), modelin vereceği parametre
# adları ve SQL. :firma_id ve :bugun'u KOD ekler; model bunları hiçbir zaman vermez.
SORGULAR = {
    "durum": {
        "aciklama": "Belirli bir türün belirli bir dönemdeki tutarı, son tarihi, ödenip ödenmediği",
        "parametreler": ["tur", "donem"],
        "sql": """SELECT id, tur, donem, tutar_tl, son_odeme_tarihi, durum, odeme_tarihi
                  FROM yukumlulukler
                  WHERE firma_id = :firma_id AND tur = :tur AND donem = :donem""",
    },
    "ay_odemeleri": {
        "aciklama": "Bir ay içinde son tarihi olan ödenmemiş ödemeler (bu ay ne ödeyeceğim, toplam); "
                    "tür söylenirse yalnızca o tür",
        "parametreler": ["ay"],  # ör. "2026-11"
        "istege_bagli": ["tur"],  # verilmezse tüm türler
        "sql": """SELECT id, tur, donem, tutar_tl, son_odeme_tarihi, durum
                  FROM yukumlulukler
                  WHERE firma_id = :firma_id AND substr(son_odeme_tarihi, 1, 7) = :ay
                        AND durum != 'Ödendi' AND (:tur IS NULL OR tur = :tur)
                  ORDER BY son_odeme_tarihi""",
    },
    "odenenler": {
        "aciklama": "Bir ay içinde ÖDENMİŞ ödemeler (ekim ayında ne ödedim, geçen ay ödenen KDV); "
                    "tür söylenirse yalnızca o tür",
        "parametreler": ["ay"],  # ödeme tarihinin ayı, ör. "2026-10"
        "istege_bagli": ["tur"],
        "sql": """SELECT id, tur, donem, tutar_tl, son_odeme_tarihi, durum, odeme_tarihi
                  FROM yukumlulukler
                  WHERE firma_id = :firma_id AND durum = 'Ödendi'
                        AND substr(odeme_tarihi, 1, 7) = :ay AND (:tur IS NULL OR tur = :tur)
                  ORDER BY odeme_tarihi""",
    },
    "yil_odenenler": {
        "aciklama": "Bir YIL içinde ödenmiş ödemeler ve toplamı (bu yıl ne kadar ödedim, 2026'da ödenen KDV); "
                    "tür söylenirse yalnızca o tür",
        "parametreler": ["yil"],  # ödeme tarihinin yılı, ör. "2026"
        "istege_bagli": ["tur"],
        "sql": """SELECT id, tur, donem, tutar_tl, son_odeme_tarihi, durum, odeme_tarihi
                  FROM yukumlulukler
                  WHERE firma_id = :firma_id AND durum = 'Ödendi'
                        AND substr(odeme_tarihi, 1, 4) = :yil AND (:tur IS NULL OR tur = :tur)
                  ORDER BY odeme_tarihi""",
    },
    "odeme_araligi": {
        "aciklama": "İki ay arasında (dahil) ödenmiş ödemeler ve toplamı (son 3 ayda ne ödedim, "
                    "son 6 ayda ödenen KDV); tür söylenirse yalnızca o tür",
        "parametreler": ["baslangic_ay", "bitis_ay"],  # ör. "2026-08", "2026-10"
        "istege_bagli": ["tur"],
        "sql": """SELECT id, tur, donem, tutar_tl, son_odeme_tarihi, durum, odeme_tarihi
                  FROM yukumlulukler
                  WHERE firma_id = :firma_id AND durum = 'Ödendi'
                        AND substr(odeme_tarihi, 1, 7) BETWEEN :baslangic_ay AND :bitis_ay
                        AND (:tur IS NULL OR tur = :tur)
                  ORDER BY odeme_tarihi""",
    },
    "firma_bilgisi": {
        "aciklama": "Firmanın kendi bilgileri: çalışan sayısı, sektör, firma türü, vergi no, unvan",
        "parametreler": [],
        "sql": """SELECT id, unvan, tur AS firma_turu, vergi_no, sektor, calisan_sayisi
                  FROM firmalar WHERE id = :firma_id""",
    },
    # --- Kullanıcının KENDİ eklediği planlı kayıtlar (planli_islemler tablosu) ---
    # Ay verilmezse bugünden sonraki kayıtlar gelir; verilirse o ayın kayıtları.
    "planli_odemeler": {
        "aciklama": "Kullanıcının kendi eklediği PLANLI ÖDEMELER (kira, tedarikçi vb. yapılacak ödemeler); "
                    "ay söylenirse o ay, söylenmezse yaklaşanlar",
        "parametreler": [],
        "istege_bagli": ["ay"],
        "sql": """SELECT id, yon, tarih, tutar_tl, aciklama, karsi_taraf FROM planli_islemler
                  WHERE firma_id = :firma_id AND yon = 'Gider'
                        AND ((:ay IS NULL AND tarih >= :bugun) OR substr(tarih, 1, 7) = :ay)
                  ORDER BY tarih""",
    },
    "beklenen_tahsilatlar": {
        "aciklama": "Kullanıcının kendi eklediği BEKLENEN TAHSİLATLAR (müşteriden gelecek ödemeler, alacaklar); "
                    "ay söylenirse o ay, söylenmezse yaklaşanlar",
        "parametreler": [],
        "istege_bagli": ["ay"],
        "sql": """SELECT id, yon, tarih, tutar_tl, aciklama, karsi_taraf FROM planli_islemler
                  WHERE firma_id = :firma_id AND yon = 'Gelir'
                        AND ((:ay IS NULL AND tarih >= :bugun) OR substr(tarih, 1, 7) = :ay)
                  ORDER BY tarih""",
    },
    "nakit_plani": {
        "aciklama": "Kullanıcının planlı ödemeleri VE beklenen tahsilatları birlikte, giriş-çıkış ve net "
                    "(nakit planı, para giriş çıkışı); ay söylenirse o ay, söylenmezse yaklaşanlar",
        "parametreler": [],
        "istege_bagli": ["ay"],
        "sql": """SELECT id, yon, tarih, tutar_tl, aciklama, karsi_taraf FROM planli_islemler
                  WHERE firma_id = :firma_id
                        AND ((:ay IS NULL AND tarih >= :bugun) OR substr(tarih, 1, 7) = :ay)
                  ORDER BY tarih""",
    },
    "gecikmis": {
        "aciklama": "Son tarihi geçmiş ve ödenmemiş (gecikmiş) ödemeler",
        "parametreler": [],
        "sql": """SELECT id, tur, donem, tutar_tl, son_odeme_tarihi, durum
                  FROM yukumlulukler
                  WHERE firma_id = :firma_id
                        AND (durum = 'Gecikti' OR (durum = 'Bekliyor' AND son_odeme_tarihi < :bugun))
                  ORDER BY son_odeme_tarihi""",
    },
    "gec_odenenler": {  # 'gecikmis' ŞU ANKİ ödenmemiş borçtur; bu ise GEÇMİŞTE geç ÖDENMİŞ kayıtlardır
        "aciklama": "Geçmişte son ödeme tarihinden SONRA (geç) ödenmiş ödemeler (gecikmiş ödediğim, geç ödenenler)",
        "parametreler": [],
        "sql": """SELECT id, tur, donem, tutar_tl, son_odeme_tarihi, durum, odeme_tarihi
                  FROM yukumlulukler
                  WHERE firma_id = :firma_id AND durum = 'Ödendi' AND odeme_tarihi > son_odeme_tarihi
                  ORDER BY odeme_tarihi DESC""",
    },
    # "KDV'mi en geç ne zaman ödemeliyim" -> o türün ödenmemiş (bekleyen ya da gecikmiş) en eski kaydı.
    # Model bunu ödeme GEÇMİŞİNE gönderiyordu; kalıbı kod tanır (niyet._son_tarih_kalibi).
    "siradaki_tur": {
        "aciklama": "Bir türün ödenmemiş en yakın kaydı ve son ödeme tarihi (KDV'mi en geç ne zaman ödemeliyim)",
        "parametreler": ["tur"],
        "menude_yok": True,
        "sql": """SELECT id, tur, donem, tutar_tl, son_odeme_tarihi, durum
                  FROM yukumlulukler
                  WHERE firma_id = :firma_id AND tur = :tur AND durum != 'Ödendi'
                  ORDER BY son_odeme_tarihi, id
                  LIMIT 1""",
    },
    "en_yakin": {
        "aciklama": "Bugünden sonraki en yakın son ödeme tarihi olan ödenmemiş ödeme",
        "parametreler": [],
        "sql": """SELECT id, tur, donem, tutar_tl, son_odeme_tarihi, durum
                  FROM yukumlulukler
                  WHERE firma_id = :firma_id AND durum != 'Ödendi' AND son_odeme_tarihi >= :bugun
                  ORDER BY son_odeme_tarihi, id
                  LIMIT 1""",
    },
    # --- Çalışanlar ve bordro (kurgusal). Modelin menüsünde YOK: soruyu app/bordro.py kodla tanır,
    # çalışanı isimden kod bulur (calisan_id modelden gelmez), hesapları Python yapar. ---
    "calisan_listesi": {
        "aciklama": "Firmanın çalışanları: ad soyad, görev, işe giriş",
        "parametreler": [],
        "menude_yok": True,
        "sql": """SELECT id, ad_soyad, gorev, ise_giris FROM calisanlar
                  WHERE firma_id = :firma_id ORDER BY id""",
    },
    "calisan_bordrosu": {
        "aciklama": "Bir çalışanın aylık brüt, kesinti ve net ücretleri",
        "parametreler": ["calisan_id"],
        "menude_yok": True,
        "sql": """SELECT b.*, c.ad_soyad, c.gorev FROM bordrolar b JOIN calisanlar c ON c.id = b.calisan_id
                  WHERE b.firma_id = :firma_id AND b.calisan_id = :calisan_id
                  ORDER BY b.donem""",
    },
    "ay_bordrosu": {
        "aciklama": "Bir ayda her çalışana ödenen brüt / net ücret (en yüksek netten başlayarak)",
        "parametreler": ["ay"],
        "menude_yok": True,
        "sql": """SELECT b.*, c.ad_soyad, c.gorev FROM bordrolar b JOIN calisanlar c ON c.id = b.calisan_id
                  WHERE b.firma_id = :firma_id AND b.donem = :ay
                  ORDER BY b.net_tl DESC""",
    },
    "bordro_aylik_toplam": {
        "aciklama": "Her ay çalışanlara ödenen toplam brüt, kesintiler ve net",
        "parametreler": [],
        "menude_yok": True,
        "sql": """SELECT donem, COUNT(*) AS kisi, ROUND(SUM(brut_tl), 2) AS brut_tl,
                         ROUND(SUM(sgk_isci_tl), 2) AS sgk_isci_tl, ROUND(SUM(issizlik_isci_tl), 2) AS issizlik_isci_tl,
                         ROUND(SUM(gelir_vergisi_tl), 2) AS gelir_vergisi_tl,
                         ROUND(SUM(damga_vergisi_tl), 2) AS damga_vergisi_tl, ROUND(SUM(net_tl), 2) AS net_tl,
                         MAX(odeme_tarihi) AS odeme_tarihi
                  FROM bordrolar WHERE firma_id = :firma_id
                  GROUP BY donem ORDER BY donem""",
    },
    "yaklasanlar": {
        "aciklama": "Bugünden sonraki ödenmemiş ödemeler, en yakından başlayarak (en yakın 3 / 5 ödeme)",
        "parametreler": [],
        "istege_bagli": ["adet"],  # kaç kayıt istendi; verilmezse 5
        "sql": """SELECT id, tur, donem, tutar_tl, son_odeme_tarihi, durum
                  FROM yukumlulukler
                  WHERE firma_id = :firma_id AND durum != 'Ödendi' AND son_odeme_tarihi >= :bugun
                  ORDER BY son_odeme_tarihi, id
                  LIMIT CAST(coalesce(:adet, 5) AS INTEGER)""",
    },
    # Tahmin için: bir türün SON dönemlerinin tutarları (durum fark etmez). Modelin menüsünde
    # görünmez; yalnızca kod kullanır (kayit.tahmin_cevabi).
    "donem_gecmisi": {
        "aciklama": "Bir türün son 3 dönemdeki tutarları (tahmin için)",
        "parametreler": ["tur"],
        "menude_yok": True,
        "sql": """SELECT id, tur, donem, tutar_tl, son_odeme_tarihi, durum
                  FROM yukumlulukler
                  WHERE firma_id = :firma_id AND tur = :tur
                  ORDER BY donem DESC
                  LIMIT 3""",
    },
    "odeme_gecmisi": {
        "aciklama": "Bir türün geçmiş ödemeleri, ne zaman ve ne kadar ödendiği (son 6 kayıt)",
        "parametreler": ["tur"],
        "sql": """SELECT id, tur, donem, tutar_tl, son_odeme_tarihi, durum, odeme_tarihi
                  FROM yukumlulukler
                  WHERE firma_id = :firma_id AND tur = :tur AND durum = 'Ödendi'
                  ORDER BY son_odeme_tarihi DESC
                  LIMIT 6""",
    },
    "faturalar": {
        "aciklama": "Bir aydaki alış/satış faturaları",
        "parametreler": ["ay"],  # ör. "2026-10"
        "sql": """SELECT id, tip, karsi_taraf, tarih, tutar_tl, kdv_orani
                  FROM faturalar
                  WHERE firma_id = :firma_id AND substr(tarih, 1, 7) = :ay
                  ORDER BY tarih""",
    },
}

# ETKİN DURUM: veritabanındaki durum sabittir ('Bekliyor'), ama son ödeme tarihi BUGÜNDEN önceyse ve
# ödenmemişse kayıt fiilen GECİKMİŞTİR. Her yükümlülük sorgusu durumu bugüne göre hesaplar; böylece
# 17.11'de son günü geçen geçici vergi 21.11'de "ödenecekler / yaklaşanlar" arasında "Bekliyor" görünmez.
DURUM_SQL = ("CASE WHEN durum != 'Ödendi' AND son_odeme_tarihi < :bugun THEN 'Gecikti' "
             "ELSE durum END AS durum")
for _s in SORGULAR.values():
    if "FROM yukumlulukler" in _s["sql"]:
        _s["sql"] = _s["sql"].replace("son_odeme_tarihi, durum", "son_odeme_tarihi, " + DURUM_SQL)

# DB'deki tür adları birebir bu dört değer (CLAUDE.md §8). Model/ kullanıcı farklı yazarsa eşle.
TURLER = ["KDV", "Muhtasar", "SGK primi", "Geçici vergi"]
_TUR_ESLEME = {
    "kdv": "KDV", "katma değer vergisi": "KDV",
    "muhtasar": "Muhtasar", "stopaj": "Muhtasar",
    "sgk": "SGK primi", "sgk primi": "SGK primi", "sigorta primi": "SGK primi", "prim": "SGK primi",
    "geçici vergi": "Geçici vergi", "gecici vergi": "Geçici vergi", "geçici": "Geçici vergi",
}


def tur_normalize(metin):
    """'sgk' / 'SGK Primi' / 'sigorta primi' -> 'SGK primi'. Tanınmazsa None."""
    if metin in TURLER:
        return metin
    anahtar = str(metin).replace("İ", "i").replace("I", "ı").lower().strip()
    return _TUR_ESLEME.get(anahtar)


_SEMA_GUNCEL = False

# Kullanıcının kendi girdiği planlı ödeme/tahsilatlar. Muhasebecinin resmî kayıtlarından
# (yukumlulukler) AYRI tutulur: "bu ay ne kadar vergi ödeyeceğim" hâlâ yalnız resmî kayıtlardan gelir.
PLANLI_ISLEMLER_SEMA = """
CREATE TABLE IF NOT EXISTS planli_islemler (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    firma_id TEXT NOT NULL,
    yon TEXT NOT NULL CHECK (yon IN ('Gider', 'Gelir')),   -- Gider: ödeyeceğim, Gelir: tahsil edeceğim
    tarih TEXT NOT NULL,                                     -- YYYY-AA-GG
    tutar_tl REAL NOT NULL CHECK (tutar_tl > 0),
    aciklama TEXT NOT NULL,
    karsi_taraf TEXT,
    ekleyen_id INTEGER,
    olusturma TEXT
);
CREATE INDEX IF NOT EXISTS ix_planli_firma ON planli_islemler(firma_id, tarih);
"""


# Kurgusal çalışanlar ve aylık bordro (scripts/00_bordro_uret.py üretir). Resmî kayıt gibi salt okunur:
# asistan bunları yalnızca SORGULAR'daki hazır sorgularla okur.
BORDRO_SEMA = """
CREATE TABLE IF NOT EXISTS calisanlar (
    id TEXT PRIMARY KEY,
    firma_id TEXT NOT NULL,
    ad_soyad TEXT NOT NULL,
    gorev TEXT,
    ise_giris TEXT
);
CREATE TABLE IF NOT EXISTS bordrolar (
    id TEXT PRIMARY KEY,
    firma_id TEXT NOT NULL,
    calisan_id TEXT NOT NULL REFERENCES calisanlar(id),
    donem TEXT NOT NULL,                 -- YYYY-AA
    brut_tl REAL NOT NULL,
    sgk_isci_tl REAL NOT NULL,           -- SGK işçi payı (%14)
    issizlik_isci_tl REAL NOT NULL,      -- işsizlik sigortası işçi payı (%1)
    gelir_vergisi_tl REAL NOT NULL,      -- toplamı o ayın muhtasar tutarına eşit
    damga_vergisi_tl REAL NOT NULL,
    net_tl REAL NOT NULL,                -- çalışanın eline geçen
    odeme_tarihi TEXT
);
CREATE INDEX IF NOT EXISTS ix_bordro_firma ON bordrolar(firma_id, donem);
CREATE INDEX IF NOT EXISTS ix_calisan_firma ON calisanlar(firma_id);
"""
_BORDRO_KOLONLARI = {
    "calisanlar": ["id", "firma_id", "ad_soyad", "gorev", "ise_giris"],
    "bordrolar": ["id", "firma_id", "calisan_id", "donem", "brut_tl", "sgk_isci_tl", "issizlik_isci_tl",
                  "gelir_vergisi_tl", "damga_vergisi_tl", "net_tl", "odeme_tarihi"],
}


def bordro_tablolari_kur(con):
    """Tabloları oluştur; boşlarsa data/csv/calisanlar.csv + bordrolar.csv'den doldur (CSV yoksa boş kalır)."""
    import csv
    from app.config import CSV_DIR
    con.executescript(BORDRO_SEMA)
    for tablo, kolonlar in _BORDRO_KOLONLARI.items():
        yol = CSV_DIR / f"{tablo}.csv"
        if not yol.exists() or con.execute(f"SELECT COUNT(*) FROM {tablo}").fetchone()[0]:
            continue
        with open(yol, encoding="utf-8", newline="") as f:
            satirlar = [tuple(s[k] for k in kolonlar) for s in csv.DictReader(f)]
        con.executemany(f"INSERT INTO {tablo} ({', '.join(kolonlar)}) VALUES "
                        f"({', '.join('?' for _ in kolonlar)})", satirlar)


def _sema_guncelle(con):
    """Eski veritabanlarına yeni talep kolonlarını ekle (01'i yeniden çalıştırmadan, veri kaybetmeden)."""
    global _SEMA_GUNCEL
    mevcut = {r[1] for r in con.execute("PRAGMA table_info(talepler)")}
    for kolon in ("emir", "detay", "ozet"):
        if mevcut and kolon not in mevcut:
            con.execute(f"ALTER TABLE talepler ADD COLUMN {kolon} TEXT NULL")
    if mevcut:  # yalnızca kurulmuş bir veritabanında (01 çalıştıysa) yeni tabloları ekle
        con.executescript(PLANLI_ISLEMLER_SEMA)
        bordro_tablolari_kur(con)
        fatura_vadelerini_guncelle(con)
    con.commit()
    _SEMA_GUNCEL = True


def fatura_vadelerini_guncelle(con):
    """Alacak takibi: faturalara vade_tarihi ve odeme_tarihi (satışta TAHSİL günü) kolonları. Eski veritabanında
    kolonlar yoksa eklenir ve data/csv/faturalar.csv'den doldurulur; CSV'deki yeni (açılış) faturalar da eklenir.
    Kolonlar zaten varsa hiçbir şey yapılmaz (kullanıcının verisi ezilmez). Veri: scripts/08_alacak_verisi.py"""
    import csv
    from app.config import CSV_DIR
    kolonlar = {r[1] for r in con.execute("PRAGMA table_info(faturalar)")}
    if not kolonlar or {"vade_tarihi", "odeme_tarihi"} <= kolonlar:
        return
    for kolon in ("vade_tarihi", "odeme_tarihi"):
        if kolon not in kolonlar:
            con.execute(f"ALTER TABLE faturalar ADD COLUMN {kolon} TEXT NULL")
    yol = CSV_DIR / "faturalar.csv"
    if not yol.exists():
        return
    with open(yol, encoding="utf-8", newline="") as f:
        satirlar = list(csv.DictReader(f))
    if "vade_tarihi" not in (satirlar[0] if satirlar else {}):
        return
    for s in satirlar:
        con.execute("INSERT OR IGNORE INTO faturalar (id, firma_id, tip, karsi_taraf, tarih, tutar_tl, kdv_orani) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)", (s["id"], s["firma_id"], s["tip"], s["karsi_taraf"], s["tarih"],
                                                    float(s["tutar_tl"]), float(s["kdv_orani"] or 0)))
        con.execute("UPDATE faturalar SET vade_tarihi = ?, odeme_tarihi = ? WHERE id = ?",
                    (s["vade_tarihi"] or None, s["odeme_tarihi"] or None, s["id"]))


def baglan():
    con = sqlite3.connect(DB_YOLU)
    con.row_factory = sqlite3.Row
    if not _SEMA_GUNCEL:
        _sema_guncelle(con)
    return con


def _firma_kontrol(firma_id):
    if not isinstance(firma_id, str) or not re.fullmatch(r"F\d{3}", firma_id):
        raise ValueError(f"Geçersiz firma_id: {firma_id!r}")


def calistir(sorgu_adi, firma_id, *parametreler):
    """SORGULAR'daki hazır sorguyu çalıştır; satırları sözlük listesi olarak döndür.

    calistir("ay_odemeleri", "F001", "2026-11")
    calistir("durum", "F001", "SGK primi", "2026-10")
    """
    if sorgu_adi not in SORGULAR:  # Kural 3: listede olmayan sorgu reddedilir
        raise ValueError(f"İzin verilmeyen sorgu: {sorgu_adi!r}")
    _firma_kontrol(firma_id)
    sorgu = SORGULAR[sorgu_adi]
    adlar = sorgu["parametreler"]
    ek = sorgu.get("istege_bagli", [])
    if not len(adlar) <= len(parametreler) <= len(adlar) + len(ek):
        raise ValueError(f"{sorgu_adi} {len(adlar)} parametre bekler {adlar}"
                         + (f" (+ isteğe bağlı {ek})" if ek else "") + f", {len(parametreler)} geldi")

    degerler = dict(zip(adlar + ek, parametreler))
    for ad in ek:
        degerler.setdefault(ad, None)  # isteğe bağlı verilmediyse filtre uygulanmaz
    if degerler.get("tur") is not None:
        degerler["tur"] = tur_normalize(degerler["tur"]) or degerler["tur"]
    degerler["firma_id"] = firma_id  # modelden değil, koddan
    degerler["bugun"] = BUGUN

    con = baglan()
    try:
        con.execute("PRAGMA query_only = ON")  # sorgu yolu veritabanını değiştiremez
        return [dict(r) for r in con.execute(sorgu["sql"], degerler).fetchall()]
    finally:
        con.close()


def talep_ekle(firma_id, talep_metni, emir=None, detay=None, ozet=None):
    """İşlem taleplerini 'Onay bekliyor' olarak kaydet (Kural 5: dış etki yok). Yeni id döner.
    emir/detay/ozet: emir isteminden çıkarılan, muhasebecinin onaylayacağı yapılandırılmış bilgi."""
    _firma_kontrol(firma_id)
    con = baglan()
    try:
        cur = con.execute(
            "INSERT INTO talepler (firma_id, talep_metni, emir, detay, ozet, durum, olusturma_tarihi) "
            "VALUES (?, ?, ?, ?, ?, 'Onay bekliyor', ?)",
            (firma_id, talep_metni, emir, json.dumps(detay, ensure_ascii=False) if detay else None, ozet,
             datetime.now().isoformat(timespec="seconds")))
        con.commit()
        return cur.lastrowid
    finally:
        con.close()


def belge_bul(firma_id, belge_turu, donem):
    """Firmanın beyannamesini bul. belge_turu: 'KDV' | 'MUHSGK'; donem: 'YYYY-AA' ya da 'son'.
    Yalnızca oturumdaki firmanın belgeleri aranır (Kural 2). Bulamazsa None."""
    _firma_kontrol(firma_id)
    con = baglan()
    try:
        r = con.execute(
            "SELECT dosya_adi, donem, tur FROM belgeler "
            "WHERE firma_id = ? AND dosya_adi LIKE ? AND (? = 'son' OR donem = ?) "
            "ORDER BY donem DESC LIMIT 1",
            (firma_id, f"{firma_id}_{belge_turu}_%", donem, donem)).fetchone()
        return dict(r) if r else None
    finally:
        con.close()


def kayitli_eposta(firma_id):
    """Firma kullanıcısının KAYITLI e-postası. Belge asla kullanıcının yazdığı adrese gönderilmez."""
    _firma_kontrol(firma_id)
    con = baglan()
    try:
        r = con.execute("SELECT eposta FROM kullanicilar WHERE firma_id = ? AND rol = 'firma' LIMIT 1",
                        (firma_id,)).fetchone()
        return r["eposta"] if r else None
    finally:
        con.close()


# ---------- Kullanıcının kendi eklediği planlı ödeme / tahsilatlar ----------
YONLER = {"Gider": "Ödeme yapacağım", "Gelir": "Ödeme alacağım (tahsilat)"}


def planli_islem_ekle(firma_id, ekleyen_id, yon, tarih, tutar_tl, aciklama, karsi_taraf=""):
    """Kullanıcı formundan gelen kaydı DOĞRULAYIP ekler (arayüze güvenmez). Yeni id döner.
    firma_id oturumdan gelir (Kural 2); kullanıcı başka firmaya kayıt ekleyemez."""
    _firma_kontrol(firma_id)
    if yon not in YONLER:
        raise ValueError(f"Geçersiz yön: {yon!r} (Gider ya da Gelir olmalı)")
    tarih = str(tarih)
    try:
        datetime.strptime(tarih, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"Geçersiz tarih: {tarih!r} (YYYY-AA-GG olmalı)") from None
    tutar = round(float(tutar_tl), 2)
    if not 0 < tutar < 1_000_000_000:
        raise ValueError("Tutar 0'dan büyük olmalı")
    aciklama = (aciklama or "").strip()
    if not 2 <= len(aciklama) <= 200:
        raise ValueError("Açıklama 2-200 karakter olmalı")
    con = baglan()
    try:
        cur = con.execute(
            "INSERT INTO planli_islemler (firma_id, yon, tarih, tutar_tl, aciklama, karsi_taraf, ekleyen_id, "
            "olusturma) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (firma_id, yon, tarih, tutar, aciklama, (karsi_taraf or "").strip()[:100] or None, ekleyen_id,
             datetime.now().isoformat(timespec="seconds")))
        con.commit()
        return cur.lastrowid
    finally:
        con.close()


def planli_islemler(firma_id):
    """Firmanın tüm planlı kayıtları (arayüz tablosu için), tarihe göre."""
    _firma_kontrol(firma_id)
    con = baglan()
    try:
        return [dict(r) for r in con.execute(
            "SELECT id, yon, tarih, tutar_tl, aciklama, karsi_taraf FROM planli_islemler "
            "WHERE firma_id = ? ORDER BY tarih", (firma_id,))]
    finally:
        con.close()


def planli_islem_sil(islem_id, firma_id):
    """Yalnızca firmanın KENDİ kaydını siler (başka firmanın kaydı silinemez). True/False."""
    _firma_kontrol(firma_id)
    con = baglan()
    try:
        cur = con.execute("DELETE FROM planli_islemler WHERE id = ? AND firma_id = ?", (islem_id, firma_id))
        con.commit()
        return cur.rowcount == 1
    finally:
        con.close()


# ---------- Arayüz (Adım 9) için yardımcılar ----------
# ---------- Giriş deneme sınırı (kaba kuvvetle şifre denemeye karşı) ----------
# Bir e-posta için son başarılı girişten sonraki hatalı denemeler sayılır: PENCERE dakika içinde AZAMI_DENEME
# hatalı denemeden sonra hesap KILIT_DAKIKA boyunca girişe kapanır. Kayıt veritabanında tutulur: sayfayı
# yenilemek ya da yeni sekme açmak sayacı sıfırlamaz.
AZAMI_DENEME, PENCERE_DAKIKA, KILIT_DAKIKA = 5, 15, 15
GIRIS_SEMA = """
CREATE TABLE IF NOT EXISTS giris_denemeleri (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    eposta TEXT NOT NULL,
    basarili INTEGER NOT NULL,          -- 1 başarılı, 0 hatalı
    tarih TEXT NOT NULL                 -- ISO, saniye hassasiyetinde
);
CREATE INDEX IF NOT EXISTS ix_giris_eposta ON giris_denemeleri(eposta, tarih);
"""
@cache
def _sahte_hash():
    """Kullanıcı yoksa da bcrypt çalışsın: cevap süresinden "bu e-posta kayıtlı mı" anlaşılmasın.
    (Gerçek hash'lerle aynı maliyet; ilk ihtiyaçta bir kez üretilir.)"""
    return bcrypt.hashpw(b"kayitli-olmayan-kullanici", bcrypt.gensalt(rounds=12))


class GirisKilitli(Exception):
    """Çok fazla hatalı deneme: hesap geçici olarak girişe kapalı. `dakika`: kalan süre (yukarı yuvarlanmış)."""
    def __init__(self, dakika):
        super().__init__(f"Çok fazla hatalı deneme. {dakika} dakika sonra tekrar deneyin.")
        self.dakika = dakika


def _simdi():
    return datetime.now()


def giris_durumu(eposta, simdi=None):
    """(kalan_deneme, kilit_bitis) — kilit yoksa kilit_bitis None. Yalnızca son başarılı girişten sonraki ve
    son PENCERE dakikadaki hatalı denemeler sayılır."""
    simdi = simdi or _simdi()
    eposta = (eposta or "").strip().lower()
    con = baglan()
    try:
        con.executescript(GIRIS_SEMA)
        son_basari = con.execute("SELECT MAX(tarih) FROM giris_denemeleri WHERE eposta = ? AND basarili = 1",
                                 (eposta,)).fetchone()[0] or ""
        alt = max(son_basari, (simdi - timedelta(minutes=PENCERE_DAKIKA)).isoformat(timespec="seconds"))
        hatalar = [r[0] for r in con.execute(
            "SELECT tarih FROM giris_denemeleri WHERE eposta = ? AND basarili = 0 AND tarih > ? ORDER BY tarih",
            (eposta, alt))]
    finally:
        con.close()
    if len(hatalar) >= AZAMI_DENEME:
        bitis = datetime.fromisoformat(hatalar[AZAMI_DENEME - 1]) + timedelta(minutes=KILIT_DAKIKA)
        if bitis > simdi:
            return 0, bitis
        return AZAMI_DENEME, None  # kilit süresi doldu: yeniden tam hak
    return AZAMI_DENEME - len(hatalar), None


def _deneme_yaz(eposta, basarili, simdi):
    con = baglan()
    try:
        con.executescript(GIRIS_SEMA)
        con.execute("INSERT INTO giris_denemeleri (eposta, basarili, tarih) VALUES (?, ?, ?)",
                    (eposta, int(basarili), simdi.isoformat(timespec="seconds")))
        con.execute("DELETE FROM giris_denemeleri WHERE tarih < ?",  # tablo büyümesin: 1 günden eskiler
                    ((simdi - timedelta(days=1)).isoformat(timespec="seconds"),))
        con.commit()
    finally:
        con.close()


def kullanici_dogrula(eposta, sifre, simdi=None):
    """E-posta + şifre doğruysa kullanıcı bilgisini (sifre_hash HARİÇ) döndür, değilse None.
    Hesap çok fazla hatalı deneme yüzünden kilitliyse şifreye BAKMADAN GirisKilitli fırlatır."""
    simdi = simdi or _simdi()
    eposta = (eposta or "").strip().lower()
    _, kilit = giris_durumu(eposta, simdi)
    if kilit:
        raise GirisKilitli(max(1, -(-int((kilit - simdi).total_seconds()) // 60)))
    con = baglan()
    try:
        k = con.execute(
            "SELECT k.id, k.eposta, k.sifre_hash, k.rol, k.firma_id, k.ad, f.unvan "
            "FROM kullanicilar k LEFT JOIN firmalar f ON f.id = k.firma_id "
            "WHERE k.eposta = ?", (eposta,)).fetchone()
    finally:
        con.close()
    hash_ = k["sifre_hash"].encode("utf-8") if k else _sahte_hash()
    dogru = bcrypt.checkpw((sifre or "").encode("utf-8"), hash_) and k is not None
    _deneme_yaz(eposta, dogru, simdi)  # kayıtlı olmayan e-postalar da sayılır (aynı cevap, aynı sınır)
    if dogru:
        kullanici = dict(k)
        del kullanici["sifre_hash"]  # hash oturuma bile taşınmaz
        return kullanici
    return None


def firmalar():
    """Tüm firmaların kimlikleri (YALNIZCA muhasebeci paneli için: firma oturumunda kullanılmaz)."""
    con = baglan()
    try:
        return [r["id"] for r in con.execute("SELECT id FROM firmalar ORDER BY id")]
    finally:
        con.close()


def erisilebilir_firma(kullanici, firma_id):
    """Oturumdaki kullanıcı bu firmanın panelini görebilir mi? (Arayüzden gelen firma_id'ye güvenilmez.)
    Firma yetkilisi: yalnızca kendi firması. Muhasebeci: kayıtlı her müşteri firma (salt okunur görüntüleme)."""
    try:
        _firma_kontrol(firma_id)
    except ValueError:
        return False
    if (kullanici or {}).get("rol") == "muhasebeci":
        return firma_id in firmalar()
    return (kullanici or {}).get("firma_id") == firma_id


def firma_bilgisi(firma_id):
    """Panel başlığı ve yan menü için firma künyesi (unvan, tür, vergi no, sektör, çalışan sayısı)."""
    _firma_kontrol(firma_id)
    con = baglan()
    try:
        r = con.execute("SELECT id, unvan, tur, vergi_no, sektor, calisan_sayisi FROM firmalar WHERE id = ?",
                        (firma_id,)).fetchone()
        return dict(r) if r else {}
    finally:
        con.close()


def yukumlulukler(firma_id):
    """Firmanın tüm yükümlülükleri (panel tablosu ve özet kartlar için)."""
    _firma_kontrol(firma_id)
    con = baglan()
    try:
        return [dict(r) for r in con.execute(
            f"SELECT id, tur, donem, tutar_tl, son_odeme_tarihi, {DURUM_SQL}, odeme_tarihi "
            "FROM yukumlulukler WHERE firma_id = :firma_id ORDER BY son_odeme_tarihi DESC",
            {"firma_id": firma_id, "bugun": BUGUN})]
    finally:
        con.close()


def aylik_gelir_gider(firma_id):
    """Grafik için firmanın ay ay para giriş/çıkışları (kalem bazında). Satırlar:
    {"ay": "2026-10", "yon": "Gelir"|"Gider", "kalem": "Müşteri tahsilatları", "tutar": 12345.6}

    Gelir: satış faturalarının TAHSİLATI + kullanıcının planladığı tahsilatlar. Satış faturasının ayı: tahsil
    edildiyse tahsil günü, edilmediyse vade günü (app/nakit.hareketler ile aynı kural; ay toplamları test edilir).
    Gider: alış faturaları + net maaş ödemeleri + vergi/prim yükümlülükleri + planlı ödemeler.
    (Maaşta NET kullanılır: SGK/muhtasar kesintisi zaten yükümlülük olarak sayılıyor, çift sayılmasın.)
    Yükümlülüğün ayı: ödendiyse ödeme tarihi, değilse son ödeme tarihi."""
    _firma_kontrol(firma_id)
    sql = """
        SELECT substr(CASE WHEN tip = 'Satış' AND vade_tarihi IS NOT NULL THEN
                          CASE WHEN odeme_tarihi IS NOT NULL AND odeme_tarihi <= :bugun THEN odeme_tarihi
                               ELSE vade_tarihi END
                      ELSE tarih END, 1, 7) AS ay,
               CASE tip WHEN 'Satış' THEN 'Gelir' ELSE 'Gider' END AS yon,
               CASE tip WHEN 'Satış' THEN 'Müşteri tahsilatları' ELSE 'Alış faturaları' END AS kalem,
               SUM(tutar_tl) AS tutar
        FROM faturalar WHERE firma_id = :f GROUP BY 1, 2, 3
        UNION ALL
        SELECT substr(odeme_tarihi, 1, 7), 'Gider', 'Maaşlar (net)', SUM(net_tl)
        FROM bordrolar WHERE firma_id = :f GROUP BY 1
        UNION ALL
        SELECT substr(COALESCE(odeme_tarihi, son_odeme_tarihi), 1, 7), 'Gider', 'Vergi ve prim', SUM(tutar_tl)
        FROM yukumlulukler WHERE firma_id = :f GROUP BY 1
        UNION ALL
        SELECT substr(tarih, 1, 7), yon, CASE yon WHEN 'Gelir' THEN 'Planlı tahsilat' ELSE 'Planlı ödeme' END,
               SUM(tutar_tl)
        FROM planli_islemler WHERE firma_id = :f GROUP BY 1, 2
        ORDER BY 1"""
    con = baglan()
    try:
        return [dict(r) for r in con.execute(sql, {"f": firma_id, "bugun": BUGUN})]
    finally:
        con.close()


def firma_talepleri(firma_id):
    """Firmanın kendi talepleri ve durumları."""
    _firma_kontrol(firma_id)
    con = baglan()
    try:
        return [dict(r) for r in con.execute(
            "SELECT id, COALESCE(ozet, talep_metni) AS talep, durum, olusturma_tarihi FROM talepler "
            "WHERE firma_id = ? ORDER BY id DESC", (firma_id,))]
    finally:
        con.close()


def bekleyen_talepler():
    """Muhasebecinin onay kuyruğu: tüm firmaların 'Onay bekliyor' talepleri."""
    con = baglan()
    try:
        return [dict(r) for r in con.execute(
            "SELECT t.id, t.firma_id, f.unvan, t.talep_metni, t.emir, t.ozet, t.olusturma_tarihi "
            "FROM talepler t JOIN firmalar f ON f.id = t.firma_id "
            "WHERE t.durum = 'Onay bekliyor' ORDER BY t.id")]
    finally:
        con.close()


def talep_karar(talep_id, karar, karar_veren_id):
    """Muhasebeci talebi onaylar/reddeder. Karar vereni DB'den doğrular (arayüze güvenmez).
    Yalnızca 'Onay bekliyor' durumundaki talep değişir (iki kez onaylanamaz). True/False döner."""
    if karar not in ("Onaylandı", "Reddedildi"):
        raise ValueError(f"Geçersiz karar: {karar!r}")
    con = baglan()
    try:
        rol = con.execute("SELECT rol FROM kullanicilar WHERE id = ?", (karar_veren_id,)).fetchone()
        if not rol or rol["rol"] != "muhasebeci":
            raise PermissionError("Talepleri yalnızca muhasebeci onaylayabilir")
        cur = con.execute(
            "UPDATE talepler SET durum = ?, onaylayan_id = ? WHERE id = ? AND durum = 'Onay bekliyor'",
            (karar, karar_veren_id, talep_id))
        con.commit()
        return cur.rowcount == 1
    finally:
        con.close()


def _kontrol():
    """CLAUDE.md Adım 5 Kontrol. Beklenen değerler senaryo gününe (11.11.2026) göredir."""
    if BUGUN != "2026-11-11":
        print(f"Not: bugün = {BUGUN}. Bu kontrol senaryo gününe göre yazıldı; gecikmiş / en yakın ödeme "
              "satırları farklı çıkabilir. Senaryo gününde çalıştırmak için:  BUGUN=2026-11-11 python -m app.db\n")
    tamam = True

    def yaz(ok, mesaj):
        nonlocal tamam
        tamam &= ok
        print("OK   " if ok else "HATA ", mesaj)

    print("--- KONTROL ---")
    satirlar = calistir("ay_odemeleri", "F001", "2026-11")
    toplam = round(sum(s["tutar_tl"] for s in satirlar), 2)  # toplamı Python hesaplar (Kural 1)
    yaz(len(satirlar) == 4 and toplam == 165469.58,
        f"ay_odemeleri F001 2026-11: {len(satirlar)} satır, toplam {toplam} ({[s['id'] for s in satirlar]})")

    f002 = calistir("ay_odemeleri", "F002", "2026-11")
    yaz(all(s["id"] not in {x["id"] for x in satirlar} for s in f002),
        f"F002 ile F001 verisi gelmez (F002: {[s['id'] for s in f002]})")

    s = calistir("durum", "F001", "sgk", "2026-10")
    yaz(len(s) == 1 and s[0]["id"] == "Y018" and s[0]["durum"] == "Bekliyor",
        f"durum F001 'sgk' 2026-10 -> {s[0]['id'] if s else None} {s[0]['tutar_tl'] if s else ''} (T01)")

    s = calistir("durum", "F002", "KDV", "2026-08")
    yaz(s and s[0]["id"] == "Y030" and s[0]["odeme_tarihi"] == "2026-09-26",
        f"durum F002 KDV 2026-08 -> ödeme tarihi {s[0]['odeme_tarihi'] if s else None} (T03)")

    s = calistir("gecikmis", "F003")
    yaz([x["id"] for x in s] == ["Y055"], f"gecikmis F003 -> {[x['id'] for x in s]} (T04)")

    s = calistir("en_yakin", "F002")
    yaz(s and s[0]["id"] == "Y040", f"en_yakin F002 -> {s[0]['id'] if s else None} {s[0]['son_odeme_tarihi'] if s else ''} (T05)")

    s = calistir("ay_odemeleri", "F002", "2026-11", "sgk")
    yaz([x["id"] for x in s] == ["Y038"], f"ay_odemeleri F002 2026-11 SGK -> {[x['id'] for x in s]} (yalnız SGK)")

    s = calistir("odenenler", "F002", "2026-10", "KDV")
    yaz([x["id"] for x in s] == ["Y033"] and s[0]["tutar_tl"] == 86213.86,
        f"odenenler F002 2026-10 KDV -> {[(x['id'], x['tutar_tl'], x['odeme_tarihi']) for x in s]}")

    s = calistir("odenenler", "F002", "2026-10")
    yaz({x["id"] for x in s} == {"Y033", "Y034", "Y035"}, f"odenenler F002 2026-10 -> {[x['id'] for x in s]}")

    s = calistir("durum", "F002", "KDV", "2025-03")
    yaz(s == [], "durum F002 KDV 2025-03 -> 0 satır, yani çekimser kalınacak (T13)")

    for kotu, aciklama in [(("DROP TABLE firmalar", "F001"), "listede olmayan sorgu adı"),
                           (("durum", "F001' OR '1'='1", "KDV", "2026-10"), "sahte firma_id"),
                           (("durum", "F001", "KDV"), "eksik parametre")]:
        try:
            calistir(*kotu)
            yaz(False, f"{aciklama} REDDEDİLMEDİ")
        except ValueError as e:
            yaz(True, f"{aciklama} reddedildi: {e}")

    print("\nSONUÇ:", "Adım 5 Kontrol GEÇTİ ✅" if tamam else "Kontrol GEÇMEDİ ❌")


if __name__ == "__main__":
    _kontrol()
