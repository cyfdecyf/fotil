from collections.abc import Callable
from pathlib import Path


def iter_directory_files(
    directory: Path,
    file_filter: Callable[[Path], bool] | None = None,
    _root_dir: Path | None = None,
):
    """
    Recursively depth first iterates files ordered under the given directory.

    Args:
        directory (Path): The directory to start iterating from.
        file_filter (Callable, optional): A callable function used to filter files.
            Only files for which the function returns True will be yielded.
            Defaults to None.

    Yields:
        Path: The relative path to directory of each file that matches the
            `filter_file` criteria.
    """
    if file_filter is not None and not callable(file_filter):
        msg = 'filter_file must be callable.'
        raise ValueError(msg)

    if _root_dir is None:
        _root_dir = directory

    has_file = False
    for f in sorted(directory.iterdir()):
        if f.is_dir() and not f.name.startswith('.'):
            # Recursive call.
            yield from iter_directory_files(f, file_filter, _root_dir=_root_dir)
        elif not has_file and f.is_file():
            has_file = True

    if not has_file:
        return

    # To save memory, do not cache listed files in the first iteration.
    for f in sorted(directory.iterdir()):
        if f.is_file() and ((file_filter is None) or file_filter(f)):
            yield f.relative_to(_root_dir)
