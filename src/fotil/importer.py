import shutil

from . import config, filedb, fs


class Importer:
    def __init__(
        self, conf: config.ImportConfig, verbose: bool = False, dry_run: bool = False
    ) -> None:
        self.conf = conf
        self.dry_run = dry_run
        self.filedb = filedb.get(conf.filedb_path, conf.hash_bytes)
        self.verbose = verbose

    def import_to_dst(self):
        """Import files from src_dir to dst_dir."""
        src_dir = self.conf.src_dir
        for fpath in fs.iter_directory_files(src_dir, file_filter=self.conf.file_filter):
            h = self.filedb.sha1sum(src_dir / fpath)
            if self.filedb.exists(h):
                if self.verbose:
                    print(f'already in filedb: {fpath}')
                continue

            if self.conf.keep_src_dir:
                dst = self.conf.dst_dir / fpath
            else:
                # TODO import different files to different dir.
                msg = 'not implemented yet'
                raise NotImplementedError(msg)

            if self.verbose or self.dry_run:
                print(f'copy {fpath} to {dst}')

            if self.dry_run:
                continue

            dst_dir = dst.parent
            if not dst_dir.exists():
                dst_dir.mkdir(parents=True, exist_ok=True)

            # This preserves mode, ownership, timestamp.
            shutil.copy2(fpath, dst)
            # Record path in imported directory.
            self.filedb.upsert(dst, h)

        if self.dry_run:
            return
        self.filedb.commit()
