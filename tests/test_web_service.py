"""Tests for the web UI filesystem service layer."""

import io

from pathlib import Path

import pillow_heif
import pytest

from PIL import Image

from fotil.config import Config, LibraryConfig
from fotil.web import service


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


def write_big_pic(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (3000, 2000), 'green').save(path)


@pytest.fixture
def lib(tmp_path, monkeypatch):
    """Library with two date dirs of pics, matching raws and one raw orphan."""
    monkeypatch.setattr(service, 'CACHE_DIR', tmp_path / 'cache')
    conf = LibraryConfig(
        pic_dir=tmp_path / 'pic', raw_dir=tmp_path / 'raw', trash_dir=tmp_path / 'trash'
    )
    write_pic(conf.pic_dir / '2024/05-01/a.jpg')
    write_hif(conf.pic_dir / '2024/05-01/b.hif')
    write_pic(conf.pic_dir / '2024/05-02/c.jpg')
    write_raw(conf.raw_dir / '2024/05-01/a.arw')
    write_raw(conf.raw_dir / '2024/05-01/b.arw')
    write_raw(conf.raw_dir / '2024/05-02/c.arw')
    write_raw(conf.raw_dir / '2024/05-02/orphan.arw')
    return conf


def test_get_library_normalizes_and_defaults(tmp_path):
    (tmp_path / 'pic').mkdir()
    conf = Config(
        default_library='main',
        library={
            'main': LibraryConfig(
                pic_dir=tmp_path / 'pic',
                raw_dir=Path('~/raw'),
                trash_dir=tmp_path / 'trash',
            )
        },
        importer={},
    )
    lib = service.get_library(conf, None)
    assert lib.pic_dir == (tmp_path / 'pic').resolve()
    assert lib.raw_dir == Path('~/raw').expanduser().resolve()
    with pytest.raises(service.UnknownLibraryError):
        service.get_library(conf, 'nope')


def test_list_subdirs(lib):
    assert service.list_subdirs(lib, '') == ['2024']
    assert service.list_subdirs(lib, '2024') == ['05-01', '05-02']
    assert service.list_subdirs(lib, '2024/05-01') == []
    assert service.list_subdirs(lib, 'missing') == []


def test_list_subdirs_details(lib):
    assert service.list_subdirs_details(lib, '') == [
        {'name': '2024', 'has_children': True}
    ]
    nodes = service.list_subdirs_details(lib, '2024')
    assert [n['name'] for n in nodes] == ['05-01', '05-02']
    assert all(not n['has_children'] for n in nodes)
    assert service.list_subdirs_details(lib, 'missing') == []


def test_list_subdirs_skips_hidden(lib):
    (lib.pic_dir / '.hidden').mkdir()
    assert service.list_subdirs(lib, '') == ['2024']


def test_list_pics(lib):
    pics, total = service.list_pics(lib, '2024/05-01')
    assert [p.name for p in pics] == ['a.jpg', 'b.hif']
    assert [str(p) for p in pics] == ['2024/05-01/a.jpg', '2024/05-01/b.hif']
    assert total == 2

    page, _ = service.list_pics(lib, '2024/05-01', offset=1, limit=1)
    assert [p.name for p in page] == ['b.hif']

    page, total = service.list_pics(lib, '2024/05-01', offset=5)
    assert page == []
    assert total == 2


def test_list_pics_empty_dir(lib):
    pics, total = service.list_pics(lib, 'missing')
    assert pics == []
    assert total == 0


def test_contained_paths_reject_escape(lib):
    with pytest.raises(service.InvalidPathError):
        service.list_subdirs(lib, '../../etc')
    with pytest.raises(service.InvalidPathError):
        service.list_pics(lib, '/etc')
    with pytest.raises(service.InvalidPathError):
        service.image_file(lib, '../outside.jpg')


def test_image_file_serves_jpg_directly(lib):
    src, media_type = service.image_file(lib, '2024/05-01/a.jpg')
    assert src == lib.pic_dir / '2024/05-01/a.jpg'
    assert media_type == 'image/jpeg'


def test_image_file_transcodes_hif_to_cached_jpeg(lib):
    src, media_type = service.image_file(lib, '2024/05-01/b.hif')
    assert media_type == 'image/jpeg'
    assert src.read_bytes()[:2] == b'\xff\xd8'  # JPEG magic
    assert src != lib.pic_dir / '2024/05-01/b.hif'

    # Second call must hit the cache: same file, untouched mtime.
    mtime = src.stat().st_mtime_ns
    again, _ = service.image_file(lib, '2024/05-01/b.hif')
    assert again == src
    assert again.stat().st_mtime_ns == mtime


def test_image_file_transcode_error(lib):
    bad = lib.pic_dir / '2024/05-02/bad.hif'
    bad.write_bytes(b'not-an-image')
    with pytest.raises(service.TranscodeError):
        service.image_file(lib, '2024/05-02/bad.hif')


def test_image_file_missing(lib):
    with pytest.raises(FileNotFoundError):
        service.image_file(lib, '2024/05-01/gone.jpg')


def test_image_file_unknown_suffix_served_as_blob(lib):
    jxl = lib.pic_dir / '2024/05-01/d.jxl'
    jxl.write_bytes(b'jxl-data')
    src, media_type = service.image_file(lib, '2024/05-01/d.jxl')
    assert src == jxl
    assert media_type == 'application/octet-stream'


