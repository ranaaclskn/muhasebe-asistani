"""RAG: Chroma'dan firma filtresiyle arama.

Atölye karşılığı: d5_03_embeddings.py (embedding_client) + d5_05_search.py (get_store, search).
Adım 7'de buraya rerank + kaynaklı cevap üretimi eklenecek.
"""
from langchain_chroma import Chroma
from langchain_ollama import OllamaEmbeddings

from app.config import CHROMA_DIR, EMBED_MODEL, KOLEKSIYON, OLLAMA_URL


def embedding_istemcisi():
    return OllamaEmbeddings(model=EMBED_MODEL, base_url=OLLAMA_URL)


def vektor_deposu():
    return Chroma(collection_name=KOLEKSIYON, embedding_function=embedding_istemcisi(),
                  persist_directory=str(CHROMA_DIR))


def firma_filtresi(firma_id):
    """Kural 2: firma_id KODDAN gelir; firma yalnızca kendi belgelerini + ORTAK rehberleri görür."""
    if not firma_id or firma_id == "ORTAK":
        raise ValueError("Geçerli bir firma_id gerekli")
    return {"firma_id": {"$in": [firma_id, "ORTAK"]}}


def ara(soru, firma_id, k=8, depo=None):
    """Soruya en yakın k parçayı (mesafe skoruyla) döndür: [(Document, mesafe), ...]"""
    depo = depo or vektor_deposu()
    return depo.similarity_search_with_score(soru, k=k, filter=firma_filtresi(firma_id))
