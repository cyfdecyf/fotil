from pathlib import Path
from typing import Annotated

import typer

from fotil import config


state = {
    'verbose': False,
    'config': None,
}

app = typer.Typer(name='fotil', help='Camera photo & video utilities.')


@app.callback()
def cli_opts(
    verbose: bool = False,
    conf: Annotated[
        Path, typer.Option('--config', '-c', help='Path to config file.')
    ] = './fotil.toml',
):
    state['verbose'] = verbose
    state['config'] = config.load_config(conf)
