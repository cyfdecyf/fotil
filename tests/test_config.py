"""Tests for config file decoding."""

from fotil.config import load_config


BASE = """\
default_library = 'main'

[library.main]
pic_dir = 'p'
raw_dir = 'r'
trash_dir = 't'

[importer.main]
src_dir = 'p'
dst_dir = 'p'
keep_src_dir = false
"""


def load(toml: str, tmp_path):
    fname = tmp_path / 'fotil.toml'
    fname.write_text(toml)
    return load_config(fname)


def test_missing_web_section_gets_defaults(tmp_path):
    assert load(BASE, tmp_path).web.sips_size_check is False


def test_web_section_overrides_defaults(tmp_path):
    conf = load(BASE + '\n[web]\nsips_size_check = true\n', tmp_path)
    assert conf.web.sips_size_check is True
