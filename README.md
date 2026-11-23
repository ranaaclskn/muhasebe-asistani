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
| "Beyannamemi gönder" → *"Hangi beyanname?"* → "KDV" → *"Hangi dönem?"* → "Eylül" → *"Onaylıyor musunuz?"* → "evet" | **Çok adımlı sohbet:** eksik bilgi tek tek sorulur, özet gösterilir, onaydan sonra kayıt açılır (LangGraph `interrupt` + SQLite checkpoint; atölye 7. gün) | Talepler / planlı kayıtlar |
| "3 numaralı talebim ne durumda?" / "Taleplerim ne oldu?" | Talep durumu sorgulama (yalnız kendi firmasının talepleri) | Talepler tablosu |
| "Hangi hisseyi alayım?" | Nazikçe reddedilir | — |
| "Demo Yazılım'ın KDV'si ne kadar?" | Başka firmanın verisi **asla** verilmez | — |
| "Aralıkta planladığım ödemeler neler?" / "Ne kadar tahsilat bekliyorum?" / "Aralık nakit planım" | Kullanıcının **kendi eklediği** planlı ödeme ve tahsilatlar; nakit planında giriş, çıkış ve net | SQLite (`planli_islemler`) |
| "Ekim faturalarımı göster" | Ayın alış ve satış faturaları; alış ve satış toplamları **ayrı** verilir | SQLite (`faturalar`) |
| "Kaç kişi çalışıyor?" / "Çalışanlar kimler?" / "Şoförlere ne kadar maaş ödedim?" | Çalışan listesi, kıdem, görev bazında maaş toplamları ve karşılaştırmalar (hesabı Python yapar) | SQLite (`calisanlar`, `bordrolar`) |
| "Gecikmiş ödemelerimin faizi ne kadar?" / "Geciken ödemeler faizleriyle toplam ne kadar?" | Gecikmiş borçlar, kaç gün geciktiği ve **tahmini gecikme zammı** (ana borç × aylık oran / 30 × gün) ile toplam. SGK primi için tahmin verilmez (gecikme cezası + zammı SGK hesaplar) | SQLite + resmî oran (`.env`) |
| "Gecikme zammı oranı nedir?" / "Nasıl hesaplanır?" | Resmî oran (aylık %3,7; 6183 s. Kanun md. 51, 13.11.2025'ten beri), günlük oran ve örnek hesap | Resmî oran (`.env`) |

**Arayüz (Streamlit):** sade, kurumsal bir tasarım (lacivert–gri tema, ince çerçeveli kartlar, emoji yerine ikonlar; tema `.streamlit/config.toml` içinde).
- **Giriş ekranı:** solda ürün tanıtımı, sağda oturum açma kartı; demo hesapları açılır kutuda.
- **Yan menü:** kullanıcı bilgisi ve firma künyesi (unvan, tür, sektör, vergi no, çalışan sayısı), çıkış.
- **Firma paneli:**
  - **Asistan** sol üstte, sayfa açılır açılmaz (yazma kutusu dahil) ekranda görünür; sohbet alanının yüksekliği ekran boyuna göre ayarlanır. "Sık sorulanlar" butonları son mesajın altındadır. Her cevabın altında hangi yoldan (sql/rag) ve hangi kaynaktan geldiği yazar. Onay sorularında **Evet / Hayır** butonları çıkar.
  - **Özet kartları:** bu ay ödenecek, geciken ödeme, en yakın son tarih, seçilen dönemin net durumu (artı/eksi).
  - **Gelir–gider grafiği:** gelir sıfırın üstünde, gider altında, koyu çizgi ayın neti. Dönem seçimi (son 3 ay / son 6 ay / tümü), toplam gelir–gider–net özeti, **gider dağılımı** (vergi/prim, maaş, alış faturaları) ve tablo görünümü (CSV indirilebilir). Gelir = satış faturaları + planlı tahsilatlar; gider = alış faturaları + **net** maaşlar + vergi/prim + planlı ödemeler (maaşta net kullanılır, çünkü SGK ve muhtasar kesintileri zaten vergi/prim olarak sayılır). İleri tarihli aylar açık renkle "plan" olarak gösterilir.
  - **Yaklaşan ödemeler:** ödenmemiş vergi/prim ve planlı ödemeler tarih sırasıyla; "4 gün gecikti" (kırmızı), "5 gün kaldı" (7 gün kalınca sarı).
  - **Alt sekmeler:** yükümlülükler (durum renkli, CSV), planlı ödeme / tahsilat ekleme formu ve listesi (CSV), taleplerim. Sekmeler sabit yüksekliktedir; sekme değişince sayfa kaymaz.
- **Muhasebeci paneli:** bekleyen talep sayısı, onay bekleyen talepler (ne onaylandığının özetiyle), **Onayla / Reddet**; onay tek kullanımlık token ile gönderime alınır, denetim kaydı tutulur.

Kullanıcının eklediği kayıtlar muhasebecinin resmî kayıtlarından (`yukumlulukler`) **ayrı** tutulur; "bu ay ne kadar vergi ödeyeceğim" sorusu yalnız resmî kayıtlardan cevaplanır.

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
| Arayüz | Streamlit (grafik: Altair) |
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

Faturalar (`data/csv/faturalar.csv`, 87 kayıt): Eylül–Ekim 2026 alış/satış örnekleri (24) ve gelir–gider grafiği dengeli görünsün diye eklenen Mayıs–Kasım 2026 satış faturaları (63; her ayın satış toplamı o ayın giderinin 0,92–1,18 katı). Kurgusal çalışan ve bordro verisi (`data/csv/calisanlar.csv`, `bordrolar.csv`) depoda hazırdır; `01` bunları da yükler. Yeniden üretmek için `python scripts/00_bordro_uret.py` (sabit seed, her seferinde aynı veri; brüt toplam = muhtasar / 0,15, gelir vergisi toplamı = muhtasar). Mevcut bir veritabanında tablolar ilk bağlantıda kendiliğinden eklenir, veri silinmez.

**Bugünün tarihi:** Asistan varsayılan olarak gerçek tarihi kullanır. Son ödeme tarihi geçmiş ve ödenmemiş kayıtlar otomatik olarak "Gecikti" sayılır; "bu ay / geçen ay / yaklaşan" buna göre hesaplanır. Sunum için senaryo gününü sabitlemek isterseniz `.env` dosyasına `BUGUN=2026-11-11` yazın. Testler (`pytest`) her zaman senaryo gününde çalışır (`tests/conftest.py`).

**Gecikme zammı oranı:** Tahmini gecikme zammı hesabı ve "gecikme zammı oranı nedir" cevabı `.env` dosyasındaki oranı kullanır (varsayılan aylık %3,7, yürürlük 13.11.2025). Oran Cumhurbaşkanı kararıyla değişirse kod değiştirmeden güncelleyin:

```
GECIKME_ZAMMI_AYLIK=3.7
GECIKME_ZAMMI_TARIH=13.11.2025
```

### Arayüzü başlat

```bash
streamlit run ui/streamlit_app.py
```

Tarayıcıda `http://localhost:8501` açılır (yalnızca bu bilgisayardan erişilir: `.streamlit/config.toml` → `address = "127.0.0.1"`). `app/` içindeki bir dosyayı ya da `.streamlit/config.toml` temasını değiştirirseniz Streamlit'i yeniden başlatın (`Ctrl + C`, sonra aynı komut); yalnızca `ui/` değiştiyse sayfayı yenilemek yeterlidir.

### Demo hesapları

Tüm hesapların şifresi: `Demo2026!`

| E-posta | Rol | Firma |
|---|---|---|
| `gida@demo.local` | Firma | Demo Gıda Ltd. Şti. |
| `yazilim@demo.local` | Firma | Demo Yazılım A.Ş. |
| `tekstil@demo.local` | Firma | Demo Tekstil (Şahıs) |
| `muhasebe@demo.local` | Muhasebeci | — (tüm taleplerin onay kuyruğu) |

Senaryo günü **11 Kasım 2026**'dır: testler bu günde çalışır; arayüz ise varsayılan olarak gerçek tarihi kullanır (sabitlemek için `.env` → `BUGUN=2026-11-11`).

### Denenebilecek sorular

- Ekim SGK primi ödendi mi?
- Bu ay toplam ne kadar ödeyeceğim?
- Son üç ayda ne kadar ödeme yaptım?
- Bu yıl yapılan ödeme toplam kaç TL?
- Eylül KDV beyannamemde ödenecek KDV ne kadardı?
- Geçici vergi ne zaman ödenir?
- SGK primini geç ödersem ne olur?
- Son beyannamemi e-postama gönder.
- Kaç kişi çalışıyor? / Çalışanlar kimler?
- Ekim faturalarımı göster.
- Gecikmiş ödemelerimin faizi ne kadar?
- Gecikme zammı oranı nedir?

---

## Testler ve kontroller

**Birim testleri (model gerekmez, birkaç saniye):**

```bash
python -m pytest -q            # 130 test: niyet kuralları, kayıt cevapları, onay/token, planlı kayıtlar, sohbet akışı
```

Testler gerçek veritabanının **geçici bir kopyasında** çalışır; arayüzden eklediğiniz kayıtlar değişmez ve testleri etkilemez.

Her modülün ayrıca kendi kontrolü var. Model gerektirenler birkaç dakika sürebilir.

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
| Kayıt cevapları (T01–T05, T12, T13 + kullanıcı testlerinden 8 ek soru) | 15/15 |
| Birim testleri (`pytest`) | 130/130 |
| Belge cevapları (T06–T09, T15 + var olmayan dönem) | 6/6 |
| Firma izolasyonu (3 hesap, arayüz) | Her firma yalnızca kendi verisini görüyor |

Not: Test seti küçüktür (15 soru) ve prompt'lar bu sorular gözetilerek iyileştirilmiştir. Arayüzde denenen farklı sorular hata bulmaya devam etmektedir; bulunan her hata kalıcı test olarak eklenir (`EK1`–`EK8` ve `tests/` altındaki pytest testleri).

---

## Klasör yapısı

```
muhasebe-asistani/
├── app/
│   ├── config.py        # ayarlar (.env), yollar, chunk boyutu, "bugün", gecikme zammı oranı
│   ├── db.py            # SQLite: SORGULAR menüsü, calistir(), talepler, giriş (bcrypt), grafik verisi
│   ├── niyet.py         # soru → {niyet, sorgu, parametreler} + kod kuralları
│   ├── kayit.py         # SQL sonucu → cevap (toplam Python'da, şablon/denetim), gecikme zammı hesabı
│   ├── bordro.py        # çalışan / maaş / bordro soruları
│   ├── emirler.py       # emir menüsü (belge gönder, planlı kayıt, görüşme) ve alan çıkarımı
│   ├── onay.py          # insan onayı, tek kullanımlık token, denetim kaydı
│   ├── rag.py           # Chroma arama → rerank → JSON cevap → kanıt eşleştirme
│   ├── dogrulama.py     # lexical rerank, dönem çıkarımı, kanıt/atıf doğrulama
│   ├── akis.py          # LangGraph: niyet → {sql, rag, talep, reddet} → logla
│   ├── api.py           # FastAPI köprüsü (n8n vb. için HTTP)
│   ├── mcp_sunucu.py    # araçları MCP ile dışarı açar (mcp_istemci.py: araçları keşfedip çağıran istemci)
│   └── log.py           # loglar tablosuna yazma
├── scripts/
│   ├── 00_bordro_uret.py
│   ├── 01_veritabani_kur.py
│   ├── 02_belge_uret.py
│   ├── 03_indeksle.py
│   ├── soru_dene.py     # geliştirici için adım adım deneme aracı
│   ├── konsol_asistan.py, veri_goruntule.py   # terminalden sohbet ve veri görüntüleme
│   └── tool_calling_dene.py                   # tool calling denemesi
├── ui/
│   ├── streamlit_app.py # giriş, firma paneli (asistan, kartlar, yaklaşan ödemeler, sekmeler), muhasebeci paneli
│   └── grafik.py        # gelir–gider grafiği (Altair), aylık özet ve gider dağılımı
├── tests/               # pytest testleri (veritabanının geçici kopyasında, model gerekmez)
├── .streamlit/config.toml  # tema ve yalnızca 127.0.0.1'de çalışma ayarı
├── n8n/                 # n8n AI Agent sistem mesajı
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
- **Çalışan ve bordro verisi kurgusaldır** (`00_bordro_uret.py`, sabit seed); toplamlar muhtasar beyannameleriyle tutarlı olacak şekilde üretilmiştir.
- **Gecikme zammı tahminidir:** bugüne kadarki tutarı gösterir, ödeme günü ilerledikçe artar. Oran `.env`'den gelir ve güncel tutulmalıdır. SGK primi için tahmin verilmez; kesin tutarı vergi dairesi / SGK hesaplar.
- **Gelir–gider grafiği demo verisidir:** satış faturalarının bir kısmı grafik dengeli görünsün diye gidere oranla üretilmiştir; gerçek bir kârlılık göstergesi değildir.
- **Geçerli bir atıf, cevabın doğru olduğunu kanıtlamaz.** Kanıt eşleştirme yalnızca rakam ve tarihleri kontrol eder, cümlenin anlamını kontrol etmez.
- Vergi takvimi ve rehber metinleri **demo amaçlıdır**; resmi bilgi için GİB ve SGK duyurularına bakın.

## Yol haritası

- [x] Veritabanı, belge üretimi, indeksleme
- [x] SQL sorgu menüsü, niyet sınıflandırma, kaynaklı RAG, doğrulama
- [x] LangGraph akışı ve loglama
- [x] Streamlit arayüzü (giriş, firma paneli, muhasebeci onayı)
- [x] Kurumsal arayüz: gelir–gider grafiği, yaklaşan ödemeler, gider dağılımı, CSV indirme
- [x] Tahmini gecikme zammı ve gecikme zammı oranı cevabı
- [x] pytest birim testleri (130 test)
- [ ] n8n: onaylanan talep için e-posta, yaklaşan ödemeler için hatırlatma
- [ ] Toplu test scripti (Hit@3, Top1, ortalama süre)
- [ ] Temiz kurulum provası
