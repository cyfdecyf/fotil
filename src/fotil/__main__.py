from .cli import app
from .cli import importer as _  # noqa: F401
from .cli.filedb import app as filedb
from .cli.library import app as lib


app.add_typer(filedb, name='fdb')
app.add_typer(lib, name='lib')
