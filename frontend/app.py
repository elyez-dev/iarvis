import os
import uuid
import time

import requests
import streamlit as st

from i18n import t as _t

BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")

TONES = ["Professional", "Friendly", "Concise", "Humorous", "Formal"]

DEFAULTS = {
    "Assistant_name": "IArvis",
    "Assistant_tone": "Professional",
    "language": "Spanish",
    "language_code": "es",
}

ACTION_ICONS = {"STORE": "💾", "SEARCH": "🔍", "TOOL": "🔧"}

# ── page config ────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="iArvis",
    page_icon="🤖",
    layout="centered",
    menu_items={
        "Get help": None,
        "Report a bug": None,
        "About": None,
    },
)

# ── CSS ────────────────────────────────────────────────────────────────────

st.markdown(
    """
    <style>
        /* --- 1. Ocultar elementos de Streamlit --- */
        #MainMenu {visibility: hidden;}
        footer {visibility: hidden;}
        [data-testid="stStatusWidget"] {display: none !important;}
        [data-testid="stToolbarActions"] {display: none !important;}

        /* --- 2. Estilos base para Notificaciones --- */
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] [class^="bg-"]) {
            transition: background-color 0.3s ease;
        }

        /* --- 3. Colores por tipo de acción --- */
        
        /* AZULITO: default, info, search */
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .bg-default),
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .bg-info),
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .bg-search) {
            background-color: #e6f2ff !important; 
        }

        /* VERDECITO: store */
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .bg-store) {
            background-color: #e6ffe6 !important;
        }

        /* NARANJITA: tool */
        div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .bg-tool) {
            background-color: #fff4e6 !important; 
        }
    </style>
    """,
    unsafe_allow_html=True,
)

# ── helpers ─────────────────────────────────────────────────────────────────


def _api(method, path, json_data=None, timeout=5):
    try:
        r = requests.request(
            method,
            f"{BACKEND_URL}{path}",
            json=json_data,
            timeout=timeout,
        )
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        return None, str(e)


def _save_setting(key, value):
    _, err = _api("PUT", "/frontend/settings", {"key": key, "value": value})
    if not err:
        st.session_state.settings[key] = value
    return err


def _build_language_list():
    """Fetch language codes from backend + i18n display names. Cache in session_state."""
    if "_lang_list" in st.session_state:
        return st.session_state._lang_list
    data, _ = _api("GET", "/frontend/languages")
    if not data:
        data = {"en": "eng_Latn", "es": "spa_Latn"}
    lang_names = _load_lang_names()
    result = []
    for code in sorted(data.keys()):
        display = lang_names.get(code, code)
        result.append((display, code))
    st.session_state._lang_list = result
    return result


def _load_lang_names():
    """Avoid circular import — load language_names from the i18n JSON directly."""
    import json, os as _os
    lang = st.session_state.get("settings", {}).get("language_code", "en") or "en"
    path = _os.path.join(_os.path.dirname(__file__), "i18n", f"{lang}.json")
    try:
        with open(path) as f:
            return json.load(f).get("language_names", {})
    except Exception:
        return {}


# ── session state init ──────────────────────────────────────────────────────

if "chat_id" not in st.session_state:
    st.session_state.chat_id = None
if "messages" not in st.session_state:
    st.session_state.messages = []
if "settings" not in st.session_state:
    data, _ = _api("GET", "/frontend/settings")
    st.session_state.settings = data if data else dict(DEFAULTS)
if "chats" not in st.session_state:
    st.session_state.chats = []
if "notifications" not in st.session_state:
    st.session_state.notifications = []
if "_polling_active" not in st.session_state:
    st.session_state._polling_active = False
if "_poll_start" not in st.session_state:
    st.session_state._poll_start = 0.0
if "_sending" not in st.session_state:
    st.session_state._sending = False
if "_pending_prompt" not in st.session_state:
    st.session_state._pending_prompt = None

# When language changes, update widget states so selectbox previews
# match the new translations (Streamlit stores the label text, not
# the index, so old-language labels persist across reruns).
if "_prev_lang" not in st.session_state:
    st.session_state._prev_lang = st.session_state.settings.get("language_code", "en")
