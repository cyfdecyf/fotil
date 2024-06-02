from pathlib import Path

from .config import LibraryConfig
from .fs import iter_directory_files


class Library:
    def __init__(
        self,
        conf: LibraryConfig,
        verbose: bool = False,
        dry_run: bool = False,
    ) -> None:
        self.conf = conf
        self.verbose = verbose
        self.dry_run = dry_run
        if self.dry_run:
            self.verbose = True

    def cleanup_raw(self, pic_dir: Path, raw_dir: Path):
        """Remove raw files that have been processed.

        Args:
            raw_dir (Path): directory containing raw files to clean up
            pic_dir (Path): directory containing processed pictures
        """
        pic_files = {
            f.stem
            for f in iter_directory_files(pic_dir, file_filter=self.conf.pic_file_filter)
        }

        for f in iter_directory_files(raw_dir, file_filter=self.conf.raw_file_filter):
            if f.stem not in pic_files:
                continue

            src_dir = f.absolute().parent.relative_to(self.conf.raw_dir)
            dst_dir = self.conf.trash_dir / src_dir
            if self.verbose:
                print(f'trash {f} to {dst_dir}')
            if not self.dry_run:
                dst_dir.mkdir(parents=True, exist_ok=True)
                f.rename(dst_dir / f.name)
