import hashlib
import sqlite3

from collections import defaultdict
from functools import cached_property
from pathlib import Path

from . import fs


class HashDB:
    """
    HashDB contains
    """

    hash_table_name = 'file_sha1sum'

    def __init__(
        self, dbfile: Path, max_hash_bytes: int, verbose: bool = False, hex_hash: bool = False
    ):
        self.max_hash_bytes = max_hash_bytes
        self.dbfile = dbfile
        self.verbose = verbose
        self.hex_hash = hex_hash

    @cached_property
    def conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.dbfile)
        create_table_query = f"""
            CREATE TABLE IF NOT EXISTS {self.hash_table_name} (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT UNIQUE,
                sha1sum BLOB
            );
        """
        # CREATE INDEX idx_file_path ON {self.hash_table_name}(file_path);
        conn.execute(create_table_query)
        return conn

    def close(self) -> None:
        self.conn.close()

    def sha1sum(self, fpath: Path | str) -> bytes | str:
        """Calculate sh1sum for the starting max_length bytes."""
        sha1 = hashlib.sha1()
        with open(fpath, 'rb') as f:
            sha1.update(f.read(self.max_hash_bytes))
        return sha1.digest()

    def scan_build_hash_db(self, directory: Path) -> None:
        print(f'scanning {directory} to build hash db')
        # sha1sum -> [file_path]
        file_hash: dict[bytes | str, list[Path]] = defaultdict(list)
        for fpath in fs.iter_directory_files(directory):
            h = self.sha1sum(directory / fpath)
            if self.verbose:
                print(f'hash: {h.hex()} file: {fpath}')
            flist = file_hash[h]
            flist.append(fpath)
            if len(flist) > 1:
                str_flist = '\n'.join(f'\t{f}' for f in flist)
                print(f'Duplicate files:\n{str_flist}')

        # Prepare the data for insertion.
        data = []
        for hash, file_paths in file_hash.items():
            for file_path in file_paths:
                if self.hex_hash:
                    data.append((str(file_path), hash.hex()))
                else:
                    data.append((str(file_path), hash))

        # Upsert the data into the database.
        insert_query = f"""
            INSERT INTO {self.hash_table_name} (file_path, sha1sum)
            VALUES (?, ?)
            ON CONFLICT(file_path) DO UPDATE SET sha1sum = excluded.sha1sum
        """
        try:
            self.conn.executemany(insert_query, data)
            self.conn.commit()
        except Exception as e:
            print(f'Error inserting data into the database: {e}')

        if self.verbose:
            print(f'Upserted {self.conn.total_changes} records to hash database')

    def load_all_hashes(self):
        select_all_query = f"""
            SELECT file_path, sha1sum FROM {self.hash_table_name}
        """
        self.hashes = set()
        cursor = self.conn.execute(select_all_query)
        for row in cursor:
            _, sha1sum = row
            if self.hex_hash:
                self.hashes.add(bytes.fromhex(sha1sum))
            else:
                self.hashes.add(sha1sum)

    def file_exists(self, fpath: Path) -> bool:
        h = self.sha1sum(fpath)
        return h in self.hashes
