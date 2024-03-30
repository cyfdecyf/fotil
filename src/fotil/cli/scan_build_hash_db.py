from typing import Optional

import typer

from fotil import config
from fotil.hash import HashDB

from . import app, state


def scan_build_hash_db_one(imp: config.ImportConfig):
    hdb = HashDB(
        imp.dst_dir / imp.hash_db, imp.hash_bytes, hex_hash=imp.hex_hash, verbose=state['verbose']
    )
    hdb.scan_build_hash_db(imp.dst_dir)
    if imp.ref_dir:
        for ref_dir in imp.ref_dir:
            hdb.scan_build_hash_db(ref_dir)


@app.command()
def scan_build_hash_db(importer: Optional[str] = None):  # noqa: UP007
    """
    Scan dst_dir in importer and build hash db under that dir.
    """
    config = state['config']
    if importer and importer not in config.importer:
        print(f'Importer "{importer}" not found in config')
        typer.Exit(code=1)

    imps = config.importer.values() if importer is None else [config.importer[importer]]

    for imp in imps:
        scan_build_hash_db_one(imp)
