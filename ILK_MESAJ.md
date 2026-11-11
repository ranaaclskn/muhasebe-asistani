# Claude Code'a yapıştırılacak ilk mesaj

(Bu klasörü Claude Code'da açtıktan sonra aşağıdaki metni kopyalayıp gönder.)

---

Merhaba. Bu klasördeki CLAUDE.md dosyası projenin bütün bağlamı: Kişisel Muhasebe Asistanı, 17 Kasım'da teslim edilecek bir atölye final projesi. Önce CLAUDE.md'yi ve data/csv altındaki dosyaları oku, sonra bana 3-4 cümleyle ne anladığını ve 7. bölümdeki ilk adımları nasıl yapacağını özetle.

Ardından Adım 1 ve Adım 2'den başla:
1. docker-compose.yml, requirements.txt, .env.example dosyalarını oluştur; Ollama'nın bilgisayarımda zaten çalışıp çalışmadığını kontrol et (curl localhost:11434/api/tags), çalışıyorsa compose'a sadece n8n'i koy.
2. scripts/01_veritabani_kur.py'yi yaz ve çalıştır.

Her adımın sonunda CLAUDE.md'deki Kontrol satırını gerçekten çalıştır ve sonucu göster. Kontrol geçmeden bir sonraki adıma geçme. Paket kurmadan veya bir şey silmeden önce bana söyle.

---

Sonraki günler için örnek mesajlar:
- "Adım 3 ve 4'e geç: belgeleri üret ve indeksle."
- "Adım 5-7: SQL sorguları, niyet sınıflandırma ve RAG zinciri. Test setindeki T01–T07, T13 ve T15'i çalıştırıp sonuçları göster."
- "Adım 8: LangGraph akışını kur."
- "Adım 9: Streamlit arayüzü."
- "Adım 10-11: n8n akışları ve test scripti; sonuçları tablo olarak ver."
- "README'yi yaz ve temiz kurulumla bir kez baştan çalıştır."

Atölye 6. günden quality_utils.py dosyan varsa app/ klasörüne kopyala ve Claude Code'a "rerank ve atıf doğrulama için quality_utils.py'yi kullan" de.
