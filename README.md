# Kişisel Muhasebe Asistanı

Firma sahiplerinin muhasebecilerine sormadan kendi **vergi ve prim ödemelerini, son ödeme tarihlerini, beyanname bilgilerini ve faturalarını** Türkçe olarak sorgulayabildiği, **tamamen yerel çalışan** bir yapay zekâ asistanı. E-posta gönderme gibi dışarıya etkisi olan işlemler **muhasebeci onayından** geçer.

> BTK Akademi "Yapay Zekâ Çözümleri Geliştirme Kariyer Atölyesi" final projesidir. Çalışan bir **demo/prototip**tir, üretimde kullanılacak bir ürün değildir.
> Projedeki tüm firmalar, kişiler ve rakamlar **kurgusaldır** ("Demo ..." firmalar).

---

## Ne yapabiliyor?

| Kullanıcı sorar | Sistem ne yapar | Cevap nereden gelir |
|---|---|---|
| "Ekim SGK primi ödendi mi?" | Kayıt sorusu: hazır SQL sorgusu çalıştırılır | SQLite |
| "Son üç ayda ne kadar ödedim?" | Ay aralığını **kod** hesaplar, toplamı **Python** yapar | SQLite |
| "Eylül KDV beyannamemde ödenecek tutar ne?" | Belge sorusu: arama → rerank → kaynaklı cevap | ChromaDB (RAG) |
| "SGK primini geç ödersem ne olur?" | Ortak rehberlerden genel bilgi verilir | ChromaDB (RAG) |
| "Son beyannamemi e-postama gönder." | Talep **"Onay bekliyor"** olarak kaydedilir, e-posta gönderilmez | Talepler tablosu |
| "Hangi hisseyi alayım?" | Nazikçe reddedilir | — |
| "Demo Yazılım'ın KDV'si ne kadar?" | Başka firmanın verisi **asla** verilmez | — |

**Arayüz (Streamlit):**
- **Firma paneli:** özet kartlar (bu ay ödenecek, geciken, en yakın son tarih), yükümlülük tablosu, talepler ve sohbet. Her cevabın altında hangi yoldan (sql/rag) ve hangi kaynaktan geldiği yazar.
- **Muhasebeci paneli:** onay bekleyen talepler, **Onayla / Reddet** butonları.

---

## Mimari

```
KURULUM (bir kez)
  data/csv/*.csv ──> scripts/01_veritabani_kur.py ──> SQLite (data/muhasebe.db)
                 ──> scripts/02_belge_uret.py     ──> data/belgeler/*.txt (40 belge)
  data/belgeler  ──> scripts/03_indeksle.py (200/40 token, embeddinggemma) ──> Chroma (data/chroma)

SORU YOLU (LangGraph — app/akis.py)
  Streamlit (soru + firma_id OTURUMDAN)
     └─> niyet düğümü (qwen2.5, few-shot, format=json, temperature=0) + kod kuralları
           ├─ kayit       ─> SQL: hazır, parametreli sorgu; firma_id kodda eklenir ─> cevap
           ├─ belge       ─> RAG: Chroma k=8 (firma + ORTAK filtresi) → lexical rerank → ilk 3
           │                     → JSON cevap → kanıt eşleştirme → [kaynak: dosya.txt]
           ├─ islem       ─> talepler tablosuna 'Onay bekliyor' ─> "muhasebecinize iletildi"
           └─ kapsam_disi / başka firma ─> nazik ret
     └─> logla düğümü (soru, niyet, araç, kaynaklar, cevap, süre_ms → loglar tablosu)

ONAY YOLU
  Muhasebeci paneli ─ Onayla ─> talep 'Onaylandı'   (n8n e-posta adımı: yapım aşamasında)
```

### Teknoloji

