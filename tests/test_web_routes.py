"""Tests for the web UI HTTP routes."""

import io

from pathlib import Path

import pillow_heif
import pytest

from litestar.testing import TestClient
from PIL import Image

from fotil.web import create_app, service


def write_pic(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (8, 6), 'red').save(path)


def write_hif(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    bio = io.BytesIO()
    pillow_heif.from_pillow(Image.new('RGB', (8, 6), 'blue')).save(bio, quality=60)
    path.write_bytes(bio.getvalue())


def write_raw(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'raw-data')


CONFIG_TEMPLATE = """\
default_library = 'main'

[library.main]
pic_dir = '{pic}'
raw_dir = '{raw}'
trash_dir = '{trash}'

[importer.main]
src_dir = '{pic}'
dst_dir = '{pic}'
keep_src_dir = false
"""


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Test client over a config whose library has pics and matching raws."""
    monkeypatch.setattr(service, 'CACHE_DIR', tmp_path / 'cache')

    pic = tmp_path / 'pic'
    raw = tmp_path / 'raw'
    trash = tmp_path / 'trash'
    write_pic(pic / '2024/05-01/a.jpg')
    write_hif(pic / '2024/05-01/b.hif')
    write_pic(pic / '2024/05-02/c.jpg')
    write_raw(raw / '2024/05-01/a.arw')
    write_raw(raw / '2024/05-01/b.arw')
    write_raw(raw / '2024/05-02/c.arw')
    write_raw(raw / '2024/05-02/orphan.arw')

    conf = tmp_path / 'fotil.toml'
    conf.write_text(CONFIG_TEMPLATE.format(pic=pic, raw=raw, trash=trash))

    with TestClient(app=create_app(conf)) as test_client:
        test_client.pic_dir = pic
        test_client.raw_dir = raw
        test_client.trash_dir = trash
        yield test_client


def test_index_renders_library_page(client):
    resp = client.get('/')
    assert resp.status_code == 200
    assert 'grid-root' in resp.text
    assert 'value="main" selected' in resp.text
    # The tree root lists the top level dirs.
    assert 'data-dir="2024"' in resp.text
    # Theme bootstrap: follows system by default, switcher present.
    assert 'fotil-theme' in resp.text
    assert 'id="theme-seg"' in resp.text


def test_index_unknown_library_is_404(client):
    assert client.get('/?library=nope').status_code == 404


def test_grid_renders_photos(client):
    resp = client.get('/grid?dir=2024/05-01')
    assert resp.status_code == 200
    assert 'data-pic-path="2024/05-01/a.jpg"' in resp.text
    assert 'data-pic-path="2024/05-01/b.hif"' in resp.text
    # Grid cards request the thumb variant of /image.
    assert 'path=2024/05-01/a.jpg&size=thumb' in resp.text


def test_grid_offset_returns_more_chunk(client):
    resp = client.get('/grid?dir=2024/05-01&offset=1')
    assert resp.status_code == 200
    assert 'grid-root' not in resp.text
    assert 'data-pic-path="2024/05-01/b.hif"' in resp.text
    assert 'data-pic-path="2024/05-01/a.jpg"' not in resp.text


def test_grid_renders_subdir_cards(client):
    resp = client.get('/grid?dir=')
    assert resp.status_code == 200
    assert 'dir=2024&offset=0' in resp.text  # subdir card link target

    deep = client.get('/grid?dir=2024')
    assert deep.status_code == 200
    assert 'dir=2024/05-01' in deep.text
    assert 'dir=2024/05-02' in deep.text


def test_grid_rejects_escape(client):
    assert client.get('/grid?dir=../../etc').status_code == 400
    assert client.get('/tree?dir=../../etc').status_code == 400


def test_tree_renders_children(client):
    resp = client.get('/tree?dir=2024')
    assert resp.status_code == 200
    assert 'data-dir="2024/05-01"' in resp.text
    assert 'data-dir="2024/05-02"' in resp.text


def test_tree_leaf_dirs_have_no_toggle(client):
    # 2024 contains subdirs -> one lazy-load toggle at the root level.
    root = client.get('/tree?dir=')
    assert root.text.count('data-loaded="false"') == 1
    # 05-01/05-02 are leaves -> no toggles rendered at all.
    deep = client.get('/tree?dir=2024')
    assert deep.status_code == 200
    assert 'data-loaded="false"' not in deep.text
    assert 'leaf' in deep.text


def test_image_serves_original(client):
    resp = client.get('/image?path=2024/05-01/a.jpg')
    assert resp.status_code == 200
    assert resp.headers['content-type'] == 'image/jpeg'
    assert resp.headers.get('content-disposition', '').startswith('inline')
    assert resp.content == (client.pic_dir / '2024/05-01/a.jpg').read_bytes()


def test_image_transcodes_hif(client):
    resp = client.get('/image?path=2024/05-01/b.hif')
    assert resp.status_code == 200
    assert resp.headers['content-type'] == 'image/jpeg'
    assert resp.content[:2] == b'\xff\xd8'  # JPEG magic, not HEIF


def test_image_thumb_variant(client, monkeypatch):
    """size=thumb serves a shrunken JPEG with an immutable cache header."""
    monkeypatch.setenv('FOTIL_TRANSCODER', 'pillow')
    big = client.pic_dir / '2024/05-01/big.jpg'
    big.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (3000, 2000), 'green').save(big)
    resp = client.get('/image?path=2024/05-01/big.jpg&size=thumb')
    assert resp.status_code == 200
    assert resp.headers['content-type'] == 'image/jpeg'
    assert resp.headers['cache-control'] == 'private, max-age=31536000, immutable'
    with Image.open(io.BytesIO(resp.content)) as im:
        assert max(im.size) <= service.THUMB_MAX_SIZE[0]


def test_image_cache_control_on_all_responses(client):
    """Every /image response carries the immutable cache header."""
    for query in ('path=2024/05-01/a.jpg', 'path=2024/05-01/b.hif&size=large'):
        resp = client.get(f'/image?{query}')
        assert resp.status_code == 200
        assert resp.headers['cache-control'] == 'private, max-age=31536000, immutable'


def test_image_unknown_size_is_400(client):
    resp = client.get('/image?path=2024/05-01/a.jpg&size=bogus')
    assert resp.status_code == 400


def test_image_size_check_from_web_config(tmp_path, monkeypatch):
    """web.sips_size_check reaches the transcode: a small HEIF keeps size."""
    monkeypatch.setattr(service, 'CACHE_DIR', tmp_path / 'cache')
    pic = tmp_path / 'pic'
    write_hif(pic / '2024/05-01/b.hif')
    conf = tmp_path / 'fotil.toml'
    conf.write_text(
        CONFIG_TEMPLATE.format(pic=pic, raw=tmp_path / 'raw', trash=tmp_path / 'trash')
        + '\n[web]\nsips_size_check = true\n'
    )
    with TestClient(app=create_app(conf)) as client:
        resp = client.get('/image?path=2024/05-01/b.hif')
    assert resp.status_code == 200
    with Image.open(io.BytesIO(resp.content)) as im:
        assert im.size == (8, 6)


def test_image_rejects_escape_and_missing(client):
    assert client.get('/image?path=../outside.jpg').status_code == 400
    assert client.get('/image?path=2024/05-01/gone.jpg').status_code == 404


def test_cleanup_moves_files_and_sets_refresh_header(client):
    resp = client.post('/cleanup', data={'library': 'main', 'pics': ['2024/05-01/a.jpg']})
    assert resp.status_code == 200
    assert 'grid-refresh' in resp.headers.get('HX-Trigger', '')
    assert '清理完成' in resp.text

    assert not (client.pic_dir / '2024/05-01/a.jpg').exists()
    assert not (client.raw_dir / '2024/05-01/a.arw').exists()
    assert (client.trash_dir / '2024/05-01/a.jpg').is_file()
    assert (client.trash_dir / '2024/05-01/a.arw').is_file()
    # Unselected files stay.
    assert (client.raw_dir / '2024/05-02/orphan.arw').is_file()


def test_cleanup_reports_skipped(client):
    resp = client.post('/cleanup', data={'library': 'main', 'pics': ['nope.jpg']})
    assert resp.status_code == 200
    assert '跳过 1 项' in resp.text
    assert (client.pic_dir / '2024/05-01/a.jpg').is_file()


def test_cleanup_multiple_pics_in_one_post(client):
    """Two checked pics arrive as a list under one form key."""
    resp = client.post(
        '/cleanup',
        data={'library': 'main', 'pics': ['2024/05-01/a.jpg', '2024/05-01/b.hif']},
    )
    assert resp.status_code == 200
    assert '清理完成' in resp.text
    assert not (client.pic_dir / '2024/05-01/a.jpg').exists()
    assert not (client.pic_dir / '2024/05-01/b.hif').exists()
    assert (client.trash_dir / '2024/05-01/a.jpg').is_file()
    assert (client.trash_dir / '2024/05-01/b.hif').is_file()
    # Same-stem raws of both pics are trashed too.
    assert (client.trash_dir / '2024/05-01/a.arw').is_file()
    assert (client.trash_dir / '2024/05-01/b.arw').is_file()
    # Other directories stay untouched.
    assert (client.pic_dir / '2024/05-02/c.jpg').is_file()
    assert (client.raw_dir / '2024/05-02/orphan.arw').is_file()


def test_static_assets_served(client):
    for asset in ('app.js', 'app.css', 'htmx.min.js', 'tailwind.js', 'alpine.min.js'):
        assert client.get(f'/static/{asset}').status_code == 200, asset
