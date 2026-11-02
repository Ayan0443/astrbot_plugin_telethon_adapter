from __future__ import annotations

import asyncio
import os
import shutil
from pathlib import Path
from typing import Any, Callable

from astrbot.api import logger
from astrbot.api.message_components import File, Image, Record, Video

try:
    from pydantic import PrivateAttr
except ImportError:
    from pydantic.v1 import PrivateAttr

try:
    from astrbot.core.utils.media_utils import convert_audio_to_wav
except ImportError:
    convert_audio_to_wav = None

# 视频贴纸（.webm/.mp4）与 TGS 动画贴纸都无法被 PIL 直接识别，
# 先转成一张 PNG 再交给上层。
_VIDEO_LIKE_SUFFIXES = {".webm", ".mp4", ".mov", ".mkv"}
_TGS_SUFFIX = ".tgs"
_FRAME_MAX_EDGE = 512


class TelethonLazyMedia:
    def __init__(
        self,
        msg: Any,
        temp_dir_getter: Callable[[], str],
        register_temp_file: Callable[[str], None],
        fallback_name: str,
    ) -> None:
        self._msg = msg
        self._temp_dir_getter = temp_dir_getter
        self._register_temp_file = register_temp_file
        self._fallback_name = fallback_name
        self._downloaded_path: str | None = None
        self._lock = asyncio.Lock()
        self._frame_path: str | None = None
        self._frame_lock = asyncio.Lock()

    def register_temp_file(self, path: str) -> None:
        self._register_temp_file(path)

    @staticmethod
    def _build_safe_target_path(temp_dir: str, fallback_name: str) -> str:
        temp_root = Path(temp_dir).resolve()
        safe_name = Path(str(fallback_name or "")).name
        if safe_name in {"", ".", ".."}:
            safe_name = "telethon_media.bin"
        target = (temp_root / safe_name).resolve()
        try:
            target.relative_to(temp_root)
        except ValueError as exc:
            raise RuntimeError("Resolved media download path escaped temp directory") from exc
        return str(target)

    async def ensure_downloaded(self) -> str:
        async with self._lock:
            if self._downloaded_path and os.path.exists(self._downloaded_path):
                return self._downloaded_path

            temp_dir = self._temp_dir_getter()
            Path(temp_dir).mkdir(parents=True, exist_ok=True)
            downloaded = await self._msg.download_media(file=temp_dir)
            if not downloaded:
                raise RuntimeError("Telethon media download returned empty path")

            if isinstance(downloaded, (bytes, bytearray)):
                target = self._build_safe_target_path(temp_dir, self._fallback_name)
                with open(target, "wb") as f:
                    f.write(downloaded)
            else:
                target = str(downloaded)

            self._downloaded_path = os.path.abspath(target)
            self.register_temp_file(self._downloaded_path)
            return self._downloaded_path

    async def ensure_image_frame(self, original: str) -> str:
        """把视频/动画贴纸转成第一帧 PNG，并缓存结果。"""
        if self._frame_path and os.path.exists(self._frame_path):
            return self._frame_path

        async with self._frame_lock:
            if self._frame_path and os.path.exists(self._frame_path):
                return self._frame_path

            if original.lower().endswith(_TGS_SUFFIX):
                try:
                    converted = extract_tgs_frame(original)
                except Exception as exc:
                    logger.warning("[Telethon] TGS 贴纸渲染失败，回退原文件: %s", exc)
                    return original
                self.register_temp_file(converted)
                self._frame_path = converted
                return converted

            ffmpeg = shutil.which("ffmpeg")
            if not ffmpeg:
                logger.warning(
                    "[Telethon] ffmpeg 不可用，视频贴纸无法转成图片，回退原文件: %s",
                    original,
                )
                return original

            try:
                converted = await extract_video_frame(original, ffmpeg)
            except Exception as exc:
                logger.warning("[Telethon] 视频贴纸抽帧失败，回退原文件: %s", exc)
                return original

            self.register_temp_file(converted)
            self._frame_path = converted
            return converted


