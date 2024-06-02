from . import app
from . import importer as _  # noqa: F401
from .filedb import app as filedb
from .library import app as lib


app.add_typer(filedb, name='fdb')
app.add_typer(lib, name='lib')
