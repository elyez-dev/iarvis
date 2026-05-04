import os


class settings:
    def __init__(self):
        self.debug = True
        self.n8n_url = os.getenv("N8N_WEBHOOK_URL", "http://n8n:5678/webhook-test")
        self.qdrant_url = os.getenv("QDRANT_URL", "http://qdrant:6333")
        self.ollama_url = os.getenv("OLLAMA_URL", "http://ollama:11434")
        self.qdrant_collection = os.getenv("QDRANT_COLLECTION", "long_term_memory")
        self.embedding_model = os.getenv("EMBEDDING_MODEL", "nomic-embed-text:latest")
        self.rag_score_threshold = float(os.getenv("RAG_SCORE_THRESHOLD", "0.6"))
        self.rag_dedupe_threshold = float(os.getenv("RAG_DEDUPE_THRESHOLD", "0.95"))
        self.default_timeout = 120.0
