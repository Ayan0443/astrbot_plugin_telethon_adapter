import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


def _install_astrbot_stubs() -> None:
    astrbot_module = types.ModuleType("astrbot")
    api_module = types.ModuleType("astrbot.api")
    message_components_module = types.ModuleType("astrbot.api.message_components")

    class _Logger:
        def warning(self, *args, **kwargs):
            return None

        def debug(self, *args, **kwargs):
            return None

    class _BaseComponent:
        def __init__(self, **kwargs):
            for key, value in kwargs.items():
                setattr(self, key, value)

    class File(_BaseComponent):
        def __init__(self, name="", file="", url="", **kwargs):
            super().__init__(name=name, file=file, url=url, **kwargs)

    class Image(_BaseComponent):
        def __init__(self, file="", **kwargs):
            super().__init__(file=file, **kwargs)

    class Record(_BaseComponent):
        def __init__(self, file="", **kwargs):
            super().__init__(file=file, **kwargs)

    class Video(_BaseComponent):
        def __init__(self, file="", **kwargs):
            super().__init__(file=file, **kwargs)

    api_module.logger = _Logger()
    message_components_module.File = File
    message_components_module.Image = Image
    message_components_module.Record = Record
    message_components_module.Video = Video

    sys.modules["astrbot"] = astrbot_module
    sys.modules["astrbot.api"] = api_module
    sys.modules["astrbot.api.message_components"] = message_components_module


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


