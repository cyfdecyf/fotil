from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated

import typer

from fotil import config


@dataclass
class CliOptions:
    verbose: bool = False
    config_path: Path = field(
        default_factory=lambda: Path('~/.config/fotil/fotil.toml').expanduser()
    )
    _config_cache: config.Config | None = field(default=None, repr=False)


cli_options = CliOptions()

DEFAULT_CONFIG_PATH = Path('~/.config/fotil/fotil.toml').expanduser()

class FotilApp(typer.Typer):
    """
    Typer app that shows help when a group is invoked without a subcommand, and
    never lets typer catch unexpected exceptions (plain tracebacks instead).
    Commands that require arguments opt into the same behavior individually
    with ``no_args_is_help=True`` so commands with all-optional arguments can
    still run bare.
    """

    def __init__(self, **kwargs):
        kwargs.setdefault('no_args_is_help', True)
        kwargs.setdefault('pretty_exceptions_enable', False)
        context_settings = kwargs.setdefault('context_settings', {})
        context_settings.setdefault('help_option_names', ['-h', '--help'])
        super().__init__(**kwargs)


app = FotilApp(
    name='fotil',
    help='Camera photo & video utilities.',
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
    if cli_options._config_cache is None:
        if not cli_options.config_path.exists():
            raise FileNotFoundError(f'Config file not found: {cli_options.config_path}')
        cli_options._config_cache = config.load_config(cli_options.config_path)
    return cli_options._config_cache


@app.callback()
def cli_opts(
    conf: Annotated[
        Path, typer.Option('--config', '-c', help='Path to config file.')
    ] = DEFAULT_CONFIG_PATH,
    *,
    verbose: bool = False,
):
    cli_options.verbose = verbose
    cli_options.config_path = conf
    cli_options._config_cache = None
