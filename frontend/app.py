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

        div[data-testid="stElementContainer"]:has([data-hook="delete-memory"]) + div[data-testid="stElementContainer"] button[data-testid="stBaseButton-secondary"] {
            border-color: #dc3545 !important;
            color: #dc3545 !important;
            background-color: transparent !important;
            transition: all 0.3s ease !important;
        }

        div[data-testid="stElementContainer"]:has([data-hook="delete-memory"]) + div[data-testid="stElementContainer"] button[data-testid="stBaseButton-secondary"]:hover {
            background-color: #dc35451a !important;
            border-color: #b02a37 !important;
            color: #b02a37 !important;
        }

        /* --- 7. Arreglo Definitivo: Alineación Text Input y Botones de Edición --- */

        /* 1. Seleccionamos toda la fila horizontal que contiene el input de texto "_" */
        div[data-testid="stHorizontalBlock"]:has(input[aria-label="_"]) {
            align-items: center !important; /* Centrado vertical general */
        }

        /* 2. El Label Fantasma */
        div[data-testid="stHorizontalBlock"]:has(input[aria-label="_"]) label[data-testid="stWidgetLabel"] {
            display: none !important;
        }

        /* 2b. "Press enter to apply" — hide */
        [data-testid="stSidebar"] [data-testid="stTextInput"]:has(input[aria-label="_"]) [data-testid="InputInstructions"] {
            display: none !important;
        }

        /* 3. La clave: Forzar la altura de todos los VerticalBlocks (las columnas individuales) dentro de esa fila */
        div[data-testid="stHorizontalBlock"]:has(input[aria-label="_"]) > div[data-testid="stColumn"] > div[data-testid="stVerticalBlock"] {
            display: flex !important;
            justify-content: center !important;
            height: 100% !important; 
            gap: 0 !important; /* Quitamos cualquier espacio vertical inyectado */
        }

