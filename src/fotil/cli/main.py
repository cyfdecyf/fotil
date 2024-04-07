from . import app
from . import importer as _  # noqa: F401
from .filedb import app as filedb


app.add_typer(filedb, name='fdb')
