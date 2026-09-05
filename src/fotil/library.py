from pathlib import Path

from .config import LibraryConfig
from .fs import iter_directory_files


class Library:
    def __init__(
        self,
        conf: LibraryConfig,
        dry_run: bool = False,
    ) -> None:
        self.conf: LibraryConfig = conf
        self.dry_run: bool = dry_run

    def cleanup_raw(self, pic_dir: Path, raw_dir: Path):
        """Remove raw files that have no corresponding processed files.

        Args:
            raw_dir (Path): directory containing raw files to clean up
            pic_dir (Path): directory containing processed pictures
        """
        print(f'cleaning up: {raw_dir}')
        pic_files = {
            f.stem
            for f in iter_directory_files(pic_dir, file_filter=self.conf.pic_file_filter)
        }

        for f in iter_directory_files(raw_dir, file_filter=self.conf.raw_file_filter):
            if f.stem in pic_files:
                continue

            src = (raw_dir / f).absolute()
            src_reldir = src.relative_to(self.conf.raw_dir).parent
            trash_dir = self.conf.trash_dir / src_reldir
            if not trash_dir.exists():
                print(f'creating trash_dir: {trash_dir}')
                if not self.dry_run:
                    trash_dir.mkdir(parents=True, exist_ok=True)

            print(f'trashing {f}')
            if not self.dry_run:
                src.rename(trash_dir / src.name)
