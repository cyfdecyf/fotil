from typing import Optional

import typer

from fotil import config
from fotil.filedb import FileDB

from . import state


app = typer.Typer()


def _scan_one(import_conf: config.ImportConfig):
    fdb = FileDB(
        import_conf.dst_dir / import_conf.hash_db,
        import_conf.hash_bytes,
        verbose=state['verbose'],
    )
    fdb.scan(import_conf.dst_dir)
    if import_conf.ref_dir:
        for ref_dir in import_conf.ref_dir:
            fdb.scan(ref_dir, file_filter=import_conf.file_filter)


@app.command()
def scan(importer: Optional[str] = None):  # noqa: UP007
    """
    Scan dst_dir in importer and build hash db under that dir.
    """
    config = state['config']
    if importer and importer not in config.importer:
        print(f'Importer "{importer}" not found in config')
        typer.Exit(code=1)

    imps = config.importer.values() if importer is None else [config.importer[importer]]

    for imp in imps:
        _scan_one(imp)
