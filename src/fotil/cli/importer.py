from typing import Annotated, Optional

import typer

from fotil import config
from fotil.importer import Importer

from . import app, state, get_config


def _import(import_conf: config.ImportConfig, dry_run: bool):
    imp = Importer(import_conf, verbose=state['verbose'], dry_run=dry_run)
    imp.import_to_dst()


@app.command(name='import')
def importer(
    imp: Annotated[
        Optional[str], typer.Option('--importer', '-i', help='Name of the importer.')  # noqa: UP007
    ] = None,
    dry_run: Optional[bool] = False,  # noqa: UP007
):
    """
    Import src_dir in import config to dst_dir.
    """
    conf = get_config()
    if imp and imp not in conf.importer:
        print(f'importer "{imp}" not found in config')
        typer.Exit(code=1)

    imps = conf.importer.values() if imp is None else [conf.importer[imp]]

    for i in imps:
        if i.enabled:
            _import(i, dry_run)
