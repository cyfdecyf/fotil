"""Filesystem service layer for the web UI.

Pure filesystem logic without HTTP concerns, so it can be tested directly.
All user supplied paths are validated to stay inside the library directories.
"""

import hashlib
import json
import subprocess
import threading

from collections import OrderedDict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

from fotil.config import Config, LibraryConfig
from fotil.exiftool import Exiftool
from fotil.fs import iter_directory_files
from fotil.web.transcode import TranscodeError, transcode


# Suffixes the browser renders directly.
BROWSER_SUFFIXES = {'.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png'}
# Suffixes that must be transcoded to JPEG because browsers cannot display
# them reliably (HEIF/HIF).
TRANSCODE_SUFFIXES = {'.hif', '.heic'}

# "large" variant: max preview size of transcoded images. Plenty for
# culling, much faster to decode and transfer than full 33MP camera images.
TRANSCODE_MAX_SIZE = (2560, 2560)
TRANSCODE_QUALITY = 85
# "thumb" variant for the photo grid.
THUMB_MAX_SIZE = (800, 800)
THUMB_QUALITY = 80
CACHE_DIR = Path('~/.cache/fotil/web').expanduser()

# URL size value -> (max_size, quality, cache_key). The cache_key becomes
# part of the on-disk cache filename, so changing size or quality rotates
# the cache naturally instead of serving stale previews.
IMAGE_VARIANTS = {
    'thumb': (
        THUMB_MAX_SIZE,
        THUMB_QUALITY,
        f'thumb-{THUMB_MAX_SIZE[0]}-{THUMB_QUALITY}',
    ),
    'large': (
        TRANSCODE_MAX_SIZE,
        TRANSCODE_QUALITY,
        f'large-{TRANSCODE_MAX_SIZE[0]}-{TRANSCODE_QUALITY}',
    ),
}

# Photos per grid chunk.
PAGE_SIZE = 200


class InvalidPathError(ValueError):
    """A user supplied path escaped the directory it must stay within."""


class UnknownLibraryError(ValueError):
    """The requested library name is not in the config."""


def get_library(conf: Config, name: str | None) -> LibraryConfig:
    """Resolve library by name, defaulting to conf.default_library.

    The directory fields are normalized to absolute paths in place, so all
    other service functions can rely on them.

    Raises:
        UnknownLibraryError: If name is neither given nor default.
    """
    if name is None:
        name = conf.default_library
    try:
        lib_conf = conf.library[name]
    except KeyError:
        raise UnknownLibraryError(f'unknown library {name!r}') from None
    lib_conf.pic_dir = lib_conf.pic_dir.expanduser().resolve()
    lib_conf.raw_dir = lib_conf.raw_dir.expanduser().resolve()
    lib_conf.trash_dir = lib_conf.trash_dir.expanduser().resolve()
    return lib_conf


def _contained_dir(root: Path, dir_rel: str) -> Path:
    """Resolve dir_rel under root, ensuring it stays inside root.

    Raises:
        InvalidPathError: If dir_rel is absolute or the resolved path
            escapes root.
    """
    dir_rel = (dir_rel or '').strip()
    if dir_rel.startswith('/'):
        raise InvalidPathError(f'directory {dir_rel!r} must be relative to pic_dir')
    target = (root / dir_rel).resolve()
    if target != root and root not in target.parents:
        raise InvalidPathError(f'directory {dir_rel!r} is outside {root}')
    return target


# Path value cache: (resolved path, kind) -> (path mtime_ns, value). Works
# for both directory listings and per-file values: a directory's mtime_ns
# changes whenever its direct entries are added, removed or renamed, and a
# file's mtime_ns changes whenever the file itself is rewritten, which is
# exactly what the cached values depend on.
_values: OrderedDict[tuple[Path, str], tuple[int, object]] = OrderedDict()
_values_lock = threading.Lock()
_VALUES_MAX = 512


