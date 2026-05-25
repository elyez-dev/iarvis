from core.user_settings import user_settings


class SettingsService:
    def __init__(self):
        self._user_settings = user_settings()

    def get_settings(self) -> dict:
        return self._user_settings.settings

    def update_setting(self, key: str, value: str) -> dict:
        self._user_settings.update_setting(key, value)
        return self._user_settings.settings
