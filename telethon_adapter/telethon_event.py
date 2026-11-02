from __future__ import annotations

import asyncio
from dataclasses import replace
import importlib
import os
import re
from pathlib import Path
import sys
from typing import Any

from astrbot.api.event import AstrMessageEvent, MessageChain
from astrbot.api.message_components import (
    At,
    File,
    Image,
    Location,
    Plain,
    Record,
    Reply,
    Video,
)
from astrbot.api.platform import AstrBotMessage, PlatformMetadata
from telethon import functions, types

if __package__:
    from .transport.request_sender import TelethonRequestSender
    from .rendering.text_renderer import TelethonTextRenderer
    from .services.message_dispatcher import TelethonMessageDispatcher
    from .services.message_executor import TelethonMessageExecutor
    from .services.message_planner import MediaAction, MediaGroupAction
    from .services.contracts import TelethonEventContext
    from .i18n import get_event_language, t
    from .fast_upload import build_input_media, should_use_fast_upload
else:
    _PACKAGE_NAME = "_telethon_adapter_direct"
    _PACKAGE_PATH = str(Path(__file__).resolve().parent)
    _package_module = sys.modules.get(_PACKAGE_NAME)
    if _package_module is None:
        import types as _types

        _package_module = _types.ModuleType(_PACKAGE_NAME)
        _package_module.__path__ = [_PACKAGE_PATH]
        sys.modules[_PACKAGE_NAME] = _package_module

    TelethonRequestSender = importlib.import_module(
        f"{_PACKAGE_NAME}.transport.request_sender"
    ).TelethonRequestSender
    TelethonTextRenderer = importlib.import_module(
        f"{_PACKAGE_NAME}.rendering.text_renderer"
    ).TelethonTextRenderer
    TelethonMessageDispatcher = importlib.import_module(
        f"{_PACKAGE_NAME}.services.message_dispatcher"
    ).TelethonMessageDispatcher
    TelethonMessageExecutor = importlib.import_module(
        f"{_PACKAGE_NAME}.services.message_executor"
    ).TelethonMessageExecutor
    _planner_module = importlib.import_module(f"{_PACKAGE_NAME}.services.message_planner")
    MediaAction = _planner_module.MediaAction
    MediaGroupAction = _planner_module.MediaGroupAction
    TelethonEventContext = importlib.import_module(
        f"{_PACKAGE_NAME}.services.contracts"
    ).TelethonEventContext
    _i18n_module = importlib.import_module(f"{_PACKAGE_NAME}.i18n")
    get_event_language = _i18n_module.get_event_language
    t = _i18n_module.t
    _fast_upload_module = importlib.import_module(f"{_PACKAGE_NAME}.fast_upload")
    build_input_media = _fast_upload_module.build_input_media
    should_use_fast_upload = _fast_upload_module.should_use_fast_upload


