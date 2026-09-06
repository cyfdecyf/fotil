"""HTTP routes for the web UI."""

from litestar import Request, get, post
from litestar.exceptions import NotFoundException, ValidationException
from litestar.params import FromQuery
from litestar.response import File, Response, Template

from fotil.config import Config, load_config

from . import service
from .service import InvalidPathError, TranscodeError, UnknownLibraryError


# 400 for user input problems (bad paths, unknown libraries).
BadRequest = ValidationException


def _config(request: Request) -> Config:
    """Reload the config file on every request, so edits apply immediately."""
    return load_config(request.app.state.config_path)


def _library(request: Request, library: str | None):
    """Resolve the library for a request, mapping errors to HTTP statuses."""
    conf = _config(request)
    try:
        return conf, service.get_library(conf, library)
    except UnknownLibraryError as exc:
        raise NotFoundException(str(exc)) from exc


def _breadcrumb(dir_rel: str) -> list[tuple[str, str]]:
    """(name, relative dir) pairs for the breadcrumb, root first."""
    crumbs = [('根目录', '')]
    parts = [p for p in dir_rel.split('/') if p]
    for i, name in enumerate(parts):
        crumbs.append((name, '/'.join(parts[: i + 1])))
    return crumbs


def _grid_context(lib_conf, library: str, dir_rel: str, offset: int) -> dict:
    subdirs = service.list_subdirs(lib_conf, dir_rel)
    pics, total = service.list_pics(lib_conf, dir_rel, offset=offset)
    shown = offset + len(pics)
    return {
        'library': library,
        'dir': dir_rel,
        'subdirs': subdirs,
        'pics': [{'rel': str(p), 'name': p.name} for p in pics],
        'total': total,
        'offset': offset,
        'page_size': service.PAGE_SIZE,
        'has_more': shown < total,
        'remaining': total - shown,
        'breadcrumb': _breadcrumb(dir_rel),
    }


@get('/', sync_to_thread=True)
def index(
    request: Request, library: FromQuery[str | None] = None, dir: FromQuery[str] = ''
) -> Template:
    conf, lib_conf = _library(request, library)
    name = library or conf.default_library
    try:
        ctx = _grid_context(lib_conf, name, dir, 0)
        ctx['nodes'] = service.list_subdirs_details(lib_conf, '')
    except InvalidPathError as exc:
        raise BadRequest(str(exc)) from exc
    ctx['libraries'] = sorted(conf.library)
    ctx['trash_dir'] = str(lib_conf.trash_dir)
    return Template(template_name='index.html', context=ctx)


@get('/tree', sync_to_thread=True)
def tree(
    request: Request, library: FromQuery[str | None] = None, dir: FromQuery[str] = ''
) -> Template:
    """Children of one directory tree node, loaded lazily by HTMX."""
    conf, lib_conf = _library(request, library)
    try:
        nodes = service.list_subdirs_details(lib_conf, dir)
    except InvalidPathError as exc:
        raise BadRequest(str(exc)) from exc
    return Template(
        template_name='_tree.html',
        context={
            'nodes': nodes,
            'dir': dir,
            'library': library or conf.default_library,
        },
    )


@get('/grid', sync_to_thread=True)
def grid(
    request: Request,
    library: FromQuery[str | None] = None,
    dir: FromQuery[str] = '',
    offset: FromQuery[int] = 0,
) -> Template:
    """Photo grid for one directory; offset > 0 returns only more photo rows."""
    conf, lib_conf = _library(request, library)
    name = library or conf.default_library
    try:
        ctx = _grid_context(lib_conf, name, dir, max(offset, 0))
    except InvalidPathError as exc:
        raise BadRequest(str(exc)) from exc
    template = '_grid.html' if offset <= 0 else '_grid_more.html'
    return Template(template_name=template, context=ctx)


@get('/image', sync_to_thread=True)
def image(
    request: Request,
    library: FromQuery[str | None] = None,
    path: FromQuery[str] = '',
    size: FromQuery[str | None] = None,
) -> File:
    """Serve a picture, transcoding HEIF files to cached JPEG previews."""
    conf, lib_conf = _library(request, library)
    if size is not None and size not in service.IMAGE_VARIANTS:
        raise BadRequest(f'unknown image size {size!r}')
    try:
        src, media_type = service.image_file(
            lib_conf, path, size=size, size_check=conf.web.sips_size_check
        )
    except InvalidPathError as exc:
        raise BadRequest(str(exc)) from exc
    except FileNotFoundError as exc:
        raise NotFoundException(str(exc)) from exc
    except TranscodeError as exc:
        raise BadRequest(str(exc)) from exc
    # /image URLs are content-constant (photos are never edited in place),
    # so browsers may cache responses forever without revalidating.
    return File(
        path=src,
        media_type=media_type,
        content_disposition_type='inline',
        headers={'cache-control': 'private, max-age=31536000, immutable'},
    )


@post('/cleanup', status_code=200)
async def cleanup(request: Request) -> Response:
    """Move the selected pics and their same-stem raws into trash_dir."""
    form = await request.form()
    library = form.get('library')
    _, lib_conf = _library(
        request, library if isinstance(library, str) and library else None
    )
    pics = [p for p in form.getall('pics') if isinstance(p, str) and p]
    try:
        result = service.cleanup_pics(lib_conf, pics)
    except InvalidPathError as exc:
        raise BadRequest(str(exc)) from exc
    html = request.app.template_engine.get_template('_cleanup_result.html').render(
        result=result, trash_dir=str(lib_conf.trash_dir)
    )
    return Response(
        content=html,
        media_type='text/html',
        headers={'HX-Trigger': '{"grid-refresh": true}'},
    )
