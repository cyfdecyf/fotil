from typing import Annotated, Optional

import typer

from fotil import filedb
from fotil.config import ImportConfig

from . import state, get_config


app = typer.Typer(help='Manage file database.')


def _scan_one(import_conf: ImportConfig):
    fdb = filedb.get(
        import_conf.filedb_path,
        import_conf.hash_bytes,
        verbose=state['verbose'],
    )
    fdb.scan(import_conf.dst_dir)
    if import_conf.ref_dir:
        for ref_dir in import_conf.ref_dir:
            fdb.scan(ref_dir, file_filter=import_conf.file_filter)


@app.command()
def scan(
    importer: Annotated[
        Optional[str], typer.Option('--importer', '-i', help='name of the importer')  # noqa: UP007
    ] = None,
):
    """
    Scan dst_dir in importer and build hash db under that dir.
    """
    conf = get_config()
    if importer and importer not in conf.importer:
        print(f'importer "{importer}" not found in config')
        typer.Exit(code=1)

    imps = conf.importer.values() if importer is None else [conf.importer[importer]]

    for imp in imps:
        if imp.enabled:
            _scan_one(imp)
