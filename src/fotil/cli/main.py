from pathlib import Path
from typing import Annotated

import typer

from fotil import config

from . import state
from .filedb import app as filedb


app = typer.Typer()


@app.callback()
def cli_opts(
    verbose: bool = False,
    conf: Annotated[
        Path, typer.Option('--config', '-c', help='path to config file')
    ] = './fotil.toml',
):
    state['verbose'] = verbose
    state['config'] = config.load_config(conf)


app.add_typer(filedb, name='fdb')
