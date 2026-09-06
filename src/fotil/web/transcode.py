"""JPEG preview transcoding backends.

Browsers cannot display HEIF images, so previews are transcoded to JPEG.
The macOS sips backend goes through ImageIO with hardware HEVC decoding
and is preferred when available; the Pillow pipeline is the portable
backend and the per-file fallback when sips fails.
"""

import os
import shutil
import subprocess

from pathlib import Path

import pillow_heif

from PIL import Image, ImageOps


pillow_heif.register_heif_opener()

# Generous for 48MP photos; a hung sips must not stall the request thread.
SIPS_TIMEOUT = 60


class TranscodeError(Exception):
    """An image could not be transcoded for display."""


def _use_sips() -> bool:
    """Whether the sips backend should try first, honoring FOTIL_TRANSCODER."""
    forced = os.environ.get('FOTIL_TRANSCODER', 'auto')
    if forced == 'sips':
        return True
    if forced == 'pillow':
        return False
    return shutil.which('sips') is not None


def transcode(
    src: Path,
    dst: Path,
    max_size: tuple[int, int],
    quality: int,
    *,
    size_check: bool = False,
) -> None:
    """Write a JPEG preview of src, shrunk to max_size, to dst.

    Tries the sips backend first when available and falls back to Pillow
    per file, so files sips cannot handle still get a preview.

    Args:
        size_check: probe the header size and only shrink images already
            larger than max_size (sips -Z would otherwise upscale smaller
            ones). Off by default; see WebConfig.sips_size_check.

    Raises:
        TranscodeError: If no backend could decode src.
    """
    if _use_sips():
        try:
            _transcode_sips(src, dst, max_size, quality, size_check=size_check)
            return
        except TranscodeError:
            pass
    _transcode_pillow(src, dst, max_size, quality)


def _transcode_sips(
    src: Path,
    dst: Path,
    max_size: tuple[int, int],
    quality: int,
    *,
    size_check: bool,
) -> None:
    """Transcode via macOS sips, validating that the output is a JPEG.

    Raises:
        TranscodeError: If sips failed, timed out or wrote no JPEG. sips can
            exit 0 on some failures, so the output itself is checked.
    """
    try:
        cmd = ['sips', '-s', 'format', 'jpeg', '-s', 'formatOptions', str(quality)]
        if not size_check:
            cmd += ['-Z', str(max(max_size))]
        else:
            # Header read only, no pixel decoding.
            with Image.open(src) as im:
                if max(im.size) > max(max_size):
                    cmd += ['-Z', str(max(max_size))]
        cmd += [str(src), '--out', str(dst)]
        proc = subprocess.run(cmd, capture_output=True, timeout=SIPS_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        raise TranscodeError(f'sips timed out on {src}') from exc
    except Exception as exc:
        raise TranscodeError(f'sips failed on {src}: {exc}') from exc
    if proc.returncode != 0 or not _is_jpeg(dst):
        stderr = proc.stderr.decode(errors='replace').strip()
        raise TranscodeError(f'sips failed on {src}: {stderr}')


def _is_jpeg(path: Path) -> bool:
    """Whether path exists and starts with the JPEG magic bytes."""
    try:
        with path.open('rb') as f:
            return f.read(2) == b'\xff\xd8'
    except OSError:
        return False


def _transcode_pillow(
    src: Path, dst: Path, max_size: tuple[int, int], quality: int
) -> None:
    """Transcode via Pillow.

    Raises:
        TranscodeError: If the image cannot be decoded or written.
    """
    try:
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im)
            im.thumbnail(max_size)
            im.convert('RGB').save(dst, 'JPEG', quality=quality)
    except Exception as exc:
        raise TranscodeError(f'failed to transcode {src}: {exc}') from exc
