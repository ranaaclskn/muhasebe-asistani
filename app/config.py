"""Projenin tüm sabitleri tek yerde. Model adlarını .env dosyasından değiştir."""
import os
from pathlib import Path

from dotenv import load_dotenv

KOK = Path(__file__).resolve().parent.parent
load_dotenv(KOK / ".env")

VERI_DIR = KOK / "data"
CSV_DIR = VERI_DIR / "csv"
BELGE_DIR = VERI_DIR / "belgeler"
DB_YOLU = VERI_DIR / "muhasebe.db"
CHROMA_DIR = VERI_DIR / "chroma"
KOLEKSIYON = "muhasebe"

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
LLM_MODEL = os.getenv("LLM_MODEL", "qwen2.5:1.5b")
EMBED_MODEL = os.getenv("EMBED_MODEL", "embeddinggemma")
N8N_URL = os.getenv("N8N_URL", "http://localhost:5678")

BUGUN = "2026-11-11"  # Senaryonun "bugün"ü (CLAUDE.md §6)
# Token tabanlı parçalama (atölye d5_02 ile aynı: cl100k_base, 200/40 token).
# Türkçede ~2,1 karakter/token -> ≈420/84 karakter.
TOKENIZER = "cl100k_base"
CHUNK_BOYUT, CHUNK_ORTUSME = 200, 40  # TOKEN
