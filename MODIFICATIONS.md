# Modifications / 改动声明

This is a modified version of [outlook84/astrbot_plugin_telethon_adapter](https://github.com/outlook84/astrbot_plugin_telethon_adapter)
(upstream `0.10.0`, commit `1247e9a`), distributed under the same GNU GPL v2 (see `LICENSE`).
Changes were made by Ayan0443 in November 2026.

本仓库是上游 `0.10.0`（`1247e9a`）的修改版，按 GPL-2.0 发布。改动（2026 年 11 月，Ayan0443）：

| File | Change |
| --- | --- |
| `telethon_adapter/config.py` | Hidden keys: fatal-exit watchdog, limited fatal retry, log redaction |
| `telethon_adapter/i18n.py` | Labels for the new options |
| `telethon_adapter/lazy_media.py` | Animated / video sticker preview frames (2×2 frame sheet); voice messages: initialize `LazyRecord` private state so `.ogg` voice converts to WAV for speech-to-text |
| `telethon_adapter/message_converter.py` | Group `@self` wake-up emits a self-At with an empty prefix; numeric `self_id` |
| `telethon_adapter/telethon_adapter.py` | Send receipts (message ids returned to callers), fatal-error watchdog + health snapshot, limited retry for non-auth fatal errors, INFO log records text length instead of message body |
| `telethon_adapter/telethon_event.py` | Records Telegram message ids of successful sends |
| `tests/*` | Tests for the above |

All changes are optional or backward compatible; with the new hidden keys unset the adapter behaves like upstream,
except for the voice-message fix and the send receipts.
