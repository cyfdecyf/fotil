from pathlib import Path
from typing import Annotated

import typer

from fotil.library import Library

from . import get_config, state


app = typer.Typer(help='Picture processing utilities.')


@app.command()
def cleanup_raw(
    library: Annotated[str, typer.Option('--library', '-l', help='Name of the library.')],
    raw_dir: Path,
    pic_dir: Path | None = None,
    dry_run: bool = False,
):
    conf = get_config()
    lib_conf = conf.library[library]

    raw_dir = raw_dir.absolute()
    try:
        relative_dir = raw_dir.relative_to(lib_conf.raw_dir)
    except ValueError:
        print(f'raw_dir {raw_dir} not in library {library} raw_dir {lib_conf.raw_dir}')
        typer.Exit(code=1)
        return  # avoid ruff warning for relative_dir

    if pic_dir is None:
        # Resolve to same relative directory under pic_dir.
        if relative_dir.name == 'raw':
            relative_dir = relative_dir.parent
        pic_dir = lib_conf.pic_dir / relative_dir
    else:
        # For pic_dir, we allow it to be outside the library pic_dir.
        pic_dir = pic_dir.absolute()

    lib = Library(conf=lib_conf, verbose=state['verbose'], dry_run=dry_run)
    lib.cleanup_raw(pic_dir, raw_dir)