def test_image_file_thumb_transcodes_jpg(lib, monkeypatch):
    """thumb serves a cached JPEG shrunk to the thumb cap, not the source."""
    monkeypatch.setenv('FOTIL_TRANSCODER', 'pillow')
    write_big_pic(lib.pic_dir / '2024/05-01/big.jpg')
    src, media_type = service.image_file(lib, '2024/05-01/big.jpg', size='thumb')
    assert media_type == 'image/jpeg'
    assert src != lib.pic_dir / '2024/05-01/big.jpg'
    assert src.is_relative_to(service.CACHE_DIR)
    with Image.open(src) as im:
        assert max(im.size) <= service.THUMB_MAX_SIZE[0]


def test_image_file_variants_use_distinct_cache_files(lib, monkeypatch):
    """thumb and large cache separately; no size still serves the original."""
    monkeypatch.setenv('FOTIL_TRANSCODER', 'pillow')
    write_big_pic(lib.pic_dir / '2024/05-01/big.jpg')
    thumb, _ = service.image_file(lib, '2024/05-01/big.jpg', size='thumb')
    large, _ = service.image_file(lib, '2024/05-01/big.jpg', size='large')
    assert thumb != large
    plain, _ = service.image_file(lib, '2024/05-01/big.jpg')
    assert plain == lib.pic_dir / '2024/05-01/big.jpg'
    assert len(list(service.CACHE_DIR.glob('*.jpg'))) == 2


def test_image_file_heif_default_matches_large(lib, monkeypatch):
    """Without size, HEIF serves the large variant (legacy compatibility)."""
    monkeypatch.setenv('FOTIL_TRANSCODER', 'pillow')
    default, _ = service.image_file(lib, '2024/05-01/b.hif')
    large, _ = service.image_file(lib, '2024/05-01/b.hif', size='large')
    assert default == large
    thumb, _ = service.image_file(lib, '2024/05-01/b.hif', size='thumb')
    assert thumb != default


def test_image_file_thumb_flattens_png_alpha(lib, monkeypatch):
    """RGBA PNGs transcode to an opaque JPEG instead of failing or blackening."""
    monkeypatch.setenv('FOTIL_TRANSCODER', 'pillow')
    png = lib.pic_dir / '2024/05-01/rgba.png'
    png.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGBA', (64, 48), (255, 0, 0, 128)).save(png)
    src, media_type = service.image_file(lib, '2024/05-01/rgba.png', size='thumb')
    assert media_type == 'image/jpeg'
    assert src.read_bytes()[:2] == b'\xff\xd8'
    with Image.open(src) as im:
        assert im.mode == 'RGB'


def test_image_file_unknown_suffix_ignores_size(lib):
    jxl = lib.pic_dir / '2024/05-01/d.jxl'
    jxl.write_bytes(b'jxl-data')
    src, media_type = service.image_file(lib, '2024/05-01/d.jxl', size='thumb')
    assert src == jxl
    assert media_type == 'application/octet-stream'


def test_image_file_unknown_size_raises(lib):
    with pytest.raises(ValueError):
        service.image_file(lib, '2024/05-01/a.jpg', size='bogus')


def test_cleanup_moves_selected_pic_and_matching_raw(lib):
    result = service.cleanup_pics(lib, ['2024/05-01/a.jpg'])
    assert result.trashed_pics == [Path('2024/05-01/a.jpg')]
    assert result.trashed_raws == [Path('2024/05-01/a.arw')]
    assert result.skipped == []

    assert not (lib.pic_dir / '2024/05-01/a.jpg').exists()
    assert not (lib.raw_dir / '2024/05-01/a.arw').exists()
    assert (lib.trash_dir / '2024/05-01/a.jpg').is_file()
    assert (lib.trash_dir / '2024/05-01/a.arw').is_file()

    # Files the user did not select stay untouched.
    assert (lib.pic_dir / '2024/05-02/c.jpg').is_file()
    assert (lib.raw_dir / '2024/05-02/orphan.arw').is_file()


def test_cleanup_stem_matches_raws_across_dirs(lib):
    write_raw(lib.raw_dir / '2024/05-02/b.arw')
    result = service.cleanup_pics(lib, ['2024/05-01/b.hif'])
    assert result.trashed_pics == [Path('2024/05-01/b.hif')]
    assert sorted(result.trashed_raws) == [
        Path('2024/05-01/b.arw'),
        Path('2024/05-02/b.arw'),
    ]


def test_cleanup_multiple_pics(lib):
    result = service.cleanup_pics(lib, ['2024/05-01/a.jpg', '2024/05-01/b.hif'])
    assert result.trashed_pics == [Path('2024/05-01/a.jpg'), Path('2024/05-01/b.hif')]
    assert sorted(result.trashed_raws) == [
        Path('2024/05-01/a.arw'),
        Path('2024/05-01/b.arw'),
    ]
    assert (lib.trash_dir / '2024/05-01/b.hif').is_file()


def test_cleanup_skips_invalid_and_missing(lib):
    result = service.cleanup_pics(
        lib, ['2024/05-01/gone.jpg', '../outside.jpg', '2024/05-01/a.jpg']
    )
    assert result.trashed_pics == [Path('2024/05-01/a.jpg')]
    assert len(result.skipped) == 2
    assert any('gone.jpg' in s for s in result.skipped)
    assert any('outside.jpg' in s for s in result.skipped)


def test_cleanup_keeps_old_trash_entries(lib):
    service.cleanup_pics(lib, ['2024/05-01/a.jpg'])
    write_pic(lib.pic_dir / '2024/05-01/a.jpg')
    service.cleanup_pics(lib, ['2024/05-01/a.jpg'])
    assert (lib.trash_dir / '2024/05-01/a.jpg').is_file()
    assert (lib.trash_dir / '2024/05-01/a 1.jpg').is_file()