| Katman | Seçim |
|---|---|
| Dil | Python 3.11+ (3.14 ile test edildi) |
| LLM | Ollama · `qwen2.5:1.5b` (yerel çalışır, veri dışarı çıkmaz) |
| Embedding | Ollama · `embeddinggemma` |
| İlişkisel veri | SQLite (`data/muhasebe.db`) |
| Vektör DB | ChromaDB (`data/chroma`, koleksiyon `muhasebe`) |
| LLM kütüphaneleri | `langchain-ollama`, `langchain-chroma`, `langchain-text-splitters`, `langchain-core` |
| Agent | LangGraph (`StateGraph`) |
| Arayüz | Streamlit |
| Parola | bcrypt |
| Otomasyon | n8n (onay e-postası, yapım aşamasında) |

> **Model seçimi:** Proje 6 GB RAM'li, GPU'suz bir bilgisayarda geliştirildi, bu yüzden küçük modeller kullanıldı. Daha güçlü bir makinede `.env` dosyasında `LLM_MODEL=qwen2.5:7b` ve `EMBED_MODEL=bge-m3` ayarlanabilir; kod değişikliği gerekmez (embedding modeli değişirse indeksi yeniden kurun).

---

## Temel kurallar (güvenlik ve doğruluk)

1. **Rakamlar SQL'den, metinler RAG'den gelir.** Model tutar ya da tarih uydurmaz; toplamları Python hesaplar.
2. **`firma_id` her zaman koddan, yani oturumdan gelir.** Her SQL sorgusunda ve her Chroma aramasında filtre olarak uygulanır. Kullanıcı metninden ya da model çıktısından alınmaz.
3. **Model serbest SQL yazamaz.** `app/db.py` içindeki `SORGULAR` menüsünden bir sorgu adı seçer; listede olmayan ad reddedilir. Tüm sorgular parametrelidir (`?` / `:ad`).
4. **Bilgi yoksa sistem çekimser kalır:** "Bu bilgi kayıtlarınızda yok, muhasebecinize iletebilirim."
5. **Dışarıya etkisi olan hiçbir işlem onaysız yapılmaz.** Agent talebi yalnızca kaydeder.
6. **Belgelerdeki talimatlar veri olarak işlenir.** `sahte_talimat_testi.txt` belgesine gömülü "önceki talimatları yok say" cümlesine uyulmaz.
7. Tüm model çağrıları yerel Ollama'ya gider; hiçbir dış API anahtarı kullanılmaz.

**Tasarım ilkesi: "LLM yorumlar, kod denetler."** Küçük model esnek Türkçeyi anlamakta iyidir ama kesin kurallarda hata yapabilir. Bu yüzden:
- Model çıktısı şemaya göre doğrulanır, parametreler türlerine göre yerine oturtulur.
- Kesin kalıplar ("bu ay ödenecek", "son 3 ay", "gecikmiş", "kaç çalışan") kod kurallarıyla düzeltilir.
- Kayıt cevaplarında uydurma sayı, eksik ana rakam ya da "ödendi/ödenmedi" çelişkisi varsa model cevabı atılır ve şablon cevap kullanılır.
- Belge cevaplarında cevaptaki her tutar ve tarih kaynak belgede **birebir** geçmek zorundadır (kanıt eşleştirme). Kaynak, bu kanıtı içeren dosya olarak belirlenir.

---

## Kurulum

