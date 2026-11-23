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
| "Son beyannamemi e-postama gönder." | Talep **"Onay bekliyor"** olarak kaydedilir; e-posta ancak muhasebeci onaylayınca, n8n ile ve yalnız **kayıtlı** adrese gider (belge ekli) | Talepler → n8n |
| "Beyannamemi gönder" → *"Hangi beyanname?"* → "KDV" → *"Hangi dönem?"* → "Eylül" → *"Onaylıyor musunuz?"* → "evet" | **Çok adımlı sohbet:** eksik bilgi tek tek sorulur, özet gösterilir, onaydan sonra kayıt açılır (LangGraph `interrupt` + SQLite checkpoint; atölye 7. gün) | Talepler / planlı kayıtlar |
| "3 numaralı talebim ne durumda?" / "Taleplerim ne oldu?" | Talep durumu sorgulama (yalnız kendi firmasının talepleri) | Talepler tablosu |
| "Hangi hisseyi alayım?" | Nazikçe reddedilir | — |
| "Demo Yazılım'ın KDV'si ne kadar?" | Başka firmanın verisi **asla** verilmez | — |
| "Aralıkta planladığım ödemeler neler?" / "Ne kadar tahsilat bekliyorum?" / "Aralık nakit planım" | Kullanıcının **kendi eklediği** planlı ödeme ve tahsilatlar; nakit planında giriş, çıkış ve net | SQLite (`planli_islemler`) |
| "Ekim faturalarımı göster" | Ayın alış ve satış faturaları; alış ve satış toplamları **ayrı** verilir | SQLite (`faturalar`) |
| "Kaç kişi çalışıyor?" / "Çalışanlar kimler?" / "Şoförlere ne kadar maaş ödedim?" | Çalışan listesi, kıdem, görev bazında maaş toplamları ve karşılaştırmalar (hesabı Python yapar) | SQLite (`calisanlar`, `bordrolar`) |
| "Gecikmiş ödemelerimin faizi ne kadar?" / "Geciken ödemeler faizleriyle toplam ne kadar?" | Gecikmiş borçlar, kaç gün geciktiği ve **tahmini gecikme zammı** (ana borç × aylık oran / 30 × gün) ile toplam. SGK primi için tahmin verilmez (gecikme cezası + zammı SGK hesaplar) | SQLite + resmî oran (`.env`) |
| "Finansal sağlık puanım kaç, neden düşük?" / "Şirketim nasıl gidiyor?" | 0–100 sağlık puanı, bileşenleri, göstergeler ve puanı en çok düşüren iki alan için öneri | Kayıtlar (app/analiz.py) |
| "En çok satış yaptığım müşteri kim?" / "En büyük tedarikçim?" / "Ege Otel Grubu ekstresi" | Müşteri/satıcı dağılımı (pay, tutar, fatura sayısı) ya da adı geçen carinin özeti ve son işlemleri | SQLite (`faturalar`) |
| "Satışlar %10 düşerse 6 ay sonra durumum ne olur?" / "2 kişi işe alırsam?" / "Maliyetler %5 artarsa 1 yıl sonra?" | Yüzde, yön, kişi sayısı ve süreyi **kod** sorudan okur; mevcut gidişat ile senaryonun birikmiş nakdi ve farkı | Kayıtlar (senaryo) |
| "Nelere dikkat etmeliyim?" / "Riskler neler?" | Panel uyarıları önem sırasıyla (gecikme, yaklaşan son tarih, müşteri yoğunlaşması, eksi ay, planlı ödeme) | Kayıtlar |
| "Gecikme zammı oranı nedir?" / "Nasıl hesaplanır?" | Resmî oran (aylık %3,7; 6183 s. Kanun md. 51, 13.11.2025'ten beri), günlük oran ve örnek hesap | Resmî oran (`.env`) |

**Arayüz (Streamlit):** sade, kurumsal bir tasarım (lacivert–gri tema, ince çerçeveli kartlar, emoji yerine ikonlar; tema `.streamlit/config.toml` içinde).
- **Giriş ekranı:** solda ürün tanıtımı, sağda oturum açma kartı; demo hesapları açılır kutuda.
- **Yan menü:** kullanıcı bilgisi ve firma künyesi (unvan, tür, sektör, vergi no, çalışan sayısı), çıkış.
- **Firma paneli:**
  - **Asistan** sol üstte, sayfa açılır açılmaz (yazma kutusu dahil) ekranda görünür; sohbet alanının yüksekliği ekran boyuna göre ayarlanır. "Sık sorulanlar" butonları son mesajın altındadır. Her cevabın altında hangi yoldan (sql/rag) ve hangi kaynaktan geldiği yazar. Onay sorularında **Evet / Hayır** butonları çıkar.
  - **Uyarılar** (sağ üstte): gecikmiş ödemeler (kırmızı), 7 gün içinde son tarihi gelenler, tek müşteriye bağımlılık (satışların %35'i ve üstü), gideri gelirinden fazla aylar, 30 gün içindeki planlı ödemeler; yoksa "Her şey yolunda".
  - **Özet kartları:** bu ay ödenecek, geciken ödeme, en yakın son tarih, seçilen dönemin net durumu (artı/eksi).
  - **Gelir–gider grafiği:** gelir sıfırın üstünde, gider altında, koyu çizgi ayın neti. Dönem seçimi (son 3 ay / son 6 ay / tümü), toplam gelir–gider–net özeti, **gider dağılımı** (vergi/prim, maaş, alış faturaları) ve tablo görünümü (CSV indirilebilir). Gelir = satış faturaları + planlı tahsilatlar; gider = alış faturaları + **net** maaşlar + vergi/prim + planlı ödemeler (maaşta net kullanılır, çünkü SGK ve muhtasar kesintileri zaten vergi/prim olarak sayılır). İleri tarihli aylar açık renkle "plan" olarak gösterilir.
  - **Yaklaşan ödemeler:** ödenmemiş vergi/prim ve planlı ödemeler tarih sırasıyla; "4 gün gecikti" (kırmızı), "5 gün kaldı" (7 gün kalınca sarı).
  - **Nakit akış tablosu** (hocanın Excel "N.AKIŞI" sayfası örnek alındı): satırlar **kodlu kalemler** (10 müşteri tahsilatları — her müşteri ayrı satır, 19 planlı tahsilat; 37 personel maaşları, 38 SGK, 52 muhtasar, 53 KDV, 54 geçici vergi, 58 satıcılar — her satıcı ayrı satır, 70 planlı ödeme), sütunlar **aylar**. Önceki dönemden devir, TOPLAM TAHSİLAT, TOPLAM ÖDEME, NET NAKİT AKIŞI ve kümülatif satırları; ödemeler eksi ve kırmızı, ileri tarihli aylar "Plan". Dönem (son 3 / 6 ay / tümü) ve müşteri/satıcı kırılımı seçilebilir. **Excel olarak indir:** biçimlendirilmiş `.xlsx` (Nakit Akış, filtreli ve `SUBTOTAL` toplamlı Hareket, Kodlar sayfaları).
  - **Hareket dökümü** (Excel "HAREKET" sayfası karşılığı): faturalar, maaş ödemeleri, vergi/prim ve planlı kayıtlar tek listede — tarih, vade, giriş/çıkış, kod, kalem, işlem, karşı taraf, tutar, durum (Gerçekleşti / Bekliyor / Gecikti / Plan). Ay, yön, kalem ve metin araması ile filtrelenir; seçime göre giriş, çıkış ve net toplamı.
  - **Ödeme takvimi:** ay takvimi; her gün hücresinde o gün son tarihi olan vergi/prim ve planlı kayıtlar durum renginde (gecikti / bekliyor / ödendi / plan / tahsilat), üzerine gelince ayrıntı; bugün çerçeveli.
  - **Cari hesaplar:** müşteri ve satıcı bazında toplam, pay (çubukla), fatura sayısı, ortalama fatura, ilk/son işlem; seçilen cari için **cari hesap ekstresi** (yürüyen toplamla). Tek müşteri %35'i geçerse uyarı.
  - **Alacaklar:** tahsil edilmemiş satış faturaları (açık alacak), vadesi geçenler, **alacak yaşlandırması** (vadesi gelmemiş / 1–30 / 31–60 / 60+ gün), müşteri bazında **ortalama tahsil süresi**, vadeden sonraki ortalama gecikme ve vadesinde ödeme oranı, alacak devir süresi (açık alacak / son 90 günün günlük satışı). Vadesi geçmiş alacak uyarılara düşer (60 günü geçen varsa kritik). Nakit akışında satış parası **tahsil günü** girer; tahsil edilmemiş fatura vergi borçları gibi vadesinde "Bekliyor/Gecikti" görünür ve birikmiş nakde sayılmaz.
  - **Finansal sağlık:** 0–100 **demo sağlık puanı** (zamanında ödeme 25, kârlılık 25, gecikme 20, müşteri dağılımı 15, nakit dayanıklılığı 15; her bileşen ve formülü ekranda) ve göstergeler: net marj (kesilen satış faturaları − ödenen giderler; kârlılık satışa, nakit dayanıklılığı tahsil edilen paraya göre), gelir büyümesi, personel gider oranı, vergi yükü, zamanında ödeme oranı, nakit dayanıklılığı (birikmiş nakit kaç aylık gideri karşılıyor). Resmî bir derecelendirme değildir.
  - **Senaryo ("ne olur?"):** satış (%), satıcı maliyeti (%) ve personel sayısı (kişi) kaydırıcılarıyla 3/6/12 aylık birikmiş nakit projeksiyonu; mevcut gidişat ile senaryo aynı grafikte. Taban son 3 tamamlanmış ayın ortalaması; varsayımlar ekranda yazılı.
  - **Aylık rapor (PDF):** seçilen tamamlanmış ay için üç sayfalık yönetici raporu: ayın tahsilat/ödeme/neti (önceki aya göre değişim), dikkat edilmesi gerekenler, son 6 ay gelir–gider grafiği, ayın kalem dağılımı, en büyük 5 müşteri ve satıcı, 6 aylık nakit akış tablosu, finansal sağlık puanı ve bileşenleri, geciken ve 30 gün içinde ödenecekler, açık alacaklar (tahsil edilmemiş satış faturaları). Rakamlar paneldeki fonksiyonlardan gelir (`app/rapor.py`, testle karşılaştırılır); model rakam üretmez. Geçen ayın raporu yan menüden tek tıkla da indirilir.
  - **Diğer sekmeler:** yükümlülükler (üstte ödenmemiş borçların **yaşlandırması**: vadesi gelmemiş / 1–30 / 31–60 / 60+ gün gecikmiş; tablo durum renkli, CSV), planlı ödeme / tahsilat ekleme formu ve listesi (CSV), taleplerim. Sekmeler sabit yüksekliktedir; sekme değişince sayfa kaymaz.
  - Nakit akış tablosu ve gelir–gider grafiği aynı kaynakları kullanır; ay ay netleri birebir aynıdır (testle kontrol edilir).
- **Muhasebeci paneli:** **tüm firmaların vergi takvimi** (ay takviminde firma adıyla) ve **yaşlandırma tablosu** (firma × gecikme kovası), **firma portföyü** (tüm müşteri firmalar tek tabloda: bu ay ödenecek, geciken, en yakın son tarih, son 3 ayın neti, bekleyen talep ve durum rozeti; altında firma seçilip **Paneli aç** ile firmanın paneline **salt okunur** girilir ya da **aylık PDF raporu** indirilir), bekleyen talep ve e-posta kuyruğu sayısı, onay bekleyen talepler (ne onaylandığının özetiyle), **Onayla / Reddet**; onay tek kullanımlık token ile gönderime alınır ve e-postası n8n ile hemen gönderilir. **E-posta kuyruğu** bölümü n8n'in açık/kapalı olduğunu ve henüz gitmemiş e-postaları gösterir. Her adım denetim kaydına yazılır.

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

ONAY YOLU (app/onay.py → app/bildirim.py → n8n)
  Muhasebeci paneli ─ Onayla ─> tek kullanımlık token ─> gonderimler: 'Kuyrukta'
     └─> POST localhost:5678/webhook/talep-onay (belge ek olarak) ─> n8n "Send Email" ─> 'Gönderildi', talep 'Tamamlandı'
         n8n kapalıysa gönderim 'Kuyrukta' kalır; panelden "Kuyruktaki e-postaları gönder" ile tekrar denenir

HATIRLATMA (scripts/05_hatirlatma.py → n8n)
  Ödenmemiş: gecikmiş + son tarihine ≤3 gün kalan ─> POST /webhook/hatirlatma ─> firmanın kayıtlı adresine e-posta

ZAMANLAYICI (n8n Schedule Trigger → Execute Command → n8n/gorev.sh)
  Her sabah 09:00 ─> gorev.sh hatirlatma  ─> scripts/05_hatirlatma.py ─> /webhook/hatirlatma
  Her ayın 1'i 08:30 ─> gorev.sh aylik-rapor ─> scripts/06_aylik_rapor.py --gonder ─> /webhook/aylik-rapor (PDF ekli)
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
| Arayüz | Streamlit (grafik: Altair; Excel raporu: openpyxl; PDF raporu: fpdf2) |
| Parola | bcrypt |
| Otomasyon | n8n 2.x (onay e-postası ve ödeme hatırlatması; webhook → Send Email) |

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
- **Girişte deneme sınırı:** bir e-posta için 15 dakika içinde 5 hatalı denemeden sonra hesap 15 dakika girişe kapanır; kilit süresince doğru şifre de kabul edilmez. Sayaç veritabanındadır (`giris_denemeleri`), sayfayı yenilemek sıfırlamaz; başarılı giriş sıfırlar. Kayıtlı olmayan e-postalar da aynı şekilde sayılır ve aynı sürede cevap alır (e-postanın kayıtlı olup olmadığı anlaşılmaz). Ödünleşim: biri bilerek yanlış şifre girerek bir hesabı 15 dakika kilitleyebilir (`app/db.py`, `AZAMI_DENEME`, `KILIT_DAKIKA`).
- **n8n webhook anahtarı:** üç webhook (`talep-onay`, `hatirlatma`, `aylik-rapor`) yalnızca `X-Muhasebe-Anahtar` başlığında doğru anahtarı taşıyan isteği kabul eder, gerisini 403 ile reddeder; böylece bilgisayardaki başka bir program uygulama adına e-posta gönderemez. Anahtar `.env`'de (`N8N_WEBHOOK_ANAHTARI`) durur, GitHub'a gitmez; `n8n/kur.sh` yoksa üretip `.env`'e ve n8n'e yazar. Anahtar eşleşmezse e-posta kuyrukta bekler ve panel nedenini söyler.
- **Muhasebeci görünümü salt okunurdur:** muhasebeci portföyden bir firmanın panelini açabilir; yetki her çizimde koddan denetlenir (`db.erisilebilir_firma`: firma yetkilisi yalnızca kendi firmasını, muhasebeci kayıtlı firmaları görür), asistan ve kayıt ekleme/silme bu görünümde kapalıdır ve her açılış denetim kaydına yazılır (`onay.firma_dosyasi_ac`).
- Analiz soruları (sağlık puanı, cari, senaryo, uyarılar) modele gitmeden **kodla** tanınır ve cevaplanır (`app/analiz_sorulari.py`); rakamlar paneldeki sekmelerle aynı fonksiyonlardan gelir. "2 kişi işe alırsam" gibi koşullu cümleler senaryodur, geçmiş işe alım (bordro) sorusu değildir.
- Kayıt cevaplarında uydurma sayı, eksik ana rakam ya da "ödendi/ödenmedi" çelişkisi varsa model cevabı atılır ve şablon cevap kullanılır.
- Belge cevaplarında cevaptaki her tutar ve tarih kaynak belgede **birebir** geçmek zorundadır (kanıt eşleştirme). Kaynak, bu kanıtı içeren dosya olarak belirlenir.

---

## Kurulum

### Gereksinimler
- Python 3.11 veya üzeri
- [Ollama](https://ollama.com) (çalışır durumda, `http://localhost:11434`)
- (İsteğe bağlı, e-posta için) n8n: Node.js ile `npx n8n` (bkz. aşağıdaki "E-posta (n8n)" bölümü) ya da Docker ile `docker compose up -d`

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

Faturalar (`data/csv/faturalar.csv`, 98 kayıt): Eylül–Ekim 2026 alış/satış örnekleri (24) ve gelir–gider grafiği dengeli görünsün diye eklenen Mayıs–Kasım 2026 satış faturaları (63; her ayın satış toplamı o ayın giderinin 0,92–1,18 katı) ve 11 açılış alacağı (Mart–Nisan; Mayıs'tan sonra tahsil edilen). Satış faturalarında **vade** ve **tahsil** tarihi vardır (`scripts/08_alacak_verisi.py`, sabit tohumlu): her müşterinin bir ödeme profili var (15–60 gün vade; kimi vadesinde, kimi geç öder), 3 fatura bilerek hiç tahsil edilmemiştir. Mevcut veritabanında yeni kolonlar ilk bağlantıda kendiliğinden eklenir (`db.fatura_vadelerini_guncelle`). Kurgusal çalışan ve bordro verisi (`data/csv/calisanlar.csv`, `bordrolar.csv`) depoda hazırdır; `01` bunları da yükler. Yeniden üretmek için `python scripts/00_bordro_uret.py` (sabit seed, her seferinde aynı veri; brüt toplam = muhtasar / 0,15, gelir vergisi toplamı = muhtasar). Mevcut bir veritabanında tablolar ilk bağlantıda kendiliğinden eklenir, veri silinmez.

**Bugünün tarihi:** Asistan varsayılan olarak gerçek tarihi kullanır. Son ödeme tarihi geçmiş ve ödenmemiş kayıtlar otomatik olarak "Gecikti" sayılır; "bu ay / geçen ay / yaklaşan" buna göre hesaplanır. Sunum için senaryo gününü sabitlemek isterseniz `.env` dosyasına `BUGUN=2026-11-11` yazın. Testler (`pytest`) her zaman senaryo gününde çalışır (`tests/conftest.py`).

**Gecikme zammı oranı:** Tahmini gecikme zammı hesabı ve "gecikme zammı oranı nedir" cevabı `.env` dosyasındaki oranı kullanır (varsayılan aylık %3,7, yürürlük 13.11.2025). Oran Cumhurbaşkanı kararıyla değişirse kod değiştirmeden güncelleyin:

```
GECIKME_ZAMMI_AYLIK=3.7
GECIKME_ZAMMI_TARIH=13.11.2025
```

### E-posta (n8n)

Muhasebeci bir talebi onaylayınca belge e-postasını, ödeme hatırlatmalarını da **n8n** gönderir. Python yalnızca ne gönderileceğini hazırlar (`app/bildirim.py`); SMTP ayarı n8n'dedir, kodda e-posta şifresi tutulmaz. Demo adresleri (`@demo.local`) gerçek olmadığı için e-postalar bilgisayardaki **test posta kutusuna** düşer; hiçbir e-posta dışarı gitmez.

Bir kez kurulum (n8n kapalıyken; SMTP kimliği ve iki akış içe aktarılır, akışlar yayınlanır):

```bash
bash n8n/kur.sh
```

Her kullanımda iki ayrı terminalde:

```bash
python scripts/test_posta_kutusu.py   # 127.0.0.1:1025 — gelen e-postalar data/posta_kutusu/*.eml
bash n8n/baslat.sh                    # n8n: http://localhost:5678 (yalnızca bu bilgisayardan erişilir)
```

Sonra muhasebeci panelinde **Onayla**ya basın: e-posta hemen gönderilir ve test posta kutusu terminalinde görünür. n8n kapalıyken onaylanan talepler kaybolmaz; panelin **E-posta kuyruğu** bölümünde bekler ve "Kuyruktaki e-postaları gönder" ile gönderilir. Ödeme hatırlatması:

```bash
python scripts/05_hatirlatma.py --dene   # e-posta göndermeden metinleri göster
python scripts/05_hatirlatma.py          # her firmaya, gecikmiş + 3 gün içinde son tarihi olan ödemeler
```

| Dosya | Görevi |
|---|---|
| `n8n/akislar.json` | Beş akış: `Webhook (talep-onay)` → `Send Email` (belge ekli), `Webhook (hatirlatma)` → `Send Email`, `Webhook (aylik-rapor)` → `Send Email` (PDF ekli, muhasebeci CC); zamanlayıcılar: `Schedule (her sabah 09:00)` → `Execute Command` (hatırlatma), `Schedule (her ayın 1'i 08:30)` → `Execute Command` (aylık rapor) |
| `n8n/gorev.sh` | Zamanlayıcının çağırdığı tek giriş noktası: yalnızca `hatirlatma` ve `aylik-rapor` görevlerini çalıştırır (başka komut reddedilir), çıktıyı `data/gorevler.log`'a da yazar |
| `n8n/webhook_anahtari.json.ornek` | Webhook'ların başlık kimliği (`X-Muhasebe-Anahtar`); değer `kur.sh` tarafından `.env`'den doldurulur, depoda anahtar yoktur |
| `n8n/test_posta_kimligi.json` | n8n SMTP kimliği: `127.0.0.1:1025`, şifresiz (yalnız test posta kutusu için) |
| `n8n/kur.sh`, `n8n/baslat.sh` | İçe aktarma/yayınlama ve n8n'i yalnız `127.0.0.1`'de başlatma |
| `scripts/test_posta_kutusu.py` | Ek paket gerektirmeyen küçük SMTP sunucusu; e-postaları `.eml` olarak kaydeder |

**Gerçek e-posta göndermek için** n8n arayüzünde (Credentials) "Test posta kutusu (yerel)" kimliğini kendi SMTP hesabınızla (ör. Gmail uygulama şifresi) değiştirin ve firmaların kayıtlı adreslerini gerçek adreslerle güncelleyin; Python kodu değişmez.

**Bellek:** Proje 6 GB RAM'li bir makinede geliştirildi. n8n belleği doldurunca sistem başka programları kapatabildiği için `kur.sh` ve `baslat.sh`, `systemd-run` varsa n8n'i bellek sınırlı bir "kafeste" çalıştırır (varsayılan 900 MB; `N8N_BELLEK=1200M bash n8n/baslat.sh` ile değiştirilir). Sınır aşılırsa yalnızca n8n durur. Gerekirse önce tarayıcı sekmelerini ve fazladan açık Streamlit pencerelerini kapatın.

**Zamanlayıcı:** n8n açık olduğu sürece her sabah 09:00'da hatırlatma, her ayın 1'inde 08:30'da geçen ayın PDF raporu (firmaya, muhasebeci CC) kendiliğinden gönderilir (saat dilimi Europe/Istanbul). n8n o saatte kapalıysa o günün görevi atlanır; elle çalıştırmak için `bash n8n/gorev.sh hatirlatma` ya da `bash n8n/gorev.sh aylik-rapor`. Her çalıştırma yeni bir Python sürecidir, "bugün" tarihi her seferinde doğru hesaplanır; sonuçlar n8n "Executions" ekranında ve `data/gorevler.log`'da görünür. Zamanlayıcı n8n'in *Execute Command* düğümünü kullanır; n8n 2.x bu düğümü varsayılan olarak kapatır, `baslat.sh` ve `kur.sh` yalnızca bu düğümü açar (`NODES_EXCLUDE`). Güvenlik için n8n yalnızca `127.0.0.1`'de dinler ve düğüm yalnızca `gorev.sh`'yi sabit bir görev adıyla çağırır. Akışlar değiştiyse n8n kapalıyken `bash n8n/kur.sh` yeniden çalıştırılır.

### Aylık yönetici raporu (PDF)

Arayüzde **Aylık rapor** sekmesinden (muhasebeci: firma portföyünün altından) indirilir. Tüm firmalar için toplu üretmek:

```bash
python scripts/06_aylik_rapor.py                 # geçen ay, tüm firmalar -> data/raporlar/
```

```bash
python scripts/06_aylik_rapor.py --ay 2026-09 --firma F001
```

```bash
python scripts/06_aylik_rapor.py --gonder        # ayrıca e-postayla gönder (n8n ve test posta kutusu açık olmalı)
```

PDF `fpdf2` ile üretilir; Türkçe karakterler için DejaVu Sans yazı tipi `app/fonts/` klasöründedir (serbest lisans, `LICENSE-DejaVu.txt`).

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
- Finansal sağlık puanım kaç, neden düşük?
- En çok satış yaptığım müşteri kim?
- Satışlar %10 düşerse 6 ay sonra durumum ne olur?
- Nelere dikkat etmeliyim?
- Ekim faturalarımı göster.
- Gecikmiş ödemelerimin faizi ne kadar?
- Gecikme zammı oranı nedir?

---

## Testler ve kontroller

**Birim testleri (model gerekmez, birkaç saniye):**

```bash
python -m pytest -q            # 326 test: niyet kuralları, kayıt cevapları, onay/token, e-posta köprüsü, nakit akış tablosu, analizler, aylık PDF raporu, muhasebeci görünümü, zamanlayıcı, güvenlik, ölçüm kuralları, alacak takibi, planlı kayıtlar, sohbet akışı
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

**Toplu ölçüm (tek komut):** test setindeki 15 soru gerçek asistana (model dahil) sorulur; niyet doğruluğu, Hit@3 ve Top1, cevap doğruluğu, başka firma verisi sızıntısı, onaysız işlem ve süre ölçülür. Ayrıntı `data/sonuclar.csv`'ye yazılır; hedef (Hit@3 ≥ %90, sızıntı 0, onaysız işlem 0) tutmazsa çıkış kodu 1'dir. Veritabanının geçici kopyasında çalışır, gerçek onay kuyruğuna talep düşmez. Ollama açık olmalı; Streamlit'i kapatın.

```bash
python scripts/04_test_calistir.py               # 15 soru, ~3-5 dakika
```

```bash
python scripts/04_test_calistir.py --id T01,T06  # yalnızca seçilen sorular
```

Puanlama kuralları `app/olcum.py`'dedir (atölye `d6_04_eval.py` karşılığı: belge sorularında beklenen dosya aramanın ilk 3 / ilk 1 parçasında mı; kayıt sorularında beklenen kayıt kimlikleri cevabın kaynaklarında mı; tutar ve tarihler cevapta aynen geçiyor mu).

**Son ölçümler** (`qwen2.5:1.5b`, CPU):

| Kontrol | Sonuç |
|---|---|
| Niyet sınıflandırma (test seti T01–T15) | 15/15 |
| Kayıt cevapları (T01–T05, T12, T13 + kullanıcı testlerinden 8 ek soru) | 15/15 |
| Birim testleri (`pytest`) | 326/326 |
| Belge cevapları (T06–T09, T15 + var olmayan dönem) | 6/6 |
| **Toplu ölçüm** (`scripts/04_test_calistir.py`, 15 soru, 23.11.2026) | Niyet 15/15 · **Hit@3 10/10** · Top1 3/5 · cevap 15/15 · sızıntı 0 · onaysız işlem 0 |
| Cevap süresi (aynı ölçüm, model yüklüyken) | ortalama 2,9 sn · medyan 2,1 sn · en uzun 8,1 sn (ilk soru model yüklenirken ~30 sn) |
| Firma izolasyonu (3 hesap, arayüz) | Her firma yalnızca kendi verisini görüyor |

Top1 3/5: T06 ve T07'de beklenen beyanname aramanın ilk 3 parçasında ama 1. sırada değil (önde vergi takvimi / aynı ayın KDV beyannamesi); cevap yine doğru dosyadan verilir, çünkü beyanname soruları dosya adıyla da eşleştirilir. Test setindeki T04'ün beklenen tarihi, son ödeme günlerinin resmî tatile göre kaydırılmasından sonra 31.10.2026'dan 02.11.2026'ya güncellendi. T12'de asistan başka firmayı soran soruyu modele göndermeden kodla reddeder (niyet `baska_firma`); ölçümde kayıt niyetine eşdeğer sayılır.

Not: Test seti küçüktür (15 soru) ve prompt'lar bu sorular gözetilerek iyileştirilmiştir. Arayüzde denenen farklı sorular hata bulmaya devam etmektedir; bulunan her hata kalıcı test olarak eklenir (`EK1`–`EK8` ve `tests/` altındaki pytest testleri).

---

## Klasör yapısı

```
muhasebe-asistani/
├── app/
│   ├── config.py        # ayarlar (.env), yollar, chunk boyutu, "bugün", gecikme zammı oranı
│   ├── db.py            # SQLite: SORGULAR menüsü, calistir(), talepler, giriş (bcrypt + deneme sınırı), grafik verisi
│   ├── niyet.py         # soru → {niyet, sorgu, parametreler} + kod kuralları
│   ├── kayit.py         # SQL sonucu → cevap (toplam Python'da, şablon/denetim), gecikme zammı hesabı
│   ├── bordro.py        # çalışan / maaş / bordro soruları
│   ├── emirler.py       # emir menüsü (belge gönder, planlı kayıt, görüşme) ve alan çıkarımı
│   ├── onay.py          # insan onayı, tek kullanımlık token, denetim kaydı
│   ├── bildirim.py      # n8n köprüsü: onay e-postası (kuyruk, tekrar deneme), ödeme hatırlatması
│   ├── nakit.py         # hareket dökümü ve nakit akış tablosu (kod planı, kod × ay matrisi, devir, kümülatif)
│   ├── alacak.py        # alacak takibi: açık alacaklar, yaşlandırma, müşteri bazında tahsil süresi, alacak devir süresi
│   ├── analiz.py        # uyarılar, ödeme takvimi, yaşlandırma, cari hesap/ekstre, finansal sağlık puanı, senaryo
│   ├── olcum.py         # toplu ölçümün puanlama kuralları (Hit@3, Top1, cevap, sızıntı, süre)
│   ├── rapor.py         # aylık yönetici raporu: veriyi toplar (rapor_verisi) ve PDF'e yazar (rapor_pdf, fpdf2)
│   ├── fonts/           # DejaVu Sans (PDF'te Türkçe karakterler için)
│   ├── analiz_sorulari.py # bu analizleri sohbetten sorulabilir yapar: soru kalıbı + kodla üretilen cevap
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
│   ├── 04_test_calistir.py # toplu ölçüm: test seti -> data/sonuclar.csv + özet (Hit@3, Top1, süre)
│   ├── 05_hatirlatma.py # ödeme hatırlatma e-postaları (n8n; zamanlayıcı her sabah 09:00)
│   ├── 08_alacak_verisi.py # faturalara vade ve tahsil tarihi (müşteri ödeme profilleri, açılış alacakları)
│   ├── 06_aylik_rapor.py # tüm firmaların aylık PDF raporu (data/raporlar/)
│   ├── test_posta_kutusu.py  # yerel test SMTP sunucusu (127.0.0.1:1025)
│   ├── soru_dene.py     # geliştirici için adım adım deneme aracı
│   ├── konsol_asistan.py, veri_goruntule.py   # terminalden sohbet ve veri görüntüleme
│   └── tool_calling_dene.py                   # tool calling denemesi
├── ui/
│   ├── streamlit_app.py # giriş, firma paneli (asistan, kartlar, yaklaşan ödemeler, sekmeler), muhasebeci paneli
│   ├── grafik.py        # gelir–gider grafiği (Altair), aylık özet ve gider dağılımı
│   ├── tablolar.py      # Excel benzeri nakit akış tablosu (HTML), .xlsx raporu, muhasebeci firma portföyü
│   └── analiz_gorunum.py # uyarı kartları, takvim ızgarası, sağlık puanı halkası, cari tablo, senaryo grafiği
├── tests/               # pytest testleri (veritabanının geçici kopyasında, model gerekmez)
├── .streamlit/config.toml  # tema ve yalnızca 127.0.0.1'de çalışma ayarı
├── n8n/                 # akislar.json, test_posta_kimligi.json, kur.sh, baslat.sh, gorev.sh (zamanlayıcı), AI Agent sistem mesajı
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
- **Sağlık puanı ve senaryo kural tabanlıdır:** formüller ekranda yazılıdır; banka bakiyesi verisi olmadığından "birikmiş nakit" kayıtlardaki gerçekleşen giriş–çıkış farkıdır (veri Mayıs 2026'da başlar, açılış bakiyesi yoktur). Büyüyen firmada tahsilat satışın gerisinde kaldığı için birikmiş nakit, kârlılığa göre düşük görünebilir; bu bilinçli olarak gösterilir ("büyüme nakit tüketir").
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
- [x] Nakit akış tablosu ve hareket dökümü (Excel indirme), muhasebeci firma portföyü
- [x] Uyarılar, ödeme takvimi, cari hesaplar, yaşlandırma, finansal sağlık puanı, senaryo simülatörü
- [x] Asistan analizlere bağlandı: sağlık puanı, cari, senaryo ve uyarı soruları sohbetten cevaplanır
- [x] Aylık yönetici raporu (PDF): firma panelinden, muhasebeci portföyünden ve komut satırından
- [x] Muhasebecinin firmaya girmesi: portföyden firmanın paneli salt okunur açılır, açılış denetime yazılır
- [x] Güvenlik: girişte deneme sınırı, n8n webhook'larında paylaşılan anahtar
- [x] Alacak takibi: vade ve tahsil tarihi, açık alacaklar, yaşlandırma, ortalama tahsil süresi; nakit akışı tahsil gününe göre
- [x] pytest birim testleri (326 test)
- [x] n8n: onaylanan talep için e-posta (belge ekli), yaklaşan/geciken ödemeler için hatırlatma
- [x] n8n zamanlayıcısı: her sabah 09:00 ödeme hatırlatması, her ayın 1'i aylık PDF raporu e-postası
- [x] Toplu ölçüm betiği: niyet, Hit@3, Top1, cevap doğruluğu, sızıntı, onaysız işlem, süre (`scripts/04_test_calistir.py`)
- [ ] Kasa ve banka bakiyesi girişi (birikmiş nakit tahmin yerine gerçek bakiyeyle)
- [ ] Excel'den hareket içe aktarma
- [ ] Temiz kurulum provası