def _cached_value[T](path: Path, kind: str, compute: Callable[[], T]) -> T:
    """Return compute() cached by path's mtime; a changed mtime invalidates.

    Keys pair the resolved path (as returned by _contained_dir or
    _contained_pic_file) with a kind tag, so one path holds one entry per
    computed value kind. compute() runs outside the lock; under thread races
    the worst case is a wasted recompute.
    """
    key = (path, kind)
    try:
        mtime = path.stat().st_mtime_ns
    except OSError:
        return compute()
    with _values_lock:
        hit = _values.get(key)
        if hit is not None and hit[0] == mtime:
            _values.move_to_end(key)
            return hit[1]
    value = compute()
    with _values_lock:
        _values[key] = (mtime, value)
        while len(_values) > _VALUES_MAX:
            _values.popitem(last=False)
    return value


def _subdir_names(directory: Path) -> list[str]:
    """Sorted non-hidden subdirectory names directly under directory."""
    return sorted(
        p.name for p in directory.iterdir() if p.is_dir() and not p.name.startswith('.')
    )


def _has_subdirs(directory: Path) -> bool:
    """Whether directory contains any non-hidden subdirectory."""
    return bool(_cached_value(directory, 'dirs', lambda: _subdir_names(directory)))


def _pic_listing(lib_conf: LibraryConfig, directory: Path) -> tuple[list[Path], int]:
    """Full sorted pic listing under directory relative to pic_dir, and count."""
    files = sorted(
        p.relative_to(lib_conf.pic_dir)
        for p in directory.iterdir()
        if p.is_file() and lib_conf.pic_file_filter(p)
    )
    return files, len(files)


def list_subdirs(lib_conf: LibraryConfig, dir_rel: str = '') -> list[str]:
    """Sorted non-hidden subdirectory names directly under pic_dir/dir_rel."""
    directory = _contained_dir(lib_conf.pic_dir, dir_rel)
    if not directory.is_dir():
        return []
    return _cached_value(directory, 'dirs', lambda: _subdir_names(directory))


def list_subdirs_details(lib_conf: LibraryConfig, dir_rel: str = '') -> list[dict]:
    """Subdirectories under pic_dir/dir_rel, with child-dir presence.

    Used by the directory tree to render expand arrows only for directories
    that actually contain subdirectories.
    """
    directory = _contained_dir(lib_conf.pic_dir, dir_rel)
    if not directory.is_dir():
        return []
    names = _cached_value(directory, 'dirs', lambda: _subdir_names(directory))
    return [
        {'name': name, 'has_children': _has_subdirs(directory / name)} for name in names
    ]


def list_pics(
    lib_conf: LibraryConfig, dir_rel: str = '', offset: int = 0, limit: int = PAGE_SIZE
) -> tuple[list[Path], int]:
    """Pic files directly under pic_dir/dir_rel, relative to pic_dir, sorted.

    Returns:
        A tuple of the files for one chunk and the total file count.
    """
    directory = _contained_dir(lib_conf.pic_dir, dir_rel)
    if not directory.is_dir():
        return [], 0
    files, total = _cached_value(
        directory, 'files', lambda: _pic_listing(lib_conf, directory)
    )
    return files[offset : offset + limit], total


def _contained_pic_file(lib_conf: LibraryConfig, path_rel: str) -> Path:
    """Resolve path_rel under pic_dir, verifying it is a picture file.

    Raises:
        InvalidPathError: If the path escapes pic_dir or is not a picture.
        FileNotFoundError: If the file does not exist.
    """
    path_rel = (path_rel or '').strip()
    src = (lib_conf.pic_dir / path_rel).resolve()
    if src == lib_conf.pic_dir or lib_conf.pic_dir not in src.parents:
        raise InvalidPathError(f'path {path_rel!r} is outside the library pic_dir')
    if not src.is_file():
        raise FileNotFoundError(f'no such picture: {path_rel}')
    if not lib_conf.pic_file_filter(src):
        raise InvalidPathError(f'{src.name!r} is not a picture file')
    return src


def transcode_cache_path(src: Path, variant: str) -> Path:
    """Cache file path for the transcoded preview of src.

    The source mtime and the variant cache_key are part of the key, so
    edits invalidate the cache and variants never collide.
    """
    _, _, cache_key = IMAGE_VARIANTS[variant]
    stamp = f'{src}::{src.stat().st_mtime_ns}::{cache_key}'
    key = hashlib.sha256(stamp.encode()).hexdigest()[:32]
    return CACHE_DIR / f'{key}.jpg'


