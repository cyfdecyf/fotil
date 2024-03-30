from pathlib import Path

from fotil.fs import iter_directory_files


def test_iter_files_empty_dir(tmp_path):
    result = list(iter_directory_files(tmp_path))
    assert len(result) == 0


def test_iter_directory_files():
    directory = Path('tests/data/fs')
    result = list(iter_directory_files(directory))
    assert len(result) == 5
    assert result == [
        Path('a/c/c.log'),
        Path('a/c/c.txt'),
        Path('a/a.txt'),
        Path('b/b.txt'),
        Path('d.txt'),
    ]


def test_iter_directory_files_with_filter():
    directory = Path('tests/data/fs')
    result = list(iter_directory_files(directory, lambda f: f.suffix == '.txt'))
    assert len(result) == 4
    assert result == [
        Path('a/c/c.txt'),
        Path('a/a.txt'),
        Path('b/b.txt'),
        Path('d.txt'),
    ]
