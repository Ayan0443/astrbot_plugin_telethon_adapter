import importlib.util
import sys
import sysconfig
import tempfile
import types
import unittest
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REAL_TELETHON_SITE_PACKAGES = PROJECT_ROOT / ".venv" / sysconfig.get_path(
    "purelib",
    vars={"base": str(PROJECT_ROOT / ".venv"), "platbase": str(PROJECT_ROOT / ".venv")},
).removeprefix(str(PROJECT_ROOT / ".venv/"))


def _install_astrbot_stubs() -> None:
    astrbot_module = types.ModuleType("astrbot")
    api_module = types.ModuleType("astrbot.api")
    message_components_module = types.ModuleType("astrbot.api.message_components")
    platform_module = types.ModuleType("astrbot.api.platform")

    class _Logger:
        def debug(self, *args, **kwargs):
            return None

        def warning(self, *args, **kwargs):
            return None

        def exception(self, *args, **kwargs):
            return None

    class _BaseComponent:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    class At(_BaseComponent):
        pass

    class File(_BaseComponent):
        pass

    class Image(_BaseComponent):
        pass

    class Location(_BaseComponent):
        pass

    class Plain(_BaseComponent):
        pass

    class Record(_BaseComponent):
        pass

    class Reply(_BaseComponent):
        pass

    class Video(_BaseComponent):
        pass

    class AstrBotMessage:
        pass

    class MessageMember(_BaseComponent):
        pass

    class MessageType:
        GROUP_MESSAGE = "group"
        FRIEND_MESSAGE = "friend"

    api_module.logger = _Logger()
    message_components_module.At = At
    message_components_module.File = File
    message_components_module.Image = Image
    message_components_module.Location = Location
    message_components_module.Plain = Plain
    message_components_module.Record = Record
    message_components_module.Reply = Reply
    message_components_module.Video = Video
    platform_module.AstrBotMessage = AstrBotMessage
    platform_module.MessageMember = MessageMember
    platform_module.MessageType = MessageType

    sys.modules["astrbot"] = astrbot_module
    sys.modules["astrbot.api"] = api_module
    sys.modules["astrbot.api.message_components"] = message_components_module
    sys.modules["astrbot.api.platform"] = platform_module


def _install_pydantic_stubs() -> None:
    pydantic_module = types.ModuleType("pydantic")
    pydantic_v1_module = types.ModuleType("pydantic.v1")

    class _PrivateAttr:
        def __init__(self, default=None):
            self.default = default
            self.name = None

        def __set_name__(self, owner, name):
            self.name = name

        def __get__(self, instance, owner=None):
            if instance is None:
                return self
            return instance.__dict__.get(self.name, self.default)

        def __set__(self, instance, value):
            instance.__dict__[self.name] = value

    pydantic_module.PrivateAttr = _PrivateAttr
    pydantic_v1_module.PrivateAttr = _PrivateAttr
    sys.modules["pydantic"] = pydantic_module
    sys.modules["pydantic.v1"] = pydantic_v1_module


def _install_telethon_stubs() -> None:
    telethon_module = types.ModuleType("telethon")
    tl_module = types.ModuleType("telethon.tl")
    tl_types_module = types.ModuleType("telethon.tl.types")

    def _stub_type(name):
        return type(name, (), {})

    for name in [
        "DocumentAttributeAudio",
        "DocumentAttributeFilename",
        "DocumentAttributeSticker",
        "DocumentAttributeVideo",
        "GeoPointEmpty",
        "MessageEntityMention",
        "MessageEntityMentionName",
        "MessageEntityTextUrl",
        "MessageMediaContact",
        "MessageMediaGeo",
        "MessageMediaGeoLive",
    ]:
        setattr(tl_types_module, name, _stub_type(name))

    sys.modules["telethon"] = telethon_module
    sys.modules["telethon.tl"] = tl_module
    sys.modules["telethon.tl.types"] = tl_types_module