def ensure_transcode(src: Path, variant: str, *, size_check: bool = False) -> Path:
    """Transcode an image to a cached JPEG preview of the given variant.

    Args:
        variant: An IMAGE_VARIANTS key ('thumb' or 'large').
        size_check: shrink only images larger than the variant max size,
            see transcode.transcode().

    Raises:
        TranscodeError: If the image cannot be decoded or written.
    """
    max_size, quality, _ = IMAGE_VARIANTS[variant]
    dst = transcode_cache_path(src, variant)
    if dst.is_file():
        return dst
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(f'.{dst.stem}.{id(dst)}.tmp')
    try:
        transcode(src, tmp, max_size, quality, size_check=size_check)
        tmp.replace(dst)
    except OSError as exc:
        raise TranscodeError(f'failed to write {dst}: {exc}') from exc
    finally:
        tmp.unlink(missing_ok=True)
    return dst


def prune_cache(max_bytes: int) -> None:
    """Delete oldest cache files until the cache fits max_bytes.

    Cache files are derived previews, not library files, so deleting them is
    safe: pruned entries simply regenerate on demand. Called when the web
    server starts and stops, never while requests are served; the *.jpg glob
    ignores stray .tmp files from crashed runs. If max_bytes is smaller than
    a single cache file, the cache can end up empty.
    """
    if max_bytes <= 0:
        return
    entries: list[tuple[int, int, Path]] = []  # (mtime_ns, size, path)
    total = 0
    for f in CACHE_DIR.glob('*.jpg'):
        try:
            st = f.stat()
        except OSError:
            continue
        entries.append((st.st_mtime_ns, st.st_size, f))
        total += st.st_size
    if total <= max_bytes:
        return
    entries.sort()
    for _, size, f in entries:
        if total <= max_bytes:
            break
        try:
            f.unlink()
        except OSError:
            continue
        total -= size


def image_file(
    lib_conf: LibraryConfig,
    path_rel: str,
    *,
    size: str | None = None,
    size_check: bool = False,
) -> tuple[Path, str]:
    """File to serve for a picture and its media type.

    With size given ('thumb' or 'large'), jpg/png and HEIF files alike are
    transcoded to a cached JPEG of that variant. Without size, legacy
    behavior applies: browser-renderable files are served as-is, HEIF
    falls back to the large variant, anything else is served as an opaque
    blob for the UI to show a placeholder for.

    Raises:
        InvalidPathError: If size is not a known variant.
    """
    src = _contained_pic_file(lib_conf, path_rel)
    suffix = src.suffix.lower()
    if size is not None and size not in IMAGE_VARIANTS:
        raise InvalidPathError(f'unknown image size {size!r}')
    if size is not None and (suffix in BROWSER_SUFFIXES or suffix in TRANSCODE_SUFFIXES):
        return ensure_transcode(src, size, size_check=size_check), 'image/jpeg'
    media_type = BROWSER_SUFFIXES.get(suffix)
    if media_type is not None:
        return src, media_type
    if suffix in TRANSCODE_SUFFIXES:
        return ensure_transcode(src, 'large', size_check=size_check), 'image/jpeg'
    return src, 'application/octet-stream'


# EXIF tags shown in the lightbox header, in display order. exiftool reads
# them with -n, so numeric tags come back as plain numbers ('FNumber': 2.8).
EXIF_DISPLAY_TAGS = [
    'ISO',
    'FNumber',
    'ExposureTime',
    'FocalLength',
    'FocalLengthIn35mmFormat',
    'LensModel',
    'Model',
]


def pic_exif(lib_conf: LibraryConfig, path_rel: str) -> list[str]:
    """Display-ready EXIF segments for one picture, in fixed order.

    Returns an empty list when the file carries none of the display tags,
    or when exiftool is unavailable, so the UI can simply hide the line.
    """
    src = _contained_pic_file(lib_conf, path_rel)
    return _cached_value(src, 'exif', lambda: _read_exif(src))


def _read_exif(src: Path) -> list[str]:
    """Run exiftool on one picture and format its display segments."""
    try:
        records = Exiftool().read([src], tags=EXIF_DISPLAY_TAGS)
    except (
        OSError,  # includes the missing-exiftool-binary FileNotFoundError
        json.JSONDecodeError,
        subprocess.CalledProcessError,
    ):
        return []
    return _format_exif(records[0]) if records else []


