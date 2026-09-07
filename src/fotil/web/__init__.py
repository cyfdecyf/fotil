"""Web UI application factory."""

from pathlib import Path

from litestar import Litestar
from litestar.plugins.jinja import JinjaTemplateEngine
from litestar.static_files import create_static_files_router
from litestar.template import TemplateConfig

from fotil.config import load_config

from . import service
from .routes import cleanup, grid, image, index, tree


def create_app(config_path: Path) -> Litestar:
    """Build the Litestar app serving the picture review UI.

    Args:
        config_path: fotil config file, reloaded on every request.
    """
    config_path = Path(config_path).expanduser().resolve()
    web_dir = Path(__file__).parent

    def prune_cache() -> None:
        # Reload so a limit edited mid-session applies at shutdown.
        conf = load_config(config_path)
        service.prune_cache(conf.web.cache_max_bytes)

    app = Litestar(
        route_handlers=[
            index,
            tree,
            grid,
            image,
            cleanup,
            create_static_files_router(path='/static', directories=[web_dir / 'static']),
        ],
        template_config=TemplateConfig(
            directory=web_dir / 'templates', engine=JinjaTemplateEngine
        ),
        on_startup=[prune_cache],
        on_shutdown=[prune_cache],
    )
    app.state.config_path = config_path
    return app
