import hashlib
import sqlite3

from collections import defaultdict
from collections.abc import Callable
from functools import cached_property
from pathlib import Path

from . import fs


class FileDB:
    """
    FileDB maintains file hashes which is used to check if file has already been imported.
    """

    hash_table_name = 'file_sha1sum'

    def __init__(self, dbfile: Path, max_hash_bytes: int, verbose: bool = False):
        self.max_hash_bytes = max_hash_bytes
        self.dbfile = dbfile
        self.verbose = verbose
        self.hash2file: dict[bytes, list[Path]] = defaultdict(list)
        self._pending_file_hash: list[tuple[str, str]] = []

        self.load()

    @cached_property
    def conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.dbfile)
        create_table_query = f"""
            CREATE TABLE IF NOT EXISTS {self.hash_table_name} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT UNIQUE,
                sha1sum TEXT
            );
        """
        # CREATE INDEX idx_file_path ON {self.hash_table_name}(file_path);
        conn.execute(create_table_query)
        return conn

    def sha1sum(self, fpath: Path | str) -> bytes:
        """Calculate sh1sum for the starting max_length bytes."""
        sha1 = hashlib.sha1()
        with open(fpath, 'rb') as f:
            sha1.update(f.read(self.max_hash_bytes))
        return sha1.digest()

    def exists(self, hashsum: bytes):
        return hashsum in self.hash2file

    def upsert(self, fpath: Path, hashsum: bytes) -> bool:
        flist = self.hash2file[hashsum]
        if fpath in flist:
            return False

        flist.append(fpath)
        if len(flist) >= 2:
            str_flist = '\n'.join(f'\t{f}' for f in flist)
            print(f'duplicate files:\n{str_flist}')

        self._pending_file_hash.append((str(fpath), hashsum.hex()))
        return True

    def commit(self) -> None:
        # Upsert the data into the database.
        insert_query = f"""
            INSERT INTO {self.hash_table_name} (file_path, sha1sum)
            VALUES (?, ?)
            ON CONFLICT(file_path) DO UPDATE SET sha1sum = excluded.sha1sum
        """
        if len(self._pending_file_hash) == 0:
            return

        try:
            with self.conn:
                self.conn.executemany(insert_query, self._pending_file_hash)
        except Exception as e:
            print(f'error inserting file hashsum into database: {e}')

        if self.verbose:
            print(f'upserted {len(self._pending_file_hash)} records to hash database')
        self._pending_file_hash.clear()

    def scan(
        self,
        directory: Path,
        file_filter: Callable[[Path], bool] | None = None,
    ) -> None:
        print(f'filedb scanning {directory}')
        for fpath in fs.iter_directory_files(directory, file_filter=file_filter):
            h = self.sha1sum(directory / fpath)
            if self.exists(h):
                if self.verbose:
                    print(f'already in filedb: {fpath}')
                continue

            if self.verbose:
                print(f'hash: {h.hex()} file: {fpath}')
            self.upsert(fpath, h)

        self.commit()

    def load(self):
        select_all_query = f"""
            SELECT file_path, sha1sum FROM {self.hash_table_name}
        """
        cursor = self.conn.execute(select_all_query)
        for row in cursor:
            fpath, sha1sum = row
            hashbytes = bytes.fromhex(sha1sum)
            self.hash2file[hashbytes].append(Path(fpath))


_file_db: dict[Path | str, FileDB] = {}


def get(dbfile: Path, max_hash_bytes: int, verbose: bool = False) -> FileDB:
    db = _file_db.get(dbfile)
    if not db:
        db = FileDB(dbfile, max_hash_bytes, verbose=verbose)
        _file_db[dbfile] = db
    return db