def _format_exif(exif: dict[str, str]) -> list[str]:
    """Turn one exiftool record into ordered, human-readable segments."""
    segments = []
    if 'ISO' in exif:
        segments.append(f'ISO {_exif_num(exif["ISO"])}')
    if 'FNumber' in exif:
        segments.append(f'f/{_exif_num(exif["FNumber"])}')
    if 'ExposureTime' in exif:
        segments.append(_exif_shutter(exif['ExposureTime']))
    if 'FocalLength' in exif:
        focal_length = _exif_num(exif['FocalLength'])
        focal = f'{focal_length}mm'
        if 'FocalLengthIn35mmFormat' in exif:
            equivalent = _exif_num(exif['FocalLengthIn35mmFormat'])
            if equivalent != focal_length:
                focal += f' (eq. {equivalent}mm)'
        segments.append(focal)
    for tag in ('LensModel', 'Model'):
        if exif.get(tag):
            segments.append(exif[tag])
    return segments


def _exif_num(value: str) -> str:
    """Trim a numeric exiftool value, so '24.0' and '24' both show as '24'."""
    try:
        return f'{float(value):g}'
    except ValueError:
        return value


def _exif_shutter(value: str) -> str:
    """Format an exposure time as '1/250s' or, for slow shutters, '0.5s'."""
    try:
        sec = float(value)
    except ValueError:
        return value
    if sec <= 0:
        return value
    if sec >= 0.25:
        return f'{sec:g}s'
    return f'1/{round(1 / sec)}s'


@dataclass
class CleanupResult:
    """Outcome of a cleanup run, for display in the UI.

    Attributes:
        trashed_pics: Relative paths of moved pics, relative to pic_dir.
        trashed_raws: Relative paths of moved raws, relative to raw_dir.
        skipped: Human readable messages for the inputs that were not moved.
    """

    trashed_pics: list[Path] = field(default_factory=list)
    trashed_raws: list[Path] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)


def cleanup_pics(lib_conf: LibraryConfig, pic_rels: Iterable[str]) -> CleanupResult:
    """Move given pics and their same-stem raws into trash_dir.

    Only the given files are touched, no library wide scan. Files are
    renamed, never deleted, so everything can be restored from trash by
    hand. Only raws whose stem matches one of the given pics are moved.

    Returns:
        A CleanupResult describing what was moved and what was skipped.
    """
    result = CleanupResult()
    stems: set[str] = set()
    for rel in pic_rels:
        try:
            src = _contained_pic_file(lib_conf, rel)
        except (InvalidPathError, FileNotFoundError) as exc:
            result.skipped.append(f'{rel}: {exc}')
            continue
        if _trash(lib_conf, src, lib_conf.pic_dir):
            result.trashed_pics.append(Path(rel.strip()))
        stems.add(src.stem)

    if not stems:
        return result
    for raw_rel in iter_directory_files(
        lib_conf.raw_dir, file_filter=lib_conf.raw_file_filter
    ):
        if raw_rel.stem not in stems:
            continue
        raw_src = lib_conf.raw_dir / raw_rel
        # Same-stem raws of several pics, or raws already trashed before.
        if not raw_src.is_file():
            continue
        if _trash(lib_conf, raw_src, lib_conf.raw_dir):
            result.trashed_raws.append(raw_rel)
    return result


def _trash(lib_conf: LibraryConfig, src: Path, src_root: Path) -> bool:
    """Move src into trash_dir mirroring its layout under src_root.

    Returns:
        False if src already vanished (e.g. moved for an earlier same-stem
        pic), True if it was moved now.
    """
    if not src.is_file():
        return False
    dst_dir = lib_conf.trash_dir / src.relative_to(src_root).parent
    dst_dir.mkdir(parents=True, exist_ok=True)
    src.rename(_unique_path(dst_dir / src.name))
    return True


def _unique_path(dst: Path) -> Path:
    """Suffix ' 1', ' 2'... before the extension to keep old trash entries."""
    if not dst.exists():
        return dst
    i = 1
    while (candidate := dst.with_name(f'{dst.stem} {i}{dst.suffix}')).exists():
        i += 1
    return candidate