def _load_lazy_media_module():
    _install_astrbot_stubs()
    _install_pydantic_stubs()
    module_path = Path(__file__).resolve().parents[1] / "telethon_adapter" / "lazy_media.py"
    spec = importlib.util.spec_from_file_location("test_lazy_media_module", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


class _FakeMessage:
    def __init__(self, download_path) -> None:
        self._download_path = download_path
        self.download_calls = 0

    async def download_media(self, file: str):
        self.download_calls += 1
        return self._download_path


class LazyMediaTests(unittest.IsolatedAsyncioTestCase):
    async def test_ensure_downloaded_reuses_cached_file_path(self):
        lazy_media = _load_lazy_media_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            original_path = os.path.join(temp_dir, "photo.jpg")
            Path(original_path).write_bytes(b"jpg")
            message = _FakeMessage(original_path)
            downloader = lazy_media.TelethonLazyMedia(
                msg=message,
                temp_dir_getter=lambda: temp_dir,
                register_temp_file=lambda path: None,
                fallback_name="photo.jpg",
            )

            first = await downloader.ensure_downloaded()
            second = await downloader.ensure_downloaded()

        self.assertEqual(first, os.path.abspath(original_path))
        self.assertEqual(second, os.path.abspath(original_path))
        self.assertEqual(message.download_calls, 1)

    async def test_ensure_downloaded_writes_bytes_payload_with_fallback_name(self):
        lazy_media = _load_lazy_media_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            message = _FakeMessage(b"payload")
            downloader = lazy_media.TelethonLazyMedia(
                msg=message,
                temp_dir_getter=lambda: temp_dir,
                register_temp_file=lambda path: None,
                fallback_name="payload.bin",
            )

            result = await downloader.ensure_downloaded()

            self.assertEqual(result, os.path.join(temp_dir, "payload.bin"))
            self.assertEqual(Path(result).read_bytes(), b"payload")

    async def test_ensure_downloaded_sanitizes_fallback_name_to_temp_dir(self):
        lazy_media = _load_lazy_media_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            message = _FakeMessage(b"payload")
            downloader = lazy_media.TelethonLazyMedia(
                msg=message,
                temp_dir_getter=lambda: temp_dir,
                register_temp_file=lambda path: None,
                fallback_name="../nested/escape.bin",
            )

            result = await downloader.ensure_downloaded()

            self.assertEqual(result, os.path.join(temp_dir, "escape.bin"))
            self.assertEqual(Path(result).read_bytes(), b"payload")

    async def test_record_conversion_registers_original_and_wav_temp_files(self):
        lazy_media = _load_lazy_media_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            original_path = os.path.join(temp_dir, "voice.ogg")
            converted_path = os.path.join(temp_dir, "voice.wav")
            Path(original_path).write_bytes(b"ogg")

            tracked: dict[str, float] = {}

            def register_temp_file(path: str) -> None:
                tracked[os.path.abspath(path)] = 1.0

            downloader = lazy_media.TelethonLazyMedia(
                msg=_FakeMessage(original_path),
                temp_dir_getter=lambda: temp_dir,
                register_temp_file=register_temp_file,
                fallback_name="voice.ogg",
            )
            record = lazy_media.LazyRecord(downloader=downloader)

            async def fake_convert_audio_to_wav(source: str, target: str) -> str:
                self.assertEqual(source, original_path)
                self.assertEqual(target, converted_path)
                Path(target).write_bytes(b"wav")
                return target

            with patch.object(lazy_media, "convert_audio_to_wav", fake_convert_audio_to_wav):
                result = await record.convert_to_file_path()

            self.assertEqual(result, os.path.abspath(converted_path))
            self.assertEqual(
                set(tracked.keys()),
                {os.path.abspath(original_path), os.path.abspath(converted_path)},
            )

    async def test_record_conversion_falls_back_to_original_when_converter_missing(self):
        lazy_media = _load_lazy_media_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            original_path = os.path.join(temp_dir, "voice.ogg")
            Path(original_path).write_bytes(b"ogg")
            downloader = lazy_media.TelethonLazyMedia(
                msg=_FakeMessage(original_path),
                temp_dir_getter=lambda: temp_dir,
                register_temp_file=lambda path: None,
                fallback_name="voice.ogg",
            )
            record = lazy_media.LazyRecord(downloader=downloader)

            with patch.object(lazy_media, "convert_audio_to_wav", None):
                result = await record.convert_to_file_path()

        self.assertEqual(result, os.path.abspath(original_path))


class _FakeProc:
    def __init__(self, returncode=0, stdout=b"", on_run=None):
        self.returncode = returncode
        self._stdout = stdout
        self._on_run = on_run

    async def communicate(self):
        if self._on_run:
            self._on_run()
        return self._stdout, b""

    def kill(self):
        return None


class _FakeAnim:
    instances = []

    def __init__(self, total, fail_frames=()):
        self.total = total
        self.fail_frames = set(fail_frames)
        self.rendered = []
        _FakeAnim.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def lottie_animation_get_totalframe(self):
        return self.total

    def render_pillow_frame(self, frame_num=0):
        self.rendered.append(frame_num)
        if frame_num in self.fail_frames:
            raise RuntimeError("render failed")
        anim = self

        class _Img:
            def thumbnail(self, size):
                anim.thumb = size

            def save(self, target):
                Path(target).write_bytes(b"png")

        return _Img()


def _install_fake_rlottie(total, fail_frames=()):
    module = types.ModuleType("rlottie_python")

    class LottieAnimation:
        @staticmethod
        def from_tgs(path):
            return _FakeAnim(total, fail_frames)

    module.LottieAnimation = LottieAnimation
    sys.modules["rlottie_python"] = module
    _FakeAnim.instances = []

def _raise_sheet(*_args, **_kwargs):
    raise RuntimeError("sheet disabled in single-frame tests")


class AnimatedFrameTests(unittest.IsolatedAsyncioTestCase):
    def _downloader(self, lazy_media, temp_dir, path, tracked=None):
        return lazy_media.TelethonLazyMedia(
            msg=_FakeMessage(path),
            temp_dir_getter=lambda: temp_dir,
            register_temp_file=(tracked.append if tracked is not None else (lambda p: None)),
            fallback_name=os.path.basename(path),
        )

    async def test_tgs_renders_middle_frame_in_thread(self):
        lazy_media = _load_lazy_media_module()
        _install_fake_rlottie(total=60)
        lazy_media.extract_tgs_sheet = _raise_sheet
        with tempfile.TemporaryDirectory() as temp_dir:
            tgs = os.path.join(temp_dir, "s.tgs")
            Path(tgs).write_bytes(b"tgs")
            tracked = []
            image = lazy_media.LazyImage(downloader=self._downloader(lazy_media, temp_dir, tgs, tracked))
            calls = []
            real_to_thread = lazy_media.asyncio.to_thread

            async def spy_to_thread(fn, *args, **kwargs):
                calls.append(fn)
                return await real_to_thread(fn, *args, **kwargs)

            with patch.object(lazy_media.asyncio, "to_thread", spy_to_thread):
                result = await image.convert_to_file_path()
                again = await image.convert_to_file_path()

            self.assertEqual(result, os.path.join(temp_dir, "s.frame.png"))
            self.assertEqual(again, result)
            self.assertEqual(calls, [_raise_sheet, lazy_media.extract_tgs_frame])
            self.assertEqual(_FakeAnim.instances[0].rendered, [30])
            self.assertIn(result, tracked)

    async def test_tgs_middle_failure_falls_back_to_frame_zero(self):
        lazy_media = _load_lazy_media_module()
        _install_fake_rlottie(total=10, fail_frames={5})
        with tempfile.TemporaryDirectory() as temp_dir:
            tgs = os.path.join(temp_dir, "s.tgs")
            Path(tgs).write_bytes(b"tgs")
            result = lazy_media.extract_tgs_frame(tgs)
            self.assertTrue(os.path.exists(result))
        self.assertEqual(_FakeAnim.instances[0].rendered, [5, 0])

    async def test_tgs_total_failure_returns_original(self):
        lazy_media = _load_lazy_media_module()
        _install_fake_rlottie(total=10, fail_frames={0, 5})
        with tempfile.TemporaryDirectory() as temp_dir:
            tgs = os.path.join(temp_dir, "s.tgs")
            Path(tgs).write_bytes(b"tgs")
            image = lazy_media.LazyImage(downloader=self._downloader(lazy_media, temp_dir, tgs))
            result = await image.convert_to_file_path()
        self.assertEqual(result, os.path.abspath(tgs))

    async def _run_video(self, lazy_media, temp_dir, probe_stdout, probe_rc, ffmpeg_results, ffprobe="/x/ffprobe"):
        video = os.path.join(temp_dir, "v.webm")
        Path(video).write_bytes(b"webm")
        target = os.path.join(temp_dir, "v.frame.png")
        calls = []
        ffmpeg_iter = iter(ffmpeg_results)

        async def fake_exec(*args, **kwargs):
            calls.append(list(args))
            if args[0].endswith("ffprobe"):
                return _FakeProc(returncode=probe_rc, stdout=probe_stdout)
            ok = next(ffmpeg_iter)
            return _FakeProc(
                returncode=0 if ok else 1,
                on_run=(lambda: Path(target).write_bytes(b"png")) if ok else None,
            )

        def fake_which(name):
            if name == "ffmpeg":
                return "/x/ffmpeg"
            if name == "ffprobe":
                return ffprobe
            return None

        image = lazy_media.LazyImage(downloader=self._downloader(lazy_media, temp_dir, video))

        async def no_sheet(*_a, **_k):
            raise RuntimeError("sheet disabled in single-frame tests")

        with patch.object(lazy_media.asyncio, "create_subprocess_exec", fake_exec), patch.object(
            lazy_media.shutil, "which", fake_which
        ), patch.object(lazy_media, "extract_video_sheet", no_sheet):
            result = await image.convert_to_file_path()
        return result, calls, video, target

    async def test_video_seeks_to_middle_using_ffprobe(self):
        lazy_media = _load_lazy_media_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            result, calls, _, target = await self._run_video(lazy_media, temp_dir, b"3.000000\n", 0, [True])
        self.assertEqual(result, os.path.abspath(target))
        ffmpeg_calls = [c for c in calls if c[0].endswith("ffmpeg")]
        self.assertEqual(len(ffmpeg_calls), 1)
        self.assertIn("-ss", ffmpeg_calls[0])
        self.assertEqual(ffmpeg_calls[0][ffmpeg_calls[0].index("-ss") + 1], "1.500")

    async def test_video_without_ffprobe_seeks_half_second(self):
        lazy_media = _load_lazy_media_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            result, calls, _, target = await self._run_video(
                lazy_media, temp_dir, b"", 0, [True], ffprobe=None
            )
        self.assertEqual(result, os.path.abspath(target))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][calls[0].index("-ss") + 1], "0.500")

    async def test_video_bad_probe_output_uses_default_seek(self):
        lazy_media = _load_lazy_media_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            _, calls, _, _ = await self._run_video(lazy_media, temp_dir, b"N/A\n", 0, [True])
        ffmpeg_calls = [c for c in calls if c[0].endswith("ffmpeg")]
        self.assertEqual(ffmpeg_calls[0][ffmpeg_calls[0].index("-ss") + 1], "0.500")

    async def test_video_seek_failure_falls_back_to_first_frame(self):
        lazy_media = _load_lazy_media_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            result, calls, _, target = await self._run_video(lazy_media, temp_dir, b"2.0", 0, [False, True])
        self.assertEqual(result, os.path.abspath(target))
        ffmpeg_calls = [c for c in calls if c[0].endswith("ffmpeg")]
        self.assertEqual(len(ffmpeg_calls), 2)
        self.assertIn("-ss", ffmpeg_calls[0])
        self.assertNotIn("-ss", ffmpeg_calls[1])

    async def test_video_total_failure_returns_original(self):
        lazy_media = _load_lazy_media_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            result, _, video, _ = await self._run_video(lazy_media, temp_dir, b"2.0", 0, [False, False])
        self.assertEqual(result, os.path.abspath(video))


