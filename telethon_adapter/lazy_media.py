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
# 视频贴纸取代表帧：优先用 ffprobe 时长的中点，否则 0.5 秒处。
_DEFAULT_VIDEO_SEEK = 0.5
_PROBE_TIMEOUT = 10.0
# 动画/视频贴纸：均匀取 4 帧拼成 2×2 顺序图（左上→右上→左下→右下），
# 让识别模型看到动作的起止，而不是只看第一帧。失败时退回单张代表帧。
_SHEET_FRACTIONS = (0.125, 0.375, 0.625, 0.875)
_SHEET_CELL = 256


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
        """把视频/动画贴纸转成一张代表帧 PNG（取中间帧），并缓存结果。"""
        if self._frame_path and os.path.exists(self._frame_path):
            return self._frame_path

        async with self._frame_lock:
            if self._frame_path and os.path.exists(self._frame_path):
                return self._frame_path

            if original.lower().endswith(_TGS_SUFFIX):
                try:
                    # rlottie 渲染是纯 CPU 同步调用，放到线程池避免阻塞事件循环。
                    try:
                        converted = await asyncio.to_thread(extract_tgs_sheet, original)
                    except Exception as sheet_exc:
                        logger.debug("[Telethon] TGS 拼图失败，改取单帧: %s", sheet_exc)
                        converted = await asyncio.to_thread(extract_tgs_frame, original)
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

            converted: str | None = None
            ffprobe = shutil.which("ffprobe")
            try:
                converted = await extract_video_sheet(original, ffmpeg, ffprobe)
            except Exception as exc:
                logger.debug("[Telethon] 视频贴纸拼图失败，改取中间帧: %s", exc)
            if converted is None:
                seek = await pick_video_seek_seconds(original, ffprobe)
                try:
                    converted = await extract_video_frame(original, ffmpeg, seek_seconds=seek)
                except Exception as exc:
                    logger.debug("[Telethon] 视频贴纸中间帧抽取失败，改取首帧: %s", exc)
            if converted is None:
                try:
                    converted = await extract_video_frame(original, ffmpeg)
                except Exception as exc:
                    logger.warning("[Telethon] 视频贴纸抽帧失败，回退原文件: %s", exc)
                    return original

            self.register_temp_file(converted)
            self._frame_path = converted
            return converted


def extract_tgs_frame(tgs_path: str) -> str:
    """把 TGS 动画贴纸渲染为一张代表帧 PNG（中间帧；失败时退回第 0 帧）。

    同步函数：调用方应通过 ``asyncio.to_thread`` 执行。
    """
    from rlottie_python import LottieAnimation

    target = os.path.splitext(tgs_path)[0] + ".frame.png"
    with LottieAnimation.from_tgs(tgs_path) as anim:
        try:
            total = int(anim.lottie_animation_get_totalframe() or 0)
        except Exception:
            total = 0
        frame_num = total // 2 if total > 1 else 0
        try:
            image = anim.render_pillow_frame(frame_num=frame_num)
        except Exception:
            if frame_num == 0:
                raise
            image = anim.render_pillow_frame(frame_num=0)
        image.thumbnail((_FRAME_MAX_EDGE, _FRAME_MAX_EDGE))
        image.save(target)
    return os.path.abspath(target)


async def probe_video_duration(video_path: str, ffprobe: str | None) -> float | None:
    """用 ffprobe 读取时长（秒）；不可用或失败时返回 None。"""
    if not ffprobe:
        return None
    try:
        proc = await asyncio.create_subprocess_exec(
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            video_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
    except Exception:
        return None
    try:
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=_PROBE_TIMEOUT)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except Exception:
            pass
        return None
    if proc.returncode != 0:
        return None
    try:
        duration = float((stdout or b"").decode("utf-8", "ignore").strip().splitlines()[0])
    except (ValueError, IndexError):
        return None
    if duration != duration or duration <= 0:  # NaN / 非正数
        return None
    return duration


async def pick_video_seek_seconds(video_path: str, ffprobe: str | None) -> float:
    """代表帧位置：有时长取中点，否则 0.5 秒。"""
    duration = await probe_video_duration(video_path, ffprobe)
    if duration is None:
        return _DEFAULT_VIDEO_SEEK
    return round(duration / 2.0, 3)


