from pathlib import Path
from typing import Annotated

import typer

from fotil.library import Library

from . import get_config


app = typer.Typer(
    help='Picture processing utilities.',
    no_args_is_help=True,
    pretty_exceptions_enable=False,
    context_settings={'help_option_names': ['-h', '--help']},
)


@app.command()
def cleanup_raw(
    raw_dir: Path,
    pic_dir: Path | None = None,
    library: Annotated[
        str | None, typer.Option('--library', '-l', help='Name of the library.')
    ] = None,
    dry_run: bool = False,
):
    conf = get_config()
    if library is None:
        library = conf.default_library
    lib_conf = conf.library[library]

    raw_dir = raw_dir.absolute()
    try:
        relative_dir = raw_dir.relative_to(lib_conf.raw_dir)
    except ValueError:
        print(f'raw_dir {raw_dir} not in library {library} raw_dir {lib_conf.raw_dir}')
        raise typer.Exit(code=1) from None

    if pic_dir is None:
        # Resolve to same relative directory under pic_dir.
        if relative_dir.name == 'raw':
            relative_dir = relative_dir.parent
        pic_dir = lib_conf.pic_dir / relative_dir
    else:
        # For pic_dir, we allow it to be outside the library pic_dir.
        pic_dir = pic_dir.absolute()

    lib = Library(conf=lib_conf, dry_run=dry_run)
    lib.cleanup_raw(pic_dir, raw_dir)
