import tomllib

from pathlib import Path

from pydantic import BaseModel


SUFFIX_SET = {'.jpg', '.jpeg', '.mov', '.mp4', '.heic', '.hif', '.raf'}


class ImportConfig(BaseModel):
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
    ref_dir: list[Path] | None = None
    hash_bytes: int = 1 * 1024**2  # 1MB by default.
    suffixes: set[str] = SUFFIX_SET
    keep_src_dir: bool
    dedup: bool = True
    hash_db: str = '.fotil.sqlite3'
    enabled: bool = True

    def file_filter(self, f: Path) -> bool:
        return f.suffix.lower() in self.suffixes

    @property
    def filedb_path(self) -> Path:
        return self.dst_dir / self.hash_db


class Config(BaseModel):
    importer: dict[str, ImportConfig]


def load_config(fname: Path | str) -> Config:
    with open(fname, 'rb') as f:
        conf = tomllib.load(f)
    return Config(**conf)