/* 4. Contenedores de botones sin margen extra */
        div[data-testid="stHorizontalBlock"]:has(input[aria-label="_"]) div[data-testid="stElementContainer"] {
            margin: 0 !important;
            padding: 0 !important;
        }

        /* --- 8. Responsive: wrap sidebar 3-columns on narrow screens --- */
        @media (max-width: 768px) {
            [data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] {
                flex-wrap: wrap !important;
                gap: 0.25rem !important;
            }
            [data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:first-child {
                flex: 1 1 100% !important;
                max-width: 100% !important;
                min-width: 0 !important;
            }
            [data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:nth-child(n+2) {
                flex: 1 1 calc(50% - 0.25rem) !important;
                max-width: calc(50% - 0.25rem) !important;
                min-width: 0 !important;
            }
            [data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:nth-child(n+2) div[data-testid="stElementContainer"] {
                width: 100% !important;
            }
            [data-testid="stSidebar"] div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"]:nth-child(n+2) button[data-testid="stBaseButton-secondary"] {
                width: 100% !important;
            }
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
    """Load language display names from i18n JSON."""
    import json, os as _os
    lang = st.session_state.get("settings", {}).get("language_code", "en") or "en"
    path = _os.path.join(_os.path.dirname(__file__), "i18n", f"{lang}.json")
    try:
        with open(path) as f:
            return json.load(f).get("language_names", {})
    except Exception:
        return {}


# ── delete memory dialog ─────────────────────────────────────────────────

@st.dialog(_t("settings.delete_memory"))
def _delete_memory_dialog():
    ts = st.session_state.get("_delete_ts", 0)
    remaining = max(0, 5 - int(time.time() - ts))

    st.error(_t("settings.delete_memory_confirm"))

    yes_label = _t("settings.delete_memory_yes")
    no_label = _t("settings.delete_memory_no")

    @st.fragment(run_every="1s")
    def _yes_button():
        ts2 = st.session_state.get("_delete_ts", 0)
        rem = max(0, 5 - int(time.time() - ts2))
        label = yes_label if rem == 0 else f"{yes_label} ({rem})"
        disabled = rem > 0
        if st.button(label, key="delete_yes", disabled=disabled, use_container_width=True, type="primary"):
            st.session_state.delete_confirmed = True
            st.session_state.pop("_delete_ts", None)
            st.rerun()

    col_yes, col_no = st.columns(2)
    with col_yes:
        _yes_button()
    with col_no:
        if st.button(no_label, key="delete_no", use_container_width=True):
            st.session_state.pop("_delete_ts", None)
            st.rerun()

@st.dialog(_t("chat.delete"))
def _delete_chat_dialog():
    chat_id = st.session_state.delete_chat_id
    title = st.session_state.delete_chat_title or ""
    st.markdown(_t("chat.delete_confirm", title=title))
    col1, col2 = st.columns(2)
    with col1:
        if st.button(_t("chat.delete_yes"), use_container_width=True, type="primary"):
            data, err = _api("DELETE", f"/frontend/chats/{chat_id}", timeout=10)
            if data:
                if st.session_state.chat_id == chat_id:
                    st.session_state.chat_id = None
                    st.session_state.messages = []
                    st.session_state.notifications = []
                    st.session_state._polling_active = False
                st.session_state.delete_chat_id = None
                st.session_state.delete_chat_title = None
                st.toast(_t("chat.deleted"), icon="🗑️")
                st.rerun()
            else:
                st.error(err or "Unknown error")
    with col2:
        if st.button(_t("chat.delete_no"), use_container_width=True):
            st.session_state.delete_chat_id = None
            st.session_state.delete_chat_title = None
            st.rerun()


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
if "delete_confirmed" not in st.session_state:
    st.session_state.delete_confirmed = False
if "delete_chat_id" not in st.session_state:
    st.session_state.delete_chat_id = None
if "delete_chat_title" not in st.session_state:
    st.session_state.delete_chat_title = None
if "editing_chat" not in st.session_state:
    st.session_state.editing_chat = None

if st.session_state.delete_confirmed:
    data, err = _api("DELETE", "/frontend/memory", timeout=30)
    st.session_state.delete_confirmed = False
    if data:
        st.session_state.chat_id = None
        st.session_state.messages = []
        st.session_state.chats = []
        st.session_state.notifications = []
        st.session_state._polling_active = False
        st.toast(_t("settings.delete_memory_success"), icon="🗑️")
    else:
        st.toast(_t("settings.delete_memory_error", error=err or "unknown"), icon="❌")
    time.sleep(1)
    st.rerun()

# Refresh widget labels on language change (Streamlit caches selectbox text).
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

        st.html('<span data-hook="delete-memory" style="display:none"></span>')

        if st.button(_t("settings.delete_memory"), use_container_width=True):
            st.session_state._delete_ts = time.time()
            _delete_memory_dialog()

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
        editing = st.session_state.editing_chat == chat["id"]

        with st.container(border=True):
            if editing:
                col_text, c_save, c_cancel = st.columns([0.76, 0.12, 0.12], vertical_alignment="bottom", gap="small")
                with col_text:
                    new_title = st.text_input(
                        "_",
                        value=chat["title"],
                        key=f"rename_{chat['id']}",
                        label_visibility="collapsed",
                        max_chars=255,
                    )
                with c_save:
                    if st.button("", icon=":material/check:", key=f"save_{chat['id']}", help=_t("chat.rename")):
                        data, err = _api("PUT", f"/frontend/chats/{chat['id']}", {"title": new_title})
                        if data:
                            st.session_state.editing_chat = None
                            st.rerun()
                        elif err:
                            st.toast(str(err))
                with c_cancel:
                    if st.button("", icon=":material/close:", key=f"cancel_{chat['id']}", help=_t("chat.delete_no")):
                        st.session_state.editing_chat = None
                        st.rerun()
            else:
                col_title, row_edit, row_delete = st.columns([0.76, 0.12, 0.12], vertical_alignment="center", gap="small")
                with col_title:
                    label = f"{'●' if active else '○'} {chat['title']}"
                    if st.button(label, key=f"chat_{chat['id']}", use_container_width=True):
                        st.session_state.editing_chat = None
                        if st.session_state.chat_id != chat["id"]:
                            st.session_state.chat_id = chat["id"]
                            st.session_state.notifications = []
                            st.session_state._polling_active = False
                            hist, _ = _api("GET", f"/frontend/chats/{chat['id']}/history")
                            st.session_state.messages = hist["messages"] if hist else []
                        st.rerun()
                with row_edit:
                    if st.button("", icon=":material/edit:", key=f"edit_{chat['id']}", help=_t("chat.rename")):
                        st.session_state.editing_chat = chat["id"]
                        st.rerun()
                with row_delete:
                    if st.button("", icon=":material/delete:", key=f"del_{chat['id']}", help=_t("chat.delete")):
                        st.session_state.delete_chat_id = chat["id"]
                        st.session_state.delete_chat_title = chat["title"]
                        _delete_chat_dialog()

    if not st.session_state.chats and st.session_state.chat_id is None:
        st.caption(_t("chat.empty"))


# ── main chat area ─────────────────────────────────────────────────────────

st.title(f"{_t('chat.title')} {st.session_state.settings.get('Assistant_name', DEFAULTS['Assistant_name'])}")

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