_current_lang = st.session_state.settings.get("language_code", "en")
if st.session_state._prev_lang != _current_lang:
    theme = st.session_state.settings.get("theme", "light")
    st.session_state.s_theme = _t("theme.light") if theme == "light" else _t("theme.dark")
    tone = st.session_state.settings.get("Assistant_tone", "Professional")
    st.session_state.s_tone = _t(f"tone.{tone}")
    st.session_state._prev_lang = _current_lang


# ── sidebar ─────────────────────────────────────────────────────────────────

with st.sidebar:
    s = st.session_state.settings

    st.title(s.get("Assistant_name", DEFAULTS["Assistant_name"]))

    with st.expander(_t("settings.title"), key="settings_expander"):
        new_name = st.text_input(
            _t("settings.name"),
            value=s.get("Assistant_name", DEFAULTS["Assistant_name"]),
        )
        if new_name and new_name != s.get("Assistant_name"):
            _save_setting("Assistant_name", new_name)

        current_tone = s.get("Assistant_tone", DEFAULTS["Assistant_tone"])
        tone_labels = [_t(f"tone.{t}") for t in TONES]
        tone_idx = TONES.index(current_tone) if current_tone in TONES else 0
        new_tone_label = st.selectbox(
            _t("settings.tone"), tone_labels, index=tone_idx, key="s_tone"
        )
        new_tone = TONES[tone_labels.index(new_tone_label)]
        if new_tone != current_tone:
            _save_setting("Assistant_tone", new_tone)

        current_lang_code = s.get("language_code", DEFAULTS["language_code"])
        lang_list = _build_language_list()
        lang_labels = [x[0] for x in lang_list]
        lang_codes = [x[1] for x in lang_list]
        try:
            lang_idx = lang_codes.index(current_lang_code)
        except ValueError:
            lang_idx = 0
        new_lang_label = st.selectbox(
            _t("settings.language"), lang_labels, index=lang_idx, key="s_lang"
        )
        new_lang_code = lang_codes[lang_labels.index(new_lang_label)]
        if new_lang_code != current_lang_code:
            _save_setting("language_code", new_lang_code)
            _save_setting("language", lang_labels[lang_labels.index(new_lang_label)])
            st.session_state.pop("_lang_list", None)
            st.rerun()

        current_theme = s.get("theme", "light")
        theme_labels = [_t("theme.light"), _t("theme.dark")]
        new_theme_label = st.selectbox(
            _t("settings.theme"),
            theme_labels,
            index=0 if current_theme == "light" else 1,
            key="s_theme",
        )
        new_theme = "light" if new_theme_label == theme_labels[0] else "dark"
        if new_theme != current_theme:
            if new_theme == "dark":
                st._config.set_option("theme.base", "dark")
                st._config.set_option("theme.backgroundColor", "#0e1117")
                st._config.set_option("theme.secondaryBackgroundColor", "#262730")
                st._config.set_option("theme.textColor", "#fafafa")
            else:
                st._config.set_option("theme.base", "light")
                st._config.set_option("theme.backgroundColor", "#ffffff")
                st._config.set_option("theme.secondaryBackgroundColor", "#f0f2f6")
                st._config.set_option("theme.textColor", "#262730")
            _save_setting("theme", new_theme)
            st.rerun()

    st.divider()

    if st.button(_t("chat.new"), use_container_width=True):
        data, err = _api("POST", "/frontend/chats")
        if data:
            st.session_state.chat_id = data["chat_id"]
            st.session_state.messages = []
            st.session_state.notifications = []
            st.session_state._polling_active = False
            st.rerun()
        elif err:
            st.error(_t("chat.error", error=err))

    st.divider()

    data, _ = _api("GET", "/frontend/chats")
    st.session_state.chats = data["chats"] if data else []

    for chat in st.session_state.chats:
        active = chat["id"] == st.session_state.chat_id
        label = f"{'●' if active else '○'} {chat['title']}"
        if st.button(label, key=f"chat_{chat['id']}", use_container_width=True):
            if st.session_state.chat_id != chat["id"]:
                st.session_state.chat_id = chat["id"]
                st.session_state.notifications = []
                st.session_state._polling_active = False
                hist, _ = _api("GET", f"/frontend/chats/{chat['id']}/history")
                st.session_state.messages = hist["messages"] if hist else []
            st.rerun()

    if not st.session_state.chats and st.session_state.chat_id is None:
        st.caption(_t("chat.empty"))