async def extract_video_frame(
    video_path: str, ffmpeg: str, seek_seconds: float | None = None
) -> str:
    """把视频抽一帧存为 PNG，供需要位图的链路使用。

    ``seek_seconds`` 为 None 时取首帧；否则先 seek 到该时间点再取帧。
    """
    target = os.path.splitext(video_path)[0] + ".frame.png"
    try:
        os.remove(target)
    except OSError:
        pass
    scale = (
        f"scale='if(gt(iw,ih),min({_FRAME_MAX_EDGE},iw),-2)'"
        f":'if(gt(iw,ih),-2,min({_FRAME_MAX_EDGE},ih))'"
    )
    args = [ffmpeg, "-y", "-loglevel", "error"]
    if seek_seconds is not None and seek_seconds > 0:
        args += ["-ss", f"{seek_seconds:.3f}"]
    args += ["-i", video_path, "-frames:v", "1", "-vf", scale, target]
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0 or not os.path.exists(target):
        raise RuntimeError(
            f"ffmpeg failed ({proc.returncode}): {(stderr or b'').decode('utf-8', 'ignore')[:200]}"
        )
    return os.path.abspath(target)


def compose_frame_sheet(frames: list[Any], target: str) -> str:
    """把 1–4 张 PIL 图按时间顺序拼成 2×2（不足 4 张时按实际数量排布）。

    透明背景铺浅色底，便于识别模型看清轮廓。同步函数，需放线程池执行。
    """
    from PIL import Image as PILImage

    if not frames:
        raise ValueError("no frames")
    cells = []
    for frame in frames[:4]:
        img = frame.convert("RGBA")
        img.thumbnail((_SHEET_CELL, _SHEET_CELL))
        cell = PILImage.new("RGBA", (_SHEET_CELL, _SHEET_CELL), (245, 245, 245, 255))
        cell.alpha_composite(img, ((_SHEET_CELL - img.width) // 2, (_SHEET_CELL - img.height) // 2))
        cells.append(cell)
    cols = 1 if len(cells) == 1 else 2
    rows = (len(cells) + cols - 1) // cols
    gap = 4
    sheet = PILImage.new(
        "RGB",
        (cols * _SHEET_CELL + (cols - 1) * gap, rows * _SHEET_CELL + (rows - 1) * gap),
        (200, 200, 200),
    )
    for idx, cell in enumerate(cells):
        r, c = divmod(idx, cols)
        sheet.paste(cell.convert("RGB"), (c * (_SHEET_CELL + gap), r * (_SHEET_CELL + gap)))
    sheet.save(target)
    return os.path.abspath(target)


def extract_tgs_sheet(tgs_path: str) -> str:
    """TGS 动画均匀取 4 帧拼成顺序图。同步函数。"""
    from rlottie_python import LottieAnimation

    target = os.path.splitext(tgs_path)[0] + ".frame.png"
    with LottieAnimation.from_tgs(tgs_path) as anim:
        total = int(anim.lottie_animation_get_totalframe() or 0)
        if total < 4:
            raise ValueError(f"too few frames: {total}")
        frames = [
            anim.render_pillow_frame(frame_num=min(total - 1, int(total * f)))
            for f in _SHEET_FRACTIONS
        ]
    return compose_frame_sheet(frames, target)


async def extract_video_sheet(video_path: str, ffmpeg: str, ffprobe: str | None) -> str:
    """视频贴纸按时长均匀取 4 帧拼成顺序图；拿不到时长则抛错由上层回退。"""
    from PIL import Image as PILImage

    duration = await probe_video_duration(video_path, ffprobe)
    if duration is None:
        raise RuntimeError("duration unavailable")
    base = os.path.splitext(video_path)[0]
    frame_paths: list[str] = []
    try:
        for idx, fraction in enumerate(_SHEET_FRACTIONS):
            frame_path = f"{base}.sheet{idx}.png"
            proc = await asyncio.create_subprocess_exec(
                ffmpeg, "-y", "-loglevel", "error",
                "-ss", f"{duration * fraction:.3f}", "-i", video_path,
                "-frames:v", "1", frame_path,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode == 0 and os.path.exists(frame_path):
                frame_paths.append(frame_path)
        if len(frame_paths) < 2:
            raise RuntimeError("too few frames extracted")

        def _compose() -> str:
            frames = []
            for path in frame_paths:
                with PILImage.open(path) as im:
                    frames.append(im.copy())
            return compose_frame_sheet(frames, base + ".frame.png")

        return await asyncio.to_thread(_compose)
    finally:
        for path in frame_paths:
            try:
                os.remove(path)
            except OSError:
                pass


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
