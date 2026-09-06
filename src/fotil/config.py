from pathlib import Path
from typing import Any

import msgspec

from msgspec import Struct, field


DEFAULT_VIDEO_SUFFIXES = {'.mov', '.mp4'}
DEFAULT_RAW_SUFFIXES = {'.arw', '.cr2', '.dng', '.nef', '.raf'}
DEFAULT_PIC_SUFFIXES = {'.heic', '.hif', '.jpeg', '.jpg', '.png', '.jxl'}
DEFAULT_SUFFIXES = DEFAULT_VIDEO_SUFFIXES | DEFAULT_RAW_SUFFIXES | DEFAULT_PIC_SUFFIXES


def dec_hook(tp: type, obj: Any) -> Any:
    if tp is Path:
        return Path(obj)
    return obj


class ImportConfig(Struct):
    """
    ImportDir defines import src and target directory, along with other
    settings.

    Attributes:
        hash_bytes (int): number of bytes to hash for each file. Do not change
            this value after import is run.
        keep_src_dir: keep source directory structure when importing into dst_dir.
        ref_dir (list[Path]): files in those directories are also considered as
            already imported in dst_dir.
    """

    src_dir: Path
    dst_dir: Path
    keep_src_dir: bool
    ref_dir: list[Path] | None = None
    hash_bytes: int = 1 * 1024**2  # 1MB by default.
    suffixes: set[str] = field(default_factory=lambda: DEFAULT_SUFFIXES.copy())
    dedup: bool = True
    hash_db: str = '.fotil.sqlite3'
    enabled: bool = True

    def file_filter(self, f: Path) -> bool:
        return f.suffix.lower() in self.suffixes

    @property
    def filedb_path(self) -> Path:
        return self.dst_dir / self.hash_db


class LibraryConfig(Struct):
    pic_dir: Path
    raw_dir: Path
    trash_dir: Path
    pic_suffixes: list[str] = field(default_factory=lambda: DEFAULT_PIC_SUFFIXES.copy())
    raw_suffixes: list[str] = field(default_factory=lambda: DEFAULT_RAW_SUFFIXES.copy())

    def __post_init__(self):
        self._validate_suffixes(self.pic_suffixes, 'pic')
        self._validate_suffixes(self.raw_suffixes, 'raw')

    @staticmethod
    def _validate_suffixes(suffixes: list[str], msg: str):
        # Suffixes must start with dot.
        for s in suffixes:
            if not s.startswith('.'):
                raise ValueError(f'{msg} suffix {s} must start with dot')

    def raw_file_filter(self, f: Path) -> bool:
        """Check if file is a raw file."""
        return f.suffix.lower() in self.raw_suffixes

    def pic_file_filter(self, f: Path) -> bool:
        """Check if file is a picture file."""
        return f.suffix.lower() in self.pic_suffixes


class GeotagConfig(Struct):
    gpslog_dir: Path | None = None
    default_timezone: str = 'auto'
    default_pattern: str = '*.jpg'
    tag_file: str = 'tag.jpg'


class WebConfig(Struct):
    """
    Web UI settings.

    Attributes:
        sips_size_check: probe the image size before sips transcoding and
            shrink only images already larger than the preview cap, matching
            Pillow's never-upscale thumbnail behavior. Off by default: camera
            originals are always larger than the cap, so the unconditional
            shrink saves the probe.
    """

    sips_size_check: bool = False


class Config(Struct):
    default_library: str
    library: dict[str, LibraryConfig]
    importer: dict[str, ImportConfig]
    geotag: GeotagConfig = field(default_factory=GeotagConfig)
    web: WebConfig = field(default_factory=WebConfig)


def load_config(fname: Path | str) -> Config:
    with open(fname, 'rb') as f:
        return msgspec.toml.decode(f.read(), type=Config, dec_hook=dec_hook)
