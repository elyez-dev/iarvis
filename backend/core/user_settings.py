
import json
import os

class user_settings:
    def __init__(self):
        self.config_dir = os.path.join(os.path.dirname(__file__), "../config")
        self.settings_file = os.path.join(self.config_dir, "user_settings.json")
        self.settings = self.load_settings()

    def load_settings(self):
        # load settings from a file, if it doesn't exist, return default settings
        try:            
            with open(self.settings_file, "r") as f:
                return json.load(f)
        except FileNotFoundError:  
            return {
                "Assistant_name": "IArvis",
                "Assistant_tone": "Professional",
                "notifications": True,
                "language": "Spanish",
                "language_code": "es",
            }

    def save_settings(self):
        # save settings to a file
        os.makedirs(self.config_dir, exist_ok=True)
        with open(self.settings_file, "w") as f:
            json.dump(self.settings, f)

    def update_setting(self, key, value):
        self.settings[key] = value
        self.save_settings()