def extract_tgs_frame(tgs_path: str) -> str:
    """把 TGS 动画贴纸渲染为第一帧 PNG。"""
    from rlottie_python import LottieAnimation

    target = os.path.splitext(tgs_path)[0] + ".frame.png"
    with LottieAnimation.from_tgs(tgs_path) as anim:
        image = anim.render_pillow_frame(frame_num=0)
        image.thumbnail((_FRAME_MAX_EDGE, _FRAME_MAX_EDGE))
        image.save(target)
    return os.path.abspath(target)


async def extract_video_frame(video_path: str, ffmpeg: str) -> str:
    """把视频抽一帧存为 PNG，供需要位图的链路使用。"""
    target = os.path.splitext(video_path)[0] + ".frame.png"
    scale = (
        f"scale='if(gt(iw,ih),min({_FRAME_MAX_EDGE},iw),-2)'"
        f":'if(gt(iw,ih),-2,min({_FRAME_MAX_EDGE},ih))'"
    )
    proc = await asyncio.create_subprocess_exec(
        ffmpeg,
        "-y",
        "-loglevel",
        "error",
        "-i",
        video_path,
        "-frames:v",
        "1",
        "-vf",
        scale,
        target,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0 or not os.path.exists(target):
        raise RuntimeError(
            f"ffmpeg failed ({proc.returncode}): {stderr.decode('utf-8', 'ignore')[:200]}"
        )
    return os.path.abspath(target)


class LazyImage(Image):
    _downloader: TelethonLazyMedia = PrivateAttr()

    def __init__(self, downloader: TelethonLazyMedia, **kwargs: Any) -> None:
        super().__init__(file="telethon-lazy://image", **kwargs)
        object.__setattr__(self, "_downloader", downloader)

    async def convert_to_file_path(self) -> str:
        original = await self._downloader.ensure_downloaded()
        suffix = Path(original).suffix.lower()
        if suffix not in _VIDEO_LIKE_SUFFIXES and suffix != _TGS_SUFFIX:
            return original
        return await self._downloader.ensure_image_frame(original)


class LazyRecord(Record):
    _downloader: TelethonLazyMedia = PrivateAttr()
    _converted_path: str | None = PrivateAttr(default=None)
    _conversion_lock: asyncio.Lock = PrivateAttr()

    def __init__(self, downloader: TelethonLazyMedia, **kwargs: Any) -> None:
        super().__init__(file="telethon-lazy://record", **kwargs)
        object.__setattr__(self, "_downloader", downloader)
        object.__setattr__(self, "_conversion_lock", asyncio.Lock())

    async def convert_to_file_path(self) -> str:
        original_path = await self._downloader.ensure_downloaded()
        async with self._conversion_lock:
            converted_path = self._converted_path
            if converted_path and os.path.exists(converted_path):
                return converted_path

            if original_path.lower().endswith(".wav"):
                return original_path
            if not convert_audio_to_wav:
                logger.warning(
                    "[Telethon] Audio conversion is unavailable, falling back to the original file: path=%s",
                    original_path,
                )
                return original_path

            wav_path = os.path.splitext(original_path)[0] + ".wav"
            try:
                converted = await convert_audio_to_wav(original_path, wav_path)
                converted = os.path.abspath(converted)
                if converted != os.path.abspath(original_path):
                    self._downloader.register_temp_file(converted)
                object.__setattr__(self, "_converted_path", converted)
                return converted
            except Exception as e:
                logger.warning(f"[Telethon] Failed to convert audio to WAV, falling back to the original file: {e}")
                return original_path


class LazyVideo(Video):
    _downloader: TelethonLazyMedia = PrivateAttr()

    def __init__(self, downloader: TelethonLazyMedia, **kwargs: Any) -> None:
        super().__init__(file="telethon-lazy://video", **kwargs)
        object.__setattr__(self, "_downloader", downloader)

    async def convert_to_file_path(self) -> str:
        return await self._downloader.ensure_downloaded()


class LazyFile(File):
    _downloader: TelethonLazyMedia = PrivateAttr()

    def __init__(self, name: str, downloader: TelethonLazyMedia, **kwargs: Any) -> None:
        super().__init__(name=name, file="", url="", **kwargs)
        object.__setattr__(self, "_downloader", downloader)

    async def get_file(self, allow_return_url: bool = False) -> str:
        return await self._downloader.ensure_downloaded()
