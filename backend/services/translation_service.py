import json
import os
from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

# Load language mappings from JSON
def load_language_map():
    config_path = os.path.join(os.path.dirname(__file__), "../config/languages.json")
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"Language mapping file not found: {config_path}")
    except json.JSONDecodeError:
        raise ValueError(f"Invalid JSON in language mapping file: {config_path}")

NLLB_LANG_MAP = load_language_map()

class TranslationService:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            #singleton pattern to ensure only one instance of the model is loaded
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        print("Cargando modelo multilingüe NLLB-200 (CPU)...")
        model_name = "facebook/nllb-200-distilled-600M"
        self.tokenizer = AutoTokenizer.from_pretrained(model_name)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(model_name).to("cpu")
        self._initialized = True
        print("NLLB cargado y listo en RAM.")

    def translate(self, text: str, src_lang: str, tgt_lang: str) -> str:
        # Si el idioma de origen y destino es el mismo, devolvemos el texto original
        if src_lang == tgt_lang:
            return text
            
        # Configuramos el tokenizer para el idioma de origen
        self.tokenizer.src_lang = src_lang
        inputs = self.tokenizer(text, return_tensors="pt", padding=True)
        
        # Generamos la traducción forzando el idioma de destino
        tgt_lang_id = self.tokenizer.lang_code_to_id[tgt_lang]
        translated_tokens = self.model.generate(
            **inputs, 
            forced_bos_token_id=tgt_lang_id,
            max_length=512 # Límite de seguridad para evitar cuelgues con textos muy largos
        )
        return self.tokenizer.batch_decode(translated_tokens, skip_special_tokens=True)[0]

# Lazy instantiation - only creates instance when actually used
def get_translator():
    return TranslationService()

# Eager instantiation - loads model at startup
translator = TranslationService()