class FrameSheetTests(unittest.IsolatedAsyncioTestCase):
    def test_compose_sheet_is_2x2_in_order(self):
        lazy_media = _load_lazy_media_module()
        from PIL import Image as PILImage
        colors = [(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255), (255, 255, 0, 255)]
        frames = [PILImage.new("RGBA", (100, 100), c) for c in colors]
        with tempfile.TemporaryDirectory() as temp_dir:
            out = lazy_media.compose_frame_sheet(frames, os.path.join(temp_dir, "x.png"))
            sheet = PILImage.open(out).convert("RGB")
            cell = lazy_media._SHEET_CELL
            self.assertEqual(sheet.size, (2 * cell + 4, 2 * cell + 4))
            mids = [(cell // 2, cell // 2), (cell + 4 + cell // 2, cell // 2),
                    (cell // 2, cell + 4 + cell // 2), (cell + 4 + cell // 2, cell + 4 + cell // 2)]
            self.assertEqual([sheet.getpixel(m) for m in mids], [c[:3] for c in colors])

    async def test_video_uses_sheet_when_available(self):
        lazy_media = _load_lazy_media_module()
        with tempfile.TemporaryDirectory() as temp_dir:
            video = os.path.join(temp_dir, "v.webm")
            Path(video).write_bytes(b"webm")
            sheet = os.path.join(temp_dir, "v.frame.png")

            async def fake_sheet(path, ffmpeg, ffprobe):
                Path(sheet).write_bytes(b"png")
                return os.path.abspath(sheet)

            downloader = lazy_media.TelethonLazyMedia(
                msg=_FakeMessage(video), temp_dir_getter=lambda: temp_dir,
                register_temp_file=lambda p: None, fallback_name="v.webm",
            )
            image = lazy_media.LazyImage(downloader=downloader)
            with patch.object(lazy_media, "extract_video_sheet", fake_sheet), patch.object(
                lazy_media.shutil, "which", lambda n: "/x/" + n
            ):
                result = await image.convert_to_file_path()
            self.assertEqual(result, os.path.abspath(sheet))

    def test_tgs_sheet_samples_four_spread_frames(self):
        lazy_media = _load_lazy_media_module()
        _install_fake_rlottie(total=80)
        rendered = []
        with tempfile.TemporaryDirectory() as temp_dir:
            tgs = os.path.join(temp_dir, "s.tgs")
            Path(tgs).write_bytes(b"tgs")
            with patch.object(lazy_media, "compose_frame_sheet", lambda frames, target: (rendered.extend(frames), target)[1]):
                lazy_media.extract_tgs_sheet(tgs)
        self.assertEqual(len(rendered), 4)
        self.assertEqual(_FakeAnim.instances[-1].rendered, [10, 30, 50, 70])


if __name__ == "__main__":
    unittest.main()
