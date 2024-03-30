import typer

from fotil import config


app = typer.Typer()


state = {
    'verbose': False,
    'config': None,
}


@app.callback()
def cli_opts(verbose: bool = False, conf: str = 'fotil.toml'):
    state['verbose'] = verbose
    state['config'] = config.load_config(conf)
