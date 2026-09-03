"""`fotil web`: serve the picture review web UI."""

from typing import Annotated

import typer

from . import app, cli_options


@app.command(name='web')
def web(
    host: Annotated[
        str, typer.Option('--host', '-H', help='Host to bind the server to.')
    ] = '127.0.0.1',
    port: Annotated[
        int, typer.Option('--port', '-p', help='Port to bind the server to.')
    ] = 8000,
):
    """Start the local web UI server for reviewing pictures."""
    import uvicorn

    from fotil.web import create_app

    uvicorn.run(create_app(cli_options.config_path), host=host, port=port)