# ── main chat area ─────────────────────────────────────────────────────────

st.title(st.session_state.settings.get("Assistant_name", DEFAULTS["Assistant_name"]))

# ── messages ─────────────────────────────────────────────────────────────────

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

if st.session_state.chat_id is None:
    st.info(_t("chat.prompt"))
else:
    prompt = st.chat_input(
        _t("chat.placeholder"), disabled=st.session_state._sending
    )
    if prompt:
        st.session_state._pending_prompt = prompt
        st.session_state._sending = True
        st.rerun()

    if st.session_state._pending_prompt is not None:
        prompt = st.session_state._pending_prompt
        st.session_state._pending_prompt = None
        st.session_state.messages.append({"role": "user", "content": prompt})
        st.session_state.notifications = []

        with st.chat_message("assistant"):
            with st.spinner(_t("chat.thinking")):
                data, err = _api(
                    "POST",
                    "/frontend/chat",
                    {"message": prompt, "chat_id": st.session_state.chat_id},
                    timeout=120,
                )
            if data:
                response = data["response"]
                st.markdown(response)
                st.session_state.messages.append(
                    {"role": "assistant", "content": response}
                )

                action_details = data.get("action_details", [])
                if action_details:
                    st.session_state.notifications = [
                        {
                            "id": str(uuid.uuid4()),
                            "type": ad["type"],
                            "summary": ad["summary"],
                            "detail": ad.get("detail"),
                        }
                        for ad in action_details
                    ]
                    st.session_state._polling_active = True
                    st.session_state._poll_start = time.time()
            else:
                st.error(err or _t("chat.error_response"))
            st.session_state._sending = False
            st.rerun()


# ── action notifications + polling (fragment) ────────────────────────────────

@st.fragment(run_every="5s")
def _action_panel():
    chat_id = st.session_state.chat_id
    polling = st.session_state._polling_active

    if polling and chat_id:
        elapsed = time.time() - st.session_state._poll_start
        if elapsed > 60:
            st.session_state._polling_active = False
        data, _ = _api(
            "GET",
            f"/frontend/actions/{chat_id}/pending",
            timeout=3,
        )
        if data and data.get("notifications"):
            seen_keys = {
                (n["type"], n["summary"]) for n in st.session_state.notifications
            }
            new = []
            for n in data["notifications"]:
                key = (n["type"], n["summary"])
                if key not in seen_keys:
                    new.append({
                        "id": str(uuid.uuid4()),
                        "type": n["type"],
                        "summary": n["summary"],
                        "detail": n.get("detail"),
                    })
                    seen_keys.add(key)

            if new:
                st.session_state.notifications.extend(new)
                _api("POST", f"/frontend/actions/{chat_id}/ack")

    notifications = st.session_state.notifications

    if not notifications:
        return

    for n in notifications:
        icon = ACTION_ICONS.get(n["type"], "ℹ️")
        detail_block = f"\n\n```\n{n['detail']}\n```" if n.get("detail") else ""
        action_label = _t(f"action.{n['type'].lower()}")
        notification_type = n.get("type", "default").lower()
        with st.container(border=True):
            st.markdown(f'<div class="bg-{notification_type}"></div>', unsafe_allow_html=True)
            col_text, col_btn = st.columns([0.90, 0.1], vertical_alignment="top")
            with col_text:
                st.markdown(
                    f"**{icon} {action_label}**\n\n{n['summary']}{detail_block}"
                )
            with col_btn:
                if st.button("✕", key=f"dismiss_{n['id']}"):
                    st.session_state.notifications = [
                        x for x in st.session_state.notifications if x["id"] != n["id"]
                    ]

_action_panel()
