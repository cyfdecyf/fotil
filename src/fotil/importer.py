import shutil

from datetime import datetime
from pathlib import Path

from . import config, filedb, fs
from .exiftool import Exiftool


class Importer:
    def __init__(
        self,
        conf: config.ImportConfig,
        verbose: bool = False,
        dry_run: bool = False,
        batch_size: int = 50,
    ) -> None:
        self.conf = conf
        self.dry_run = dry_run
        self.filedb = filedb.get(conf.filedb_path, conf.hash_bytes)
        self.verbose = verbose
        self.batch_size = batch_size

    def import_to_dst(self):
        """Import files from src_dir to dst_dir."""
        src_dir = self.conf.src_dir
        # Do batch import to commit filedb more frequently, so that interrupted run
        # won't lose too much work. Besides, this allows calling exiftool processing
        # multiple files a time, which is faster.
        import_batch = []
        for fpath in fs.iter_directory_files(src_dir, file_filter=self.conf.file_filter):
            h = self.filedb.sha1sum(src_dir / fpath)
            if self.filedb.exists(h):
                if self.verbose:
                    print(f'already in filedb: {fpath}')
                continue

            import_batch.append((fpath, h))

            if len(import_batch) >= self.batch_size:
                self.do_import(import_batch)
                import_batch.clear()

        if len(import_batch) > 0:
            self.do_import(import_batch)
            import_batch.clear()

    def gen_dst_by_date(self, dt: datetime, suffix: str) -> str:
        """
        Args:
            date: date string in format 'YYYY:MM:DD HH:MM:SS'. From exiftool.
        """
        d = Path(dt.strftime('%Y/%m'))
        name = dt.strftime('%Y-%m-%d_%H-%M-%S')
        return d / f'{name}{suffix}'

    def do_import(self, batch_src: list[tuple[Path, str]]):
        fpaths = [src[0] for src in batch_src]
        if self.conf.keep_src_dir:
            dst_paths = fpaths
        else:
            exiftool = Exiftool()
            exifs = exiftool.read(fpaths, cd_dir=self.conf.src_dir)
            dates = (exiftool.create_date(ex) for ex in exifs)
            dst_paths = (
                self.gen_dst_by_date(d, f.suffix)
                for f, d in zip(fpaths, dates, strict=False)
            )

        for (fpath, hash), rel_dst in zip(batch_src, dst_paths, strict=False):
            dst = self.conf.dst_dir / rel_dst
            if dst.exists():
                for i in range(1, 100):
                    new_dst = dst.with_name(f'{dst.stem} ({i}){dst.suffix}')
                    if not new_dst.exists():
                        dst = new_dst
                        break
                else:
                    raise RuntimeError(f'100 same file name for {dst}, possible bug?')

            print(f'import {fpath} to {dst}')

            if self.dry_run:
                continue

            dst_dir = dst.parent
            if not dst_dir.exists():
                dst_dir.mkdir(parents=True, exist_ok=True)

            # This preserves mode, ownership, timestamp.
            shutil.copy2(self.conf.src_dir / fpath, dst)
            # Record path in imported directory.
            self.filedb.upsert(dst, hash)

        if self.dry_run:
            return
        self.filedb.commit()
