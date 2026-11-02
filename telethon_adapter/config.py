from __future__ import annotations

from typing import Any

from .i18n import CONFIG_FIELD_TEXTS, DEFAULT_LANGUAGE, normalize_language, t

FIELD_SPECS = {
    "id": {"type": "string"},
    "api_id": {"type": "int"},
    "api_hash": {"type": "string"},
    "session_string": {"type": "text"},
    "language": {
        "type": "string",
        "options": ["zh-CN", "en-US"],
    },
    "trigger_prefix": {"type": "string"},
    "reply_to_self_triggers_command": {"type": "bool"},
    "group_self_mention_wakeup": {"type": "bool"},
    "download_incoming_media": {"type": "bool"},
    "incoming_media_ttl_seconds": {"type": "float"},
    "log_processed_messages_only": {"type": "bool"},
    "fast_upload_enabled": {"type": "bool"},
    "raw_event_debug": {"type": "bool", "invisible": True},
    "telethon_media_group_timeout": {"type": "float"},
    "telethon_media_group_max_wait": {"type": "float"},
    "proxy_type": {
        "type": "string",
        "options": ["", "socks5", "socks4", "http", "mtproto"],
    },
    "proxy_host": {"type": "string"},
    "proxy_port": {"type": "int"},
    "proxy_username": {"type": "string"},
    "proxy_password": {"type": "string"},
    "proxy_rdns": {
        "type": "bool",
        "invisible": True,
    },
    "proxy_secret": {"type": "string"},
}

def _build_config_metadata(default_language: str = DEFAULT_LANGUAGE) -> dict[str, dict[str, Any]]:
    texts = CONFIG_FIELD_TEXTS[default_language]
    metadata: dict[str, dict[str, Any]] = {}
    for field_name, field_spec in FIELD_SPECS.items():
        field_metadata = dict(field_spec)
        field_metadata.update(texts.get(field_name, {}))
        metadata[field_name] = field_metadata
    return metadata


def _build_i18n_resources() -> dict[str, dict[str, dict[str, Any]]]:
    return {
        language: {
            field_name: dict(field_text)
            for field_name, field_text in field_texts.items()
        }
        for language, field_texts in CONFIG_FIELD_TEXTS.items()
    }


TELETHON_CONFIG_METADATA = _build_config_metadata()
TELETHON_I18N_RESOURCES = _build_i18n_resources()

DEFAULT_CONFIG_TEMPLATE = {
    "id": "telethon_userbot",
    "api_id": 123456,
    "api_hash": "your_api_hash",
    "session_string": "",
    "language": DEFAULT_LANGUAGE,
    "trigger_prefix": "-astr",
    "reply_to_self_triggers_command": False,
    "group_self_mention_wakeup": True,
    "download_incoming_media": True,
    "incoming_media_ttl_seconds": 600.0,
    "log_processed_messages_only": True,
    "fast_upload_enabled": False,
    "raw_event_debug": False,
    "telethon_media_group_timeout": 1.2,
    "telethon_media_group_max_wait": 8.0,
    "proxy_type": "",
    "proxy_host": "",
    "proxy_port": 0,
    "proxy_username": "",
    "proxy_password": "",
    "proxy_secret": "",
}


def parse_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized == "":
            return default
        if normalized in {"1", "true", "yes", "y", "on"}:
            return True
        if normalized in {"0", "false", "no", "n", "off"}:
            return False
    return default


def parse_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    normalized = str(value).strip()
    return normalized if normalized else default


