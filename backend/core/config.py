
class settings:
    def __init__(self):
        self.debug = True
        self.database_url = "sqlite:///./test.db"
        self.n8n_url = "http://n8n:5678/webhook-test"
        self.default_timeout = 120.0