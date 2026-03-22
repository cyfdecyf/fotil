from pathlib import Path
from typing import Annotated

import typer

from fotil import config


state = {
    'verbose': False,
    '_config_path': None,
    '_config_cache': None,
}

DEFAULT_CONFIG_PATH = Path('~/.config/fotil/fotil.toml').expanduser()

app = typer.Typer(
    name='fotil',
    help='Camera photo & video utilities.',
    context_settings={'help_option_names': ['-h', '--help']},
)


def get_config() -> config.Config:
    """
    Lazy load configuration file.

    Returns:
        Config: The loaded configuration object.

    Raises:
        FileNotFoundError: If the config file doesn't exist.
        msgspec.ValidationError: If the config file is invalid.
    """
    if state['_config_cache'] is None:
        conf_path = state['_config_path']
        if not Path(conf_path).exists():
            raise FileNotFoundError(f'Config file not found: {conf_path}')
        state['_config_cache'] = config.load_config(conf_path)
    return state['_config_cache']


@app.callback()
def cli_opts(
    verbose: bool = False,
    conf: Annotated[
        Path, typer.Option('--config', '-c', help='Path to config file.')
    ] = DEFAULT_CONFIG_PATH,
):
    state['verbose'] = verbose
    state['_config_path'] = conf
    state['_config_cache'] = None  # Clear cache when config path changes
