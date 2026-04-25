
import os


class settings:
    def __init__(self):
        self.debug = True
        self.database_url = "sqlite:///./test.db"
        self.n8n_url = os.getenv("N8N_WEBHOOK_URL", "http://n8n:5678/webhook-test")
        self.qdrant_url = os.getenv("QDRANT_URL", "http://qdrant:6333")
        self.ollama_url = os.getenv("OLLAMA_URL", "http://ollama:11434")
        self.default_timeout = 120.0