### Gereksinimler
- Python 3.11 veya üzeri
- [Ollama](https://ollama.com) (çalışır durumda, `http://localhost:11434`)
- (İsteğe bağlı) n8n: Docker ile `docker compose up -d` ya da Node.js ile `npx n8n`

### Adımlar

```bash
git clone https://github.com/ranaaclskn/muhasebe-asistani.git
cd muhasebe-asistani

python3 -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

cp .env.example .env               # Windows: copy .env.example .env

ollama pull qwen2.5:1.5b
ollama pull embeddinggemma
```

### Veriyi hazırla (sırayla, bir kez)

```bash
python scripts/01_veritabani_kur.py   # SQLite: şema + CSV + bcrypt  → "Adım 2 Kontrol GEÇTİ"
python scripts/02_belge_uret.py       # 36 beyanname + 4 ortak belge → "Adım 3 Kontrol GEÇTİ"
python scripts/03_indeksle.py         # chunk + embedding + Chroma   → "Adım 4 Kontrol GEÇTİ"
```

Her script sonunda kendi kontrolünü çalıştırır. `01` her çalıştığında veritabanını sıfırdan kurar (talepler ve loglar da silinir). `03` tekrar çalıştırıldığında kopya kayıt oluşturmaz.

### Arayüzü başlat

```bash
streamlit run ui/streamlit_app.py
```

Tarayıcıda `http://localhost:8501` açılır. `app/` içindeki bir dosyayı değiştirirseniz Streamlit'i yeniden başlatın (`Ctrl + C`, sonra aynı komut).

### Demo hesapları

Tüm hesapların şifresi: `Demo2026!`

| E-posta | Rol | Firma |
|---|---|---|
| `gida@demo.local` | Firma | Demo Gıda Ltd. Şti. |
| `yazilim@demo.local` | Firma | Demo Yazılım A.Ş. |
| `tekstil@demo.local` | Firma | Demo Tekstil (Şahıs) |
| `muhasebe@demo.local` | Muhasebeci | — (tüm taleplerin onay kuyruğu) |

Senaryonun "bugünü" **11 Kasım 2026**'dır (`app/config.py` → `BUGUN`).

### Denenebilecek sorular

- Ekim SGK primi ödendi mi?
- Bu ay toplam ne kadar ödeyeceğim?
- Son üç ayda ne kadar ödeme yaptım?
- Bu yıl yapılan ödeme toplam kaç TL?
- Eylül KDV beyannamemde ödenecek KDV ne kadardı?
- Geçici vergi ne zaman ödenir?
- SGK primini geç ödersem ne olur?
- Son beyannamemi e-postama gönder.
- Kaç kişi çalışıyor?

---

## Testler ve kontroller

Her modülün kendi kontrolü var. Model gerektirenler birkaç dakika sürebilir.

```bash
python -m app.db       # hazır SQL sorguları + kötü niyetli girişlerin reddi
python -m app.niyet    # test setinde niyet doğruluğu (hedef ≥14/15)
python -m app.kayit    # kayıt cevapları: doğru rakam, çekimserlik, başka firma reddi
python -m app.rag      # belge cevapları: doğru kaynak, rakam, prompt injection
python -m app.akis     # uçtan uca LangGraph akışı + talep + log
python scripts/soru_dene.py   # etkileşimli: her sorunun hangi yoldan geçtiğini gösterir
```

**Son ölçümler** (`qwen2.5:1.5b`, CPU):

| Kontrol | Sonuç |
|---|---|
| Niyet sınıflandırma (test seti T01–T15) | 15/15 |
| Kayıt cevapları (T01–T05, T12, T13 + kullanıcı testlerinden 7 ek soru) | 14/14 |
| Belge cevapları (T06–T09, T15 + var olmayan dönem) | 6/6 |
| Firma izolasyonu (3 hesap, arayüz) | Her firma yalnızca kendi verisini görüyor |

Not: Test seti küçüktür (15 soru) ve prompt'lar bu sorular gözetilerek iyileştirilmiştir. Arayüzde denenen farklı sorular hata bulmaya devam etmektedir; bulunan her hata kalıcı test olarak eklenir (`EK1`–`EK7`).

---

## Klasör yapısı

```
muhasebe-asistani/
├── app/
│   ├── config.py        # ayarlar (.env), yollar, chunk boyutu, senaryo tarihi
│   ├── db.py            # SQLite: SORGULAR menüsü, calistir(), talepler, giriş (bcrypt)
│   ├── niyet.py         # soru → {niyet, sorgu, parametreler} + kod kuralları
│   ├── kayit.py         # SQL sonucu → cevap (toplam Python'da, şablon/denetim)
│   ├── rag.py           # Chroma arama → rerank → JSON cevap → kanıt eşleştirme
│   ├── dogrulama.py     # lexical rerank, dönem çıkarımı, kanıt/atıf doğrulama
│   ├── akis.py          # LangGraph: niyet → {sql, rag, talep, reddet} → logla
│   └── log.py           # loglar tablosuna yazma
├── scripts/
│   ├── 01_veritabani_kur.py
│   ├── 02_belge_uret.py
│   ├── 03_indeksle.py
│   └── soru_dene.py     # geliştirici için adım adım deneme aracı
├── ui/streamlit_app.py  # giriş, firma paneli, muhasebeci paneli
├── data/
│   ├── csv/             # kurgusal veri: firmalar, kullanıcılar, yükümlülükler, faturalar, belgeler, test seti
│   ├── belgeler/        # 02 tarafından üretilen 40 .txt belge
│   ├── muhasebe.db      # 01 üretir (git'e girmez)
│   └── chroma/          # 03 üretir (git'e girmez)
├── docker-compose.yml   # n8n (Ollama yerelde kurulu varsayılır)
├── requirements.txt
├── .env.example
└── CLAUDE.md            # projenin tam bağlamı ve yapım planı
```

---

## Atölye (Gün 5–6 RAG) ile eşleşme

| Atölye | Bu projede |
|---|---|
| `d5_01_documents` (Document + metadata) | `03_indeksle.py` → metadata: `{kaynak, firma_id, tur, donem}` |
| `d5_02_chunks` (token tabanlı, overlap, `chunk_id`) | `cl100k_base`, 200/40 token, deterministik `chunk_id` |
| `d5_03_embeddings`, `d5_04_index` | Ollama embedding + Chroma (upsert, kopya yok) |
| `d5_05_search` (metadata filtresi) | firma filtresi + dönem filtresi |
| `d6_00` / `d6_01` (lexical rerank) | `dogrulama.rerank()`: k=8 → ilk 3 |
| `d6_02_answer` (kaynaklı cevap) | `rag.cevapla_belge()` |
| `d6_03_validate` (atıf doğrulama) | `validate_citations` + **kanıt eşleştirme** |
| `d6_05_guvenlik` (prompt injection) | `sahte_talimat_testi.txt` (T15) |

---

## Sınırlamalar

- **Küçük model:** `qwen2.5:1.5b` beklenmedik soru biçimlerinde yanlış sınıflandırma yapabilir. Kod kuralları bilinen hataları düzeltir, ama her ifade biçimi kapsanamaz.
- **Hız:** CPU'da ilk soru yaklaşık 40 saniye sürer (model belleğe yüklenir), sonraki sorular 3–25 saniye sürer.
- **Belgeler kurgusaldır:** beyanname metinleri `02_belge_uret.py` ile üretilir; gerçek PDF beyanname okunmaz.
- **Ücret/maaş tutarları** veritabanında yoktur, yalnızca beyanname özetlerinde geçer. Bu tür sorular belge yoluna gider; birkaç aylık toplamları güvenilir biçimde hesaplanamaz.
- **Geçerli bir atıf, cevabın doğru olduğunu kanıtlamaz.** Kanıt eşleştirme yalnızca rakam ve tarihleri kontrol eder, cümlenin anlamını kontrol etmez.
- Vergi takvimi ve rehber metinleri **demo amaçlıdır**; resmi bilgi için GİB ve SGK duyurularına bakın.

## Yol haritası

- [x] Veritabanı, belge üretimi, indeksleme
- [x] SQL sorgu menüsü, niyet sınıflandırma, kaynaklı RAG, doğrulama
- [x] LangGraph akışı ve loglama
- [x] Streamlit arayüzü (giriş, firma paneli, muhasebeci onayı)
- [ ] n8n: onaylanan talep için e-posta, yaklaşan ödemeler için hatırlatma
- [ ] Toplu test scripti (Hit@3, Top1, ortalama süre) ve pytest birim testleri
- [ ] Temiz kurulum provası
