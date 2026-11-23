"""Testler senaryo gününde (11.11.2026) çalışır: beklenen tutarlar ("bu ay 4 ödeme, 165.469,58 TL")
bu güne göre yazıldı. Uygulama ise varsayılan olarak GERÇEK tarihi kullanır (app/config.py).
Gerçek-tarih davranışı (gecikmiş sayılma) testlerde monkeypatch ile ayrıca denenir."""
import os

os.environ["BUGUN"] = "2026-11-11"  # app.config import edilmeden ÖNCE
# .env sunum ayarı (MUHASEBE_DB=data/demo.db) testlere sızmasın: testler geliştirme veritabanıyla çalışır
os.environ["MUHASEBE_DB"] = "data/muhasebe.db"