def parse_int(value: Any, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return default
        try:
            return int(normalized)
        except ValueError:
            return default
    return default


def parse_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        normalized = value.strip()
        if not normalized:
            return default
        try:
            return float(normalized)
        except ValueError:
            return default
    return default


def normalize_proxy_type(value: Any) -> str:
    proxy_type = parse_str(value, "").lower()
    if proxy_type == "mtproxy":
        return "mtproto"
    return proxy_type


def apply_config(adapter: Any) -> None:
    adapter.api_id = parse_int(adapter.config.get("api_id"), 0)
    adapter.api_hash = parse_str(adapter.config.get("api_hash"), "")
    adapter.session_string = parse_str(adapter.config.get("session_string"), "")
    adapter.language = normalize_language(adapter.config.get("language"))
    adapter.trigger_prefix = parse_str(adapter.config.get("trigger_prefix"), "")
    adapter.reply_to_self_triggers_command = parse_bool(
        adapter.config.get("reply_to_self_triggers_command"), False
    )
    adapter.group_self_mention_wakeup = parse_bool(
        adapter.config.get("group_self_mention_wakeup"), True
    )
    adapter.download_incoming_media = parse_bool(
        adapter.config.get("download_incoming_media"), True
    )
    adapter.incoming_media_ttl_seconds = parse_float(
        adapter.config.get("incoming_media_ttl_seconds"),
        600.0,
    )
    adapter.log_processed_messages_only = parse_bool(
        adapter.config.get("log_processed_messages_only"), True
    )
    adapter.fast_upload_enabled = parse_bool(
        adapter.config.get("fast_upload_enabled"), False
    )
    adapter.raw_event_debug = parse_bool(
        adapter.config.get("raw_event_debug"), False
    )
    adapter.media_group_timeout = parse_float(
        adapter.config.get("telethon_media_group_timeout"),
        1.2,
    )
    adapter.media_group_max_wait = parse_float(
        adapter.config.get("telethon_media_group_max_wait"),
        8.0,
    )
    adapter.proxy_type = normalize_proxy_type(adapter.config.get("proxy_type"))
    adapter.proxy_host = parse_str(adapter.config.get("proxy_host"), "")
    adapter.proxy_port = parse_int(adapter.config.get("proxy_port"), 0)
    adapter.proxy_username = parse_str(adapter.config.get("proxy_username"), "")
    adapter.proxy_password = str(adapter.config.get("proxy_password", "") or "")
    adapter.proxy_rdns = parse_bool(adapter.config.get("proxy_rdns"), True)
    adapter.proxy_secret = parse_str(adapter.config.get("proxy_secret"), "")


def _config_language(config: Any) -> str:
    if isinstance(config, dict):
        return normalize_language(config.get("language"))
    return DEFAULT_LANGUAGE


def config_error(
    field_name: str,
    current_value: Any,
    suggestion: str,
    *,
    language: str = DEFAULT_LANGUAGE,
) -> ValueError:
    return ValueError(
        t(
            language,
            "config.error",
            field_name=field_name,
            current_value=current_value,
            suggestion=suggestion,
        )
    )


def validate_config(adapter: Any) -> None:
    language = _config_language(getattr(adapter, "config", None))
    if adapter.api_id <= 0:
        raise config_error(
            "api_id",
            adapter.config.get("api_id"),
            t(language, "config.api_id.invalid"),
            language=language,
        )
    if not adapter.api_hash:
        raise config_error(
            "api_hash",
            adapter.config.get("api_hash"),
            t(language, "config.api_hash.invalid"),
            language=language,
        )
    if not adapter.session_string:
        raise config_error(
            "session_string",
            adapter.config.get("session_string"),
            t(language, "config.session_string.invalid"),
            language=language,
        )
    if adapter.language not in {"zh-CN", "en-US"}:
        raise config_error(
            "language",
            adapter.config.get("language"),
            t(language, "config.language.invalid"),
            language=language,
        )

    allowed_proxy_types = {"", "socks5", "socks4", "http", "mtproto"}
    if adapter.proxy_type not in allowed_proxy_types:
        raise config_error(
            "proxy_type",
            adapter.config.get("proxy_type"),
            t(language, "config.proxy_type.invalid"),
            language=language,
        )
    if adapter.proxy_type:
        if not adapter.proxy_host:
            raise config_error(
                "proxy_host",
                adapter.config.get("proxy_host"),
                t(language, "config.proxy_host.required"),
                language=language,
            )
        if adapter.proxy_port <= 0:
            raise config_error(
                "proxy_port",
                adapter.config.get("proxy_port"),
                t(language, "config.proxy_port.required"),
                language=language,
            )
        if adapter.proxy_type == "mtproto" and not adapter.proxy_secret:
            raise config_error(
                "proxy_secret",
                adapter.config.get("proxy_secret"),
                t(language, "config.proxy_secret.required"),
                language=language,
            )

    if adapter.media_group_timeout < 0:
        raise config_error(
            "telethon_media_group_timeout",
            adapter.config.get("telethon_media_group_timeout"),
            t(language, "config.media_group_timeout.invalid"),
            language=language,
        )
    if adapter.media_group_max_wait <= 0:
        raise config_error(
            "telethon_media_group_max_wait",
            adapter.config.get("telethon_media_group_max_wait"),
            t(language, "config.media_group_max_wait.invalid"),
            language=language,
        )
