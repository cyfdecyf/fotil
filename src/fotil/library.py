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
        print(f'cleaning up: {raw_dir}')
        pic_files = {
            f.stem
            for f in iter_directory_files(pic_dir, file_filter=self.conf.pic_file_filter)
        }

        trash_dir_printed = False

        for f in iter_directory_files(raw_dir, file_filter=self.conf.raw_file_filter):
            if f.stem not in pic_files:
                continue

            src = (raw_dir / f).absolute()
            src_reldir = src.relative_to(self.conf.raw_dir).parent
            trash_dir = self.conf.trash_dir / src_reldir
            if not trash_dir_printed:
                print(f'trash_dir: {trash_dir}')
                trash_dir_printed = True

            print(f'trashing {f}')
            if not self.dry_run:
                trash_dir.mkdir(parents=True, exist_ok=True)
                src.rename(trash_dir / src.name)
