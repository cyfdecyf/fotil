from collections.abc import Callable
from pathlib import Path


def iter_directory_files(
    directory: Path,
    filter_file: Callable[[Path], bool] | None = None,
    _root_dir: Path | None = None,
):
    """
    Recursively depth first iterates files ordered under the given directory.

    Args:
        directory (Path): The directory to start iterating from.
        filter_file (callable, optional): A callable function used to filter files.
            Only files for which the function returns True will be yielded.
            Defaults to None.

    Yields:
        Path: The relative path to directory of each file that matches the
            `filter_file` criteria.
    """
    if filter_file is not None and not callable(filter_file):
        msg = 'filter_file must be callable.'
        raise ValueError(msg)

    if _root_dir is None:
        _root_dir = directory

    has_file = False
    for f in sorted(directory.iterdir()):
        if f.is_dir() and not f.name.startswith('.'):
            # Recursive call.
            yield from iter_directory_files(f, filter_file, _root_dir=_root_dir)
        elif not has_file and f.is_file():
            has_file = True

    if not has_file:
        return

    # To save memory, do not cache listed files in the first iteration.
    for f in sorted(directory.iterdir()):
        if f.is_file() and ((filter_file is None) or filter_file(f)):
            yield f.relative_to(_root_dir)