def _load_message_converter_module():
    _install_astrbot_stubs()
    _install_pydantic_stubs()
    _install_telethon_stubs()

    package_name = "telethon_adapter"
    package_path = Path(__file__).resolve().parents[1] / package_name
    package_module = types.ModuleType(package_name)
    package_module.__path__ = [str(package_path)]
    sys.modules[package_name] = package_module

    for module_name in ["i18n", "lazy_media", "message_converter"]:
        full_name = f"{package_name}.{module_name}"
        module_path = package_path / f"{module_name}.py"
        spec = importlib.util.spec_from_file_location(full_name, module_path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules[full_name] = module
        spec.loader.exec_module(module)

    return sys.modules["telethon_adapter.message_converter"]


def _load_message_converter_module_with_real_telethon():
    _install_astrbot_stubs()
    _install_pydantic_stubs()

    for module_name in list(sys.modules):
        if module_name == "telethon" or module_name.startswith("telethon."):
            sys.modules.pop(module_name, None)

    site_packages = str(REAL_TELETHON_SITE_PACKAGES)
    if site_packages not in sys.path:
        sys.path.insert(0, site_packages)

    package_name = "telethon_adapter"
    package_path = PROJECT_ROOT / package_name
    package_module = types.ModuleType(package_name)
    package_module.__path__ = [str(package_path)]
    sys.modules[package_name] = package_module

    for module_name in ["i18n", "lazy_media", "message_converter"]:
        full_name = f"{package_name}.{module_name}"
        module_path = package_path / f"{module_name}.py"
        spec = importlib.util.spec_from_file_location(full_name, module_path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        sys.modules[full_name] = module
        spec.loader.exec_module(module)

    return sys.modules["telethon_adapter.message_converter"]


class _FakeAdapter:
    def __init__(self, temp_dir: str, download_incoming_media: bool = True) -> None:
        self.self_id = "999"
        self.self_username = "astrbot"
        self.trigger_prefix = "-astr"
        self.language = "zh-CN"
        self.trigger_prefix = "-astr"
        self.reply_to_self_triggers_command = False
        self.download_incoming_media = download_incoming_media
        self._temp_dir = temp_dir
        self.registered_paths: list[str] = []

    def _get_media_temp_dir(self) -> str:
        return self._temp_dir

    def _register_temp_file(self, path: str) -> None:
        self.registered_paths.append(path)


class _FakeSender:
    def __init__(self, user_id: int, username: str | None = None) -> None:
        self.id = user_id
        self.username = username
        self.first_name = ""
        self.last_name = ""


class _FakeEvent:
    def __init__(self, message, sender, chat_id="100", is_private=False) -> None:
        self.message = message
        self.chat_id = chat_id
        self.is_private = is_private
        self._sender = sender

    async def get_sender(self):
        return self._sender


class _FakeMessage:
    def __init__(
        self,
        message_id: int,
        raw_text: str = "",
        entities=None,
        media=None,
        photo=None,
        document=None,
        reply_message=None,
        forum_topic_id=None,
    ) -> None:
        self.id = message_id
        self.raw_text = raw_text
        self.entities = entities
        self.media = media
        self.photo = photo
        self.document = document
        self.reply_to = None
        self._reply_message = reply_message
        self.forum_topic_id = forum_topic_id

    async def get_reply_message(self):
        if isinstance(self._reply_message, Exception):
            raise self._reply_message
        return self._reply_message


class _CapturingLogger:
    def __init__(self) -> None:
        self.debug_calls: list[tuple[tuple, dict]] = []

    def debug(self, *args, **kwargs):
        self.debug_calls.append((args, kwargs))

    def warning(self, *args, **kwargs):
        return None

    def exception(self, *args, **kwargs):
        return None


class _FakeReplyMessage(_FakeMessage):
    def __init__(
        self,
        message_id: int,
        sender,
        raw_text: str = "",
        entities=None,
        media=None,
        photo=None,
        document=None,
        chat_id="100",
        is_private=False,
        date=None,
    ) -> None:
        super().__init__(
            message_id,
            raw_text=raw_text,
            entities=entities,
            media=media,
            photo=photo,
            document=document,
        )
        self._sender = sender
        self.sender_id = getattr(sender, "id", None)
        self.chat_id = chat_id
        self.is_private = is_private
        self.date = date or datetime.fromtimestamp(1700000000)
        self.out = str(self.sender_id) == "999"

    async def get_sender(self):
        return self._sender


class MessageConverterTests(unittest.IsolatedAsyncioTestCase):
    async def test_convert_message_strips_trigger_prefix_and_injects_group_at(self):
        module = _load_message_converter_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            converter = module.TelethonMessageConverter(_FakeAdapter(temp_dir))
            event = _FakeEvent(
                _FakeMessage(1, raw_text="-astr hello world"),
                _FakeSender(123, username="alice"),
            )

            result = await converter.convert_message(event)

        self.assertEqual(result.message_str, "hello world")
        self.assertEqual(result.type, "group")
        self.assertEqual(result.group_id, "100")
        self.assertEqual(len(result.message), 2)
        self.assertEqual(type(result.message[0]).__name__, "At")
        self.assertEqual(result.message[0].qq, "999")
        self.assertEqual(type(result.message[1]).__name__, "Plain")
        self.assertEqual(result.message[1].text, "hello world")

    async def test_convert_private_message_strips_trigger_prefix_without_injecting_at(self):
        module = _load_message_converter_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            converter = module.TelethonMessageConverter(_FakeAdapter(temp_dir))
            event = _FakeEvent(
                _FakeMessage(1, raw_text="-astr tg status"),
                _FakeSender(123, username="alice"),
                is_private=True,
            )

            result = await converter.convert_message(event)

        self.assertEqual(result.message_str, "tg status")
        self.assertEqual(result.type, "friend")
        self.assertEqual(len(result.message), 1)
        self.assertEqual(type(result.message[0]).__name__, "Plain")
        self.assertEqual(result.message[0].text, "tg status")

    async def test_convert_message_emits_debug_logs(self):
        module = _load_message_converter_module()
        original_logger = module.logger
        capturing_logger = _CapturingLogger()
        module.logger = capturing_logger

        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                converter = module.TelethonMessageConverter(_FakeAdapter(temp_dir))
                event = _FakeEvent(
                    _FakeMessage(1, raw_text="-astr hello world"),
                    _FakeSender(123, username="alice"),
                )

                await converter.convert_message(event)
        finally:
            module.logger = original_logger

        self.assertEqual(len(capturing_logger.debug_calls), 2)
        self.assertIn("[Telethon] convert_message:", capturing_logger.debug_calls[0][0][0])
        self.assertIn("[Telethon] convert_result:", capturing_logger.debug_calls[1][0][0])

    async def test_convert_message_removes_self_mention_from_message_str(self):
        module = _load_message_converter_module()
        entity_type = sys.modules["telethon.tl.types"].MessageEntityMention
        entity = entity_type()
        entity.offset = 0
        entity.length = 8

        with tempfile.TemporaryDirectory() as temp_dir:
            converter = module.TelethonMessageConverter(_FakeAdapter(temp_dir))
            event = _FakeEvent(
                _FakeMessage(1, raw_text="@astrbot hello", entities=[entity]),
                _FakeSender(123, username="alice"),
            )

            result = await converter.convert_message(event)

        self.assertEqual(result.message_str, " hello")
        self.assertEqual(len(result.message), 2)
        self.assertEqual(type(result.message[0]).__name__, "At")
        self.assertEqual(result.message[0].qq, "999")
        self.assertEqual(type(result.message[1]).__name__, "Plain")
        self.assertEqual(result.message[1].text, " hello")

    async def test_convert_group_message_with_empty_prefix_preserves_self_mention_text(self):
        module = _load_message_converter_module()
        entity_type = sys.modules["telethon.tl.types"].MessageEntityMention
        entity = entity_type()
        entity.offset = 0
        entity.length = 8

        with tempfile.TemporaryDirectory() as temp_dir:
            adapter = _FakeAdapter(temp_dir)
            adapter.trigger_prefix = ""
            converter = module.TelethonMessageConverter(adapter)
            event = _FakeEvent(
                _FakeMessage(1, raw_text="@astrbot hello", entities=[entity]),
                _FakeSender(123, username="alice"),
            )

            result = await converter.convert_message(event)

        self.assertEqual(result.message_str, "@astrbot hello")
        self.assertEqual(len(result.message), 2)
        self.assertEqual(type(result.message[0]).__name__, "Plain")
        self.assertEqual(result.message[0].text, "@astrbot")
        self.assertEqual(type(result.message[1]).__name__, "Plain")
        self.assertEqual(result.message[1].text, " hello")

    async def test_group_self_mention_wakeup_emits_self_at_with_empty_prefix(self):
        module = _load_message_converter_module()
        entity_type = sys.modules["telethon.tl.types"].MessageEntityMention
        entity = entity_type()
        entity.offset = 0
        entity.length = 14

        with tempfile.TemporaryDirectory() as temp_dir:
            adapter = _FakeAdapter(temp_dir)
            adapter.trigger_prefix = ""
            adapter.group_self_mention_wakeup = True
            # username only available via the multi-username list
            adapter.self_username = "test_bot_user"
            adapter.self_usernames = {"test_bot_user"}
            converter = module.TelethonMessageConverter(adapter)
            event = _FakeEvent(
                _FakeMessage(1, raw_text="@test_BOT_USER 喵", entities=[entity]),
                _FakeSender(123, username="alice"),
            )

            result = await converter.convert_message(event)

        self.assertEqual(result.self_id, "999")
        self.assertEqual(type(result.message[0]).__name__, "At")
        self.assertEqual(result.message[0].qq, result.self_id)
        self.assertNotIn("@test_BOT", result.message_str)
        self.assertIn("喵", result.message_str)

    async def test_group_self_mention_wakeup_matches_secondary_username(self):
        module = _load_message_converter_module()
        entity_type = sys.modules["telethon.tl.types"].MessageEntityMention
        entity = entity_type()
        entity.offset = 0
        entity.length = 4

        with tempfile.TemporaryDirectory() as temp_dir:
            adapter = _FakeAdapter(temp_dir)
            adapter.trigger_prefix = ""
            adapter.group_self_mention_wakeup = True
            adapter.self_usernames = {"astrbot", "alt"}
            converter = module.TelethonMessageConverter(adapter)
            event = _FakeEvent(
                _FakeMessage(1, raw_text="@ALT hi", entities=[entity]),
                _FakeSender(123, username="alice"),
            )
            result = await converter.convert_message(event)

        self.assertEqual(type(result.message[0]).__name__, "At")
        self.assertEqual(result.message[0].qq, "999")

    async def test_group_other_mention_is_not_self_at(self):
        module = _load_message_converter_module()
        entity_type = sys.modules["telethon.tl.types"].MessageEntityMention
        entity = entity_type()
        entity.offset = 0
        entity.length = 4

        with tempfile.TemporaryDirectory() as temp_dir:
            adapter = _FakeAdapter(temp_dir)
            adapter.trigger_prefix = ""
            adapter.group_self_mention_wakeup = True
            converter = module.TelethonMessageConverter(adapter)
            event = _FakeEvent(
                _FakeMessage(1, raw_text="@bob hi", entities=[entity]),
                _FakeSender(123, username="alice"),
            )
            result = await converter.convert_message(event)

        self.assertEqual(type(result.message[0]).__name__, "At")
        self.assertEqual(result.message[0].qq, "bob")
        self.assertNotEqual(result.message[0].qq, result.self_id)

    def test_parse_text_components_converts_tg_user_link_to_at(self):
        module = _load_message_converter_module()
        entity_type = sys.modules["telethon.tl.types"].MessageEntityTextUrl
        entity = entity_type()
        entity.offset = 6
        entity.length = 4
        entity.url = "tg://user?id=42"

        with tempfile.TemporaryDirectory() as temp_dir:
            converter = module.TelethonMessageConverter(_FakeAdapter(temp_dir))
            components = converter.parse_text_components("hello @bob", [entity])

        self.assertEqual(len(components), 2)
        self.assertEqual(type(components[0]).__name__, "Plain")
        self.assertEqual(components[0].text, "hello ")
        self.assertEqual(type(components[1]).__name__, "At")
        self.assertEqual(components[1].qq, "bob")
        self.assertEqual(components[1].name, "bob")

    def test_parse_text_components_uses_utf16_offsets_for_emoji_prefix(self):
        module = _load_message_converter_module()
        entity_type = sys.modules["telethon.tl.types"].MessageEntityTextUrl
        entity = entity_type()
        entity.offset = 6
        entity.length = 4
        entity.url = "tg://user?id=84"

        with tempfile.TemporaryDirectory() as temp_dir:
            converter = module.TelethonMessageConverter(_FakeAdapter(temp_dir))
            components = converter.parse_text_components("hi 😀 @bob", [entity])

        self.assertEqual(len(components), 2)
        self.assertEqual(type(components[0]).__name__, "Plain")
        self.assertEqual(components[0].text, "hi 😀 ")
        self.assertEqual(type(components[1]).__name__, "At")
        self.assertEqual(components[1].qq, "bob")
        self.assertEqual(components[1].name, "bob")

    def test_parse_text_components_converts_mention_name_to_stable_text_at(self):
        module = _load_message_converter_module()
        entity_type = sys.modules["telethon.tl.types"].MessageEntityMentionName
        entity = entity_type()
        entity.offset = 6
        entity.length = 4
        entity.user_id = 42

        with tempfile.TemporaryDirectory() as temp_dir:
            converter = module.TelethonMessageConverter(_FakeAdapter(temp_dir))
            components = converter.parse_text_components("hello @bob", [entity])

        self.assertEqual(len(components), 2)
        self.assertEqual(type(components[0]).__name__, "Plain")
        self.assertEqual(components[0].text, "hello ")
        self.assertEqual(type(components[1]).__name__, "At")
        self.assertEqual(components[1].qq, "bob")
        self.assertEqual(components[1].name, "bob")

    async def test_convert_message_removes_self_text_url_mention_from_message_str(self):
        module = _load_message_converter_module()
        entity_type = sys.modules["telethon.tl.types"].MessageEntityTextUrl
        entity = entity_type()
        entity.offset = 0
        entity.length = 8
        entity.url = "tg://user?id=999"

        with tempfile.TemporaryDirectory() as temp_dir:
            converter = module.TelethonMessageConverter(_FakeAdapter(temp_dir))
            event = _FakeEvent(
                _FakeMessage(1, raw_text="@astrbot hello", entities=[entity]),
                _FakeSender(123, username="alice"),
            )

            result = await converter.convert_message(event)

        self.assertEqual(result.message_str, " hello")
        self.assertEqual(len(result.message), 2)
        self.assertEqual(type(result.message[0]).__name__, "At")
        self.assertEqual(result.message[0].qq, "999")
        self.assertEqual(type(result.message[1]).__name__, "Plain")
        self.assertEqual(result.message[1].text, " hello")

    def test_strip_prefix_from_components_handles_split_plain_segments(self):
        module = _load_message_converter_module()
        plain_type = sys.modules["astrbot.api.message_components"].Plain
        at_type = sys.modules["astrbot.api.message_components"].At

        components = [
            plain_type(text="-a"),
            plain_type(text="str hello"),
            at_type(qq="42", name="bob"),
        ]

        result = module.TelethonMessageConverter.strip_prefix_from_components(
            components,
            "-astr",
        )

        self.assertEqual(len(result), 2)
        self.assertEqual(type(result[0]).__name__, "Plain")
        self.assertEqual(result[0].text, "hello")
        self.assertEqual(type(result[1]).__name__, "At")
        self.assertEqual(result[1].qq, "42")

    async def test_parse_media_components_maps_audio_document(self):
        module = _load_message_converter_module()
        tl_types = sys.modules["telethon.tl.types"]
        audio_attr = tl_types.DocumentAttributeAudio()
        filename_attr = tl_types.DocumentAttributeFilename()
        filename_attr.file_name = "voice.ogg"

        document = types.SimpleNamespace(
            mime_type="audio/ogg",
            attributes=[audio_attr, filename_attr],
        )
        msg = _FakeMessage(
            2,
            media=object(),
            document=document,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            converter = module.TelethonMessageConverter(_FakeAdapter(temp_dir))
            components = await converter.parse_media_components(msg)

        self.assertEqual([type(component).__name__ for component in components], ["LazyRecord", "LazyFile", "Plain"])
        self.assertEqual(components[1].name, "voice.ogg")
        self.assertEqual(components[2].text, "[音频] voice.ogg")

    async def test_parse_media_components_uses_english_labels(self):
        module = _load_message_converter_module()
        tl_types = sys.modules["telethon.tl.types"]
        audio_attr = tl_types.DocumentAttributeAudio()
        filename_attr = tl_types.DocumentAttributeFilename()
        filename_attr.file_name = "voice.ogg"

        document = types.SimpleNamespace(
            mime_type="audio/ogg",
            attributes=[audio_attr, filename_attr],
        )
        msg = _FakeMessage(
            20,
            media=object(),
            document=document,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            adapter = _FakeAdapter(temp_dir)
            adapter.language = "en-US"
            converter = module.TelethonMessageConverter(adapter)
            components = await converter.parse_media_components(msg)

        self.assertEqual(components[2].text, "[Audio] voice.ogg")

    def test_guess_media_name_uses_mime_type_extension_for_documents(self):
        module = _load_message_converter_module()
        msg = _FakeMessage(
            21,
            document=types.SimpleNamespace(
                mime_type="application/pdf",
                attributes=[],
            ),
        )

        file_name = module.TelethonMessageConverter.guess_media_name(msg)

        self.assertEqual(file_name, "telethon_media_21.pdf")

    async def test_parse_media_components_skips_download_when_disabled(self):
        module = _load_message_converter_module()
        msg = _FakeMessage(
            3,
            media=object(),
            photo=object(),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            converter = module.TelethonMessageConverter(
                _FakeAdapter(temp_dir, download_incoming_media=False)
            )
            components = await converter.parse_media_components(msg)

        self.assertEqual(components, [])

    async def test_convert_message_builds_reply_component_from_replied_message(self):
        module = _load_message_converter_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            converter = module.TelethonMessageConverter(_FakeAdapter(temp_dir))
            reply_sender = _FakeSender(456, username="bob")
            reply_message = _FakeReplyMessage(
                99,
                sender=reply_sender,
                raw_text="quoted text",
                chat_id="100",
            )
            message = _FakeMessage(
                4,
                raw_text="-astr ack",
                reply_message=reply_message,
            )
            message.reply_to = types.SimpleNamespace(reply_to_msg_id=99)
            event = _FakeEvent(
                message,
                _FakeSender(123, username="alice"),
            )

            result = await converter.convert_message(event)

        self.assertEqual(type(result.message[0]).__name__, "Reply")
        self.assertEqual(result.message[0].id, "99")
        self.assertEqual(result.message[0].sender_id, "456")
        self.assertEqual(result.message[0].sender_nickname, "bob")
        self.assertEqual(result.message[0].message_str, "quoted text")
        self.assertEqual(len(result.message[0].chain), 1)
        self.assertEqual(type(result.message[0].chain[0]).__name__, "Plain")
        self.assertEqual(result.message[0].chain[0].text, "quoted text")
        self.assertEqual(type(result.message[1]).__name__, "At")
        self.assertEqual(result.message[1].qq, "999")
        self.assertEqual(type(result.message[2]).__name__, "Plain")
        self.assertEqual(result.message[2].text, "ack")

    async def test_group_reply_to_self_sender_matches_self_id_for_wakeup(self):
        """AstrBot waking_check compares Reply.sender_id with event.get_self_id()."""
        module = _load_message_converter_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            adapter = _FakeAdapter(temp_dir)
            adapter.trigger_prefix = ""
            adapter.group_self_mention_wakeup = True
            adapter.self_usernames = {"astrbot"}
            converter = module.TelethonMessageConverter(adapter)
            reply_message = _FakeReplyMessage(
                98,
                sender=_FakeSender(999, username="astrbot"),
                raw_text="previous bot output",
                chat_id="100",
            )
            message = _FakeMessage(8, raw_text="真的吗", reply_message=reply_message)
            message.reply_to = types.SimpleNamespace(reply_to_msg_id=98)
            event = _FakeEvent(message, _FakeSender(123, username="alice"))

            result = await converter.convert_message(event)

        replies = [c for c in result.message if type(c).__name__ == "Reply"]
        self.assertEqual(len(replies), 1)
        self.assertEqual(str(replies[0].sender_id), str(result.self_id))

    async def test_convert_group_reply_to_self_injects_wakeup_at_when_enabled(self):
        module = _load_message_converter_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            adapter = _FakeAdapter(temp_dir)
            adapter.reply_to_self_triggers_command = True
            converter = module.TelethonMessageConverter(adapter)
            reply_message = _FakeReplyMessage(
                98,
                sender=_FakeSender(999, username="astrbot"),
                raw_text="previous bot output",
                chat_id="100",
            )
            message = _FakeMessage(
                8,
                raw_text="tg status",
                reply_message=reply_message,
            )
            message.reply_to = types.SimpleNamespace(reply_to_msg_id=98)
            event = _FakeEvent(
                message,
                _FakeSender(123, username="alice"),
            )

            result = await converter.convert_message(event)

        self.assertEqual(type(result.message[0]).__name__, "Reply")
        self.assertEqual(type(result.message[1]).__name__, "At")
        self.assertEqual(result.message[1].qq, "999")
        self.assertEqual(type(result.message[2]).__name__, "Plain")
        self.assertEqual(result.message[2].text, "tg status")

    async def test_convert_private_reply_to_self_does_not_inject_wakeup_at(self):
        module = _load_message_converter_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            adapter = _FakeAdapter(temp_dir)
            adapter.reply_to_self_triggers_command = True
            converter = module.TelethonMessageConverter(adapter)
            reply_message = _FakeReplyMessage(
                97,
                sender=_FakeSender(999, username="astrbot"),
                raw_text="previous bot output",
                chat_id="42",
                is_private=True,
            )
            message = _FakeMessage(
                9,
                raw_text="tg status",
                reply_message=reply_message,
            )
            message.reply_to = types.SimpleNamespace(reply_to_msg_id=97)
            event = _FakeEvent(
                message,
                _FakeSender(123, username="alice"),
                chat_id="42",
                is_private=True,
            )

            result = await converter.convert_message(event)

        self.assertEqual([type(component).__name__ for component in result.message], ["Reply", "Plain"])
        self.assertEqual(result.message[1].text, "tg status")

    async def test_convert_reply_to_outgoing_non_self_sender_does_not_inject_wakeup_at(self):
        module = _load_message_converter_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            adapter = _FakeAdapter(temp_dir)
            adapter.reply_to_self_triggers_command = True
            converter = module.TelethonMessageConverter(adapter)
            reply_sender = _FakeSender(555, username="channel_alias")
            reply_message = _FakeReplyMessage(
                96,
                sender=reply_sender,
                raw_text="send-as output",
                chat_id="100",
            )
            reply_message.out = True
            message = _FakeMessage(
                10,
                raw_text="tg status",
                reply_message=reply_message,
            )
            message.reply_to = types.SimpleNamespace(reply_to_msg_id=96)
            event = _FakeEvent(
                message,
                _FakeSender(123, username="alice"),
            )

            result = await converter.convert_message(event)

        self.assertEqual([type(component).__name__ for component in result.message], ["Reply", "Plain"])
        self.assertEqual(result.message[1].text, "tg status")

    async def test_convert_topic_root_reply_to_self_does_not_inject_wakeup_at(self):
        module = _load_message_converter_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            adapter = _FakeAdapter(temp_dir)
            adapter.reply_to_self_triggers_command = True
            converter = module.TelethonMessageConverter(adapter)
            reply_message = _FakeReplyMessage(
                777,
                sender=_FakeSender(999, username="astrbot"),
                raw_text="topic root",
                chat_id="-100222",
            )
            message = _FakeMessage(
                11,
                raw_text="tg status",
                reply_message=reply_message,
            )
            message.reply_to = types.SimpleNamespace(
                reply_to_msg_id=777,
                top_msg_id=777,
            )
            event = _FakeEvent(
                message,
                _FakeSender(123, username="alice"),
                chat_id="-100222",
            )

            result = await converter.convert_message(event)

        self.assertEqual(result.group_id, "-100222#777")
        self.assertEqual([type(component).__name__ for component in result.message], ["Plain"])
        self.assertEqual(result.message[0].text, "tg status")

    async def test_convert_group_topic_message_uses_thread_scoped_session(self):
        module = _load_message_converter_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            converter = module.TelethonMessageConverter(_FakeAdapter(temp_dir))
            message = _FakeMessage(
                5,
                raw_text="-astr hello topic",
            )
            message.reply_to = types.SimpleNamespace(
                reply_to_msg_id=456,
                reply_to_top_id=456,
            )
            event = _FakeEvent(
                message,
                _FakeSender(123, username="alice"),
                chat_id="-100123456",
            )

            result = await converter.convert_message(event)

        self.assertEqual(result.type, "group")
        self.assertEqual(result.group_id, "-100123456#456")
        self.assertEqual(result.session_id, "-100123456#456")
        self.assertEqual(type(result.message[0]).__name__, "At")
        self.assertEqual(type(result.message[1]).__name__, "Plain")
        self.assertEqual(result.message[1].text, "hello topic")

    async def test_convert_topic_root_reply_does_not_emit_reply_component(self):
        module = _load_message_converter_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            converter = module.TelethonMessageConverter(_FakeAdapter(temp_dir))
            message = _FakeMessage(
                6,
                raw_text="-astr in topic",
            )
            message.reply_to = types.SimpleNamespace(
                reply_to_msg_id=777,
                top_msg_id=777,
            )
            event = _FakeEvent(
                message,
                _FakeSender(123, username="alice"),
                chat_id="-100222",
            )

            result = await converter.convert_message(event)

        self.assertEqual(result.group_id, "-100222#777")
        self.assertFalse(any(type(component).__name__ == "Reply" for component in result.message))

    async def test_convert_forum_topic_reply_header_uses_reply_to_msg_id_as_thread(self):
        module = _load_message_converter_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            converter = module.TelethonMessageConverter(_FakeAdapter(temp_dir))
            message = _FakeMessage(
                7,
                raw_text="-astr hi",
            )
            message.reply_to = types.SimpleNamespace(
                forum_topic=True,
                reply_to_msg_id=888,
            )
            event = _FakeEvent(
                message,
                _FakeSender(123, username="alice"),
                chat_id="-100333",
            )

            result = await converter.convert_message(event)

        self.assertEqual(result.group_id, "-100333#888")
        self.assertEqual(result.session_id, "-100333#888")
        self.assertFalse(any(type(component).__name__ == "Reply" for component in result.message))


@unittest.skipUnless(
    REAL_TELETHON_SITE_PACKAGES.exists(),
    "real Telethon test requires project .venv",
)
class MessageConverterRealTelethonTests(unittest.TestCase):
    def test_extract_thread_id_prefers_real_reply_to_top_id(self):
        module = _load_message_converter_module_with_real_telethon()
        from telethon.tl.types import MessageReplyHeader

        message = types.SimpleNamespace(
            reply_to=MessageReplyHeader(
                forum_topic=True,
                reply_to_msg_id=900,
                reply_to_top_id=777,
            )
        )

        self.assertEqual(module.TelethonMessageConverter.extract_thread_id(message), "777")

    def test_extract_thread_id_uses_real_top_msg_id_fallback(self):
        module = _load_message_converter_module_with_real_telethon()
        from telethon.tl.types import InputReplyToMessage

        message = types.SimpleNamespace(
            reply_to=InputReplyToMessage(
                reply_to_msg_id=900,
                top_msg_id=666,
            )
        )

        self.assertEqual(module.TelethonMessageConverter.extract_thread_id(message), "666")

    def test_extract_thread_id_uses_real_forum_topic_reply_to_msg_id_fallback(self):
        module = _load_message_converter_module_with_real_telethon()
        from telethon.tl.types import MessageReplyHeader

        message = types.SimpleNamespace(
            reply_to=MessageReplyHeader(
                forum_topic=True,
                reply_to_msg_id=555,
            )
        )

        self.assertEqual(module.TelethonMessageConverter.extract_thread_id(message), "555")


if __name__ == "__main__":
    unittest.main()