class TelethonEvent(AstrMessageEvent):
    META_ATTR = "_gdl_meta"
    MEDIA_GROUP_INTENT = "media_group"
    MAX_MESSAGE_LENGTH = 4096
    SPLIT_PATTERNS = {
        "paragraph": re.compile(r"\n\n"),
        "line": re.compile(r"\n"),
        "sentence": re.compile(r"[.!?。！？]"),
        "word": re.compile(r"\s"),
    }
    MARKDOWN_HINT_PATTERNS = (
        re.compile(r"```"),
        re.compile(r"(?m)^\s{0,3}#{1,6}\s+\S"),
        re.compile(r"(?m)^\s{0,3}>\s+\S"),
        re.compile(r"(?m)^\s{0,3}(?:[-*+]\s+\S|\d+\.\s+\S)"),
        re.compile(r"(?m)^\|.+\|\s*$"),
        re.compile(r"\[[^\]\n]+\]\((?:https?://|tg://)[^)]+\)"),
        re.compile(r"(?<!\*)\*\*[^*\n]+\*\*(?!\*)"),
        re.compile(r"(?<!_)__[^_\n]+__(?!_)"),
        re.compile(r"`[^`\n]+`"),
    )
    _message_dispatcher = TelethonMessageDispatcher()
    _message_executor = TelethonMessageExecutor(build_input_media=build_input_media)

    @staticmethod
    def _is_gif_path(path: str) -> bool:
        if path.lower().endswith(".gif"):
            return True
        try:
            with open(path, "rb") as f:
                return f.read(6) in (b"GIF87a", b"GIF89a")
        except OSError:
            return False

    def __init__(
        self,
        message_str: str,
        message_obj: AstrBotMessage,
        platform_meta: PlatformMetadata,
        session_id: str,
        client: Any,
    ) -> None:
        super().__init__(message_str, message_obj, platform_meta, session_id)
        self.client = client
        self.peer, self.thread_id = self._parse_session_target(session_id)

    @staticmethod
    def _parse_session_target(session_id: str) -> tuple[int, int | None]:
        normalized = str(session_id or "").strip()
        if not normalized:
            raise ValueError("session_id is empty")
        peer_part, separator, thread_part = normalized.partition("#")
        peer = int(peer_part)
        if not separator:
            return peer, None
        return peer, int(thread_part) if thread_part else None

    def _effective_reply_to(self, reply_to: int | None) -> int | None:
        if reply_to is not None:
            return reply_to
        return self.thread_id

    @classmethod
    def _text_renderer(cls) -> TelethonTextRenderer:
        return TelethonTextRenderer(
            max_message_length=cls.MAX_MESSAGE_LENGTH,
            split_patterns=cls.SPLIT_PATTERNS,
            markdown_hint_patterns=cls.MARKDOWN_HINT_PATTERNS,
        )

    def _request_sender(self) -> TelethonRequestSender:
        return TelethonRequestSender(
            client=self.client,
            peer=self.peer,
            thread_id=self.thread_id,
            build_input_media=build_input_media,
            should_use_fast_upload=should_use_fast_upload,
        )

    def _build_reply_to(self, reply_to: int | None) -> Any | None:
        return self._request_sender().build_reply_to(self._effective_reply_to(reply_to))

    @staticmethod
    def _normalize_low_level_reply_to(reply_to: Any | None) -> Any | None:
        return TelethonRequestSender.normalize_low_level_reply_to(reply_to)

    async def _resolve_input_peer(self) -> Any:
        return await self._request_sender().resolve_input_peer()

    async def _parse_formatting_entities(
        self,
        text: str,
        parse_mode: str | None,
    ) -> tuple[str, Any | None]:
        return await self._request_sender().parse_formatting_entities(text, parse_mode)

    async def _execute_request(self, request: Any, entity: Any) -> Any:
        return await self._request_sender().execute_request(request, entity)

    async def _send_text_request(
        self,
        text: str,
        *,
        parse_mode: str | None,
        reply_to: int | None,
        link_preview: bool,
    ) -> Any:
        result = await self._request_sender().send_text(
            text,
            parse_mode=parse_mode,
            reply_to_msg_id=reply_to,
            link_preview=link_preview,
            force_low_level=self._should_use_low_level_text_request(),
        )
        self._record_sent_receipt(result)
        return result

    def _record_sent_receipt(self, result: Any) -> None:
        """Record Telegram message ids returned by a successful send request.

        Frisk local patch: the ids are the only send evidence downstream
        plugins may trust (``after_message_sent`` also fires after a failed
        send). Stored as event extra ``telethon_sent_message_ids``.
        """
        items = result if isinstance(result, (list, tuple)) else [result]
        ids = []
        for item in items:
            msg_id = getattr(item, "id", None)
            if isinstance(msg_id, int) and msg_id > 0:
                ids.append(msg_id)
        if not ids:
            return
        try:
            existing = list(self.get_extra("telethon_sent_message_ids", []) or [])
            self.set_extra("telethon_sent_message_ids", existing + ids)
        except Exception:
            pass

    async def _send_media_request(self, action: MediaAction) -> Any:
        result = await self._send_media_request_inner(action)
        self._record_sent_receipt(result)
        return result

    async def _send_media_request_inner(self, action: MediaAction) -> Any:
        action = await self._normalize_media_action_caption(action)
        if not self._should_use_low_level_media_request(spoiler=action.spoiler):
            return await self._request_sender().send_media_action(
                action,
            )

        entity = await self._resolve_input_peer()
        parsed_caption, msg_entities = await self._parse_formatting_entities(
            action.caption or "",
            action.caption_parse_mode,
        )
        _file_handle, media, _is_image = await build_input_media(
            self.client,
            action.path,
            **TelethonRequestSender._build_media_kwargs(
                mime_type=action.mime_type,
                attributes=action.attributes,
            ),
        )
        if action.spoiler:
            media = await self._finalize_spoiler_media(
                entity,
                media,
                mime_type=action.mime_type,
            )
        request = functions.messages.SendMediaRequest(
            peer=entity,
            media=media,
            reply_to=self._normalize_low_level_reply_to(self._build_reply_to(action.reply_to)),
            message=parsed_caption,
            entities=msg_entities,
        )
        return await self._execute_request(request, entity)

    async def _finalize_spoiler_media(
        self,
        entity: Any,
        media: Any,
        *,
        mime_type: str | None,
    ) -> Any:
        return await self._message_executor.finalize_spoiler_media(
            self,
            entity,
            media,
            mime_type=mime_type,
        )

    def _message_log_context(self, reply_to: int | None = None) -> dict[str, Any]:
        return self._message_executor.message_log_context(self, reply_to)

    def _event_context(self, reply_to: int | None = None) -> TelethonEventContext:
        return self._message_executor.build_event_context(self, reply_to)

    def _label(self, key: str) -> str:
        return f"[{t(get_event_language(self), key)}]"

    async def _send_chat_action(self, action: types.TypeSendMessageAction) -> None:
        await self._message_executor.send_chat_action(self, action)

    def _chat_action_scope(
        self,
        action_name: str,
        fallback_action: types.TypeSendMessageAction,
    ):
        return self._message_executor.chat_action_scope(self, action_name, fallback_action)

    async def _flush_text(
        self, text_parts: list[tuple[str, bool]], reply_to: int | None
    ) -> int | None:
        return await self._message_executor.flush_text(self, text_parts, reply_to)

    async def _execute_media_action(self, action: MediaAction) -> int | None:
        return await self._message_executor.execute_media_action(self, action)

    async def _execute_media_group_action(self, action: MediaGroupAction) -> None:
        action = await self._normalize_media_group_action_caption(action)
        request_sender = self._request_sender()
        if not self._should_use_low_level_media_group_request(
            has_spoiler=any(spoiler for _path, spoiler, _is_video in action.media_items)
        ) and not any(
            request_sender.should_use_fast_upload(self.client, path)
            for path, _spoiler, _is_video in action.media_items
        ):
            payload: dict[str, Any] = {
                "caption": action.caption,
                "reply_to": self._build_reply_to(action.reply_to),
            }
            if action.caption_parse_mode is not None:
                payload["parse_mode"] = action.caption_parse_mode
            await self.client.send_file(
                self.peer,
                file=[path for path, _spoiler, _is_video in action.media_items],
                **payload,
            )
            return
        await request_sender.send_media_group_action(action)

    async def _normalize_media_action_caption(self, action: MediaAction) -> MediaAction:
        if not action.caption or action.caption_parse_mode != "markdown":
            return action
        formatted_caption = await self._format_markdown_for_telethon_html_async(action.caption)
        return replace(action, caption=formatted_caption, caption_parse_mode="html")

    async def _normalize_media_group_action_caption(
        self,
        action: MediaGroupAction,
    ) -> MediaGroupAction:
        if not action.caption or action.caption_parse_mode != "markdown":
            return action
        formatted_caption = await self._format_markdown_for_telethon_html_async(action.caption)
        return replace(action, caption=formatted_caption, caption_parse_mode="html")

    async def _try_send_local_media_group(self, message: MessageChain) -> bool:
        return await self._message_dispatcher.try_send_local_media_group(self, message)

    def _should_use_low_level_text_request(self) -> bool:
        return self.thread_id is not None

    def _should_use_low_level_media_request(self, *, spoiler: bool) -> bool:
        return self.thread_id is not None or spoiler

    def _should_use_low_level_media_group_request(self, *, has_spoiler: bool) -> bool:
        return self.thread_id is not None or has_spoiler

    async def send_typing(self) -> None:
        await self._send_chat_action(types.SendMessageTypingAction())

    async def _send_base_message(self, message: MessageChain) -> None:
        await super().send(message)

    async def send(self, message: MessageChain):
        await self._message_dispatcher.send(self, message)

    @staticmethod
    def _format_at_text(item: At) -> str:
        return TelethonTextRenderer.format_at_text(item)

    @classmethod
    def _format_at_html(cls, item: At) -> str | None:
        return TelethonTextRenderer.format_at_html(item)

    @classmethod
    def _split_message(cls, text: str) -> list[str]:
        return cls._text_renderer().split_message(text)

    @classmethod
    def _split_html_message(cls, html_text: str) -> list[str]:
        return cls._text_renderer().split_html_message(html_text)

    @classmethod
    def _component_has_spoiler(cls, item: Any) -> bool:
        for attr_name in ("spoiler", "has_spoiler", "is_spoiler"):
            value = getattr(item, attr_name, None)
            if value is not None:
                return bool(value)

        meta = getattr(item, cls.META_ATTR, None)
        if isinstance(meta, dict):
            for key in ("spoiler", "has_spoiler", "is_spoiler"):
                if key in meta:
                    return bool(meta[key])

        extra = getattr(item, "extra", None)
        if isinstance(extra, dict):
            for key in ("spoiler", "has_spoiler", "is_spoiler"):
                if key in extra:
                    return bool(extra[key])

        return False

    def _pack_text_chunks(
        self, text_parts: list[tuple[str, bool]]
    ) -> list[list[tuple[str, bool]]]:
        return self._text_renderer().pack_text_chunks(text_parts)

    @staticmethod
    def _render_text_chunk(text_parts: list[tuple[str, bool]]) -> str:
        return TelethonTextRenderer.render_text_chunk(text_parts)

    @classmethod
    def _looks_like_markdown(cls, text: str) -> bool:
        return cls._text_renderer().looks_like_markdown(text)

    @staticmethod
    def _render_table(node) -> str:
        return TelethonTextRenderer.render_table(node)

    @classmethod
    def _format_markdown_for_telethon_html(cls, text: str) -> str:
        return TelethonTextRenderer.format_markdown_for_telethon_html(text)

    async def _format_markdown_for_telethon_html_async(self, text: str) -> str:
        return await self._text_renderer().format_markdown_async(
            text,
            formatter=self._format_markdown_for_telethon_html,
            thread_runner=asyncio.to_thread,
        )

    async def _send_text_with_action(
        self,
        text: str | list[tuple[str, bool]],
        reply_to: int | None,
        *,
        send_typing_action: bool = True,
    ):
        return await self._message_executor.send_text_with_action(
            self,
            text,
            reply_to,
            send_typing_action=send_typing_action,
        )

    async def react(self, emoji: str) -> None:
        await self._message_executor.react(self, emoji)
