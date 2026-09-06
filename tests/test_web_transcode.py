"""Tests for the JPEG preview transcode backends."""

import io
import shutil

from pathlib import Path

import pillow_heif
import pytest

from PIL import Image

from fotil.web import service, transcode


SIPS_AVAILABLE = shutil.which('sips') is not None


def write_hif(path: Path, size: tuple[int, int] = (8, 6)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    bio = io.BytesIO()
    pillow_heif.from_pillow(Image.new('RGB', size, 'blue')).save(bio, quality=60)
    path.write_bytes(bio.getvalue())


@pytest.fixture
def pillow_backend(monkeypatch):
    monkeypatch.setenv('FOTIL_TRANSCODER', 'pillow')


@pytest.fixture
def sips_backend(monkeypatch):
    monkeypatch.setenv('FOTIL_TRANSCODER', 'sips')


@pytest.fixture
def out(tmp_path):
    return tmp_path / 'out.jpg'


def test_use_sips_honors_env_override(monkeypatch):
    monkeypatch.setenv('FOTIL_TRANSCODER', 'sips')
    assert transcode._use_sips() is True
    monkeypatch.setenv('FOTIL_TRANSCODER', 'pillow')
    assert transcode._use_sips() is False
    monkeypatch.setenv('FOTIL_TRANSCODER', 'auto')
    assert transcode._use_sips() is SIPS_AVAILABLE
    monkeypatch.delenv('FOTIL_TRANSCODER')
    assert transcode._use_sips() is SIPS_AVAILABLE


def test_pillow_backend_transcodes_hif(pillow_backend, tmp_path, out):
    src = tmp_path / 'a.hif'
    write_hif(src)
    transcode.transcode(src, out, (2560, 2560), 85)
    assert out.read_bytes()[:2] == b'\xff\xd8'
    with Image.open(out) as im:
        assert im.size == (8, 6)


def test_pillow_backend_shrinks_to_max_size(pillow_backend, tmp_path, out):
    src = tmp_path / 'big.hif'
    write_hif(src, (3000, 2000))
    transcode.transcode(src, out, (2560, 2560), 85)
    with Image.open(out) as im:
        assert max(im.size) <= 2560


def test_pillow_backend_bad_file_raises(pillow_backend, tmp_path, out):
    src = tmp_path / 'bad.hif'
    src.write_bytes(b'not-an-image')
    with pytest.raises(transcode.TranscodeError):
        transcode.transcode(src, out, (2560, 2560), 85)
    assert not out.exists()


@pytest.mark.skipif(not SIPS_AVAILABLE, reason='sips not available')
def test_sips_backend_transcodes_hif(tmp_path, out):
    src = tmp_path / 'a.hif'
    write_hif(src)
    transcode._transcode_sips(src, out, (2560, 2560), 85, size_check=True)
    assert out.read_bytes()[:2] == b'\xff\xd8'


@pytest.mark.skipif(not SIPS_AVAILABLE, reason='sips not available')
def test_sips_backend_size_check_does_not_upscale(tmp_path, out):
    """With size checking, images within the cap keep their size."""
    src = tmp_path / 'a.hif'
    write_hif(src)
    transcode._transcode_sips(src, out, (2560, 2560), 85, size_check=True)
    with Image.open(out) as im:
        assert im.size == (8, 6)


@pytest.mark.skipif(not SIPS_AVAILABLE, reason='sips not available')
def test_sips_backend_default_upscales(tmp_path, out):
    """Default is no size check: -Z always applies, so -Z upscales small
    images. Documented behavior of sips_size_check = false."""
    src = tmp_path / 'a.hif'
    write_hif(src)
    transcode._transcode_sips(src, out, (2560, 2560), 85, size_check=False)
    with Image.open(out) as im:
        assert im.size == (2560, 1920)


@pytest.mark.skipif(not SIPS_AVAILABLE, reason='sips not available')
def test_sips_backend_shrinks_to_max_size(tmp_path, out):
    src = tmp_path / 'big.hif'
    write_hif(src, (3000, 2000))
    transcode._transcode_sips(src, out, (2560, 2560), 85, size_check=True)
    with Image.open(out) as im:
        assert max(im.size) <= 2560


@pytest.mark.skipif(not SIPS_AVAILABLE, reason='sips not available')
def test_sips_backend_bad_file_raises(tmp_path, out):
    src = tmp_path / 'bad.hif'
    src.write_bytes(b'not-an-image')
    with pytest.raises(transcode.TranscodeError):
        transcode._transcode_sips(src, out, (2560, 2560), 85, size_check=True)


BOOM_MSG = 'boom'


def _boom(src, dst, max_size, quality, size_check):
    raise transcode.TranscodeError(BOOM_MSG)


def test_sips_failure_falls_back_to_pillow(sips_backend, monkeypatch, tmp_path, out):
    monkeypatch.setattr(transcode, '_transcode_sips', _boom)
    src = tmp_path / 'a.hif'
    write_hif(src)
    transcode.transcode(src, out, (2560, 2560), 85)
    assert out.read_bytes()[:2] == b'\xff\xd8'


def test_all_backends_failing_raises(sips_backend, monkeypatch, tmp_path, out):
    monkeypatch.setattr(transcode, '_transcode_sips', _boom)
    src = tmp_path / 'bad.hif'
    src.write_bytes(b'not-an-image')
    with pytest.raises(transcode.TranscodeError):
        transcode.transcode(src, out, (2560, 2560), 85)


def test_service_reexports_transcode_error():
    assert service.TranscodeError is transcode.TranscodeError
