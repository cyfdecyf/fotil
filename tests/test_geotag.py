import shutil

from datetime import datetime as dt
from datetime import timedelta
from pathlib import Path

from fotil.cli import geotag
from fotil.exiftool import Exiftool


DATA_DIR = Path(__file__).resolve().parent / 'data'
VIDEO_FIXTURE = DATA_DIR / 'video' / 'test.mp4'
IMG_FIXTURE = DATA_DIR / 'img' / 'a.jpg'

INITIAL_TIME = dt(2024, 1, 2, 9, 0, 0)
INITIAL_TIME_STR = '2024:01:02 09:00:00'

# QuickTime Keys date tags come back from exiftool with the local timezone
# appended, and their JSON key drops the "Keys:" prefix.
NAIVE_VIDEO_TAGS = ['CreateDate', 'TrackCreateDate']
SUFFIXED_VIDEO_TAGS = ['CreationDate', 'EncodingTime']


def _prepare_video(dst_dir: Path, name: str) -> Path:
    """Copy the video fixture and set a known initial time on all test tags."""
    fpath = dst_dir / name
    shutil.copy(VIDEO_FIXTURE, fpath)
    tag_values = dict.fromkeys(
        [*NAIVE_VIDEO_TAGS, 'Keys:CreationDate', 'EncodingTime'], INITIAL_TIME_STR
    )
    Exiftool().write([fpath], tag_values, overwrite_original=True)
    return fpath


def _read_video_tags(fpath: Path) -> dict[str, str]:
    return Exiftool().read([fpath], tags=[*NAIVE_VIDEO_TAGS, *SUFFIXED_VIDEO_TAGS])[0]


def test_shift_time_all_video_tags(tmp_path: Path):
    fpath = _prepare_video(tmp_path, 'video.mp4')

    geotag.shift_time([fpath], time_shift=1)

    metadata = _read_video_tags(fpath)
    expected = INITIAL_TIME + timedelta(hours=1)
    for tag in NAIVE_VIDEO_TAGS:
        assert metadata[tag] == expected.strftime('%Y:%m:%d %H:%M:%S')
    for tag in SUFFIXED_VIDEO_TAGS:
        assert Exiftool.parse_date(metadata[tag]) == expected


def test_copy_time_with_shift(tmp_path: Path):
    src = _prepare_video(tmp_path, 'src.mp4')
    dst = _prepare_video(tmp_path, 'dst.mp4')

    geotag.copy_time(src, [dst], time_shift=1)

    src_meta = _read_video_tags(src)
    dst_meta = _read_video_tags(dst)
    expected = INITIAL_TIME + timedelta(hours=1)
    for tag in NAIVE_VIDEO_TAGS:
        assert src_meta[tag] == INITIAL_TIME_STR
        assert dst_meta[tag] == expected.strftime('%Y:%m:%d %H:%M:%S')
    for tag in SUFFIXED_VIDEO_TAGS:
        assert Exiftool.parse_date(src_meta[tag]) == INITIAL_TIME
        assert Exiftool.parse_date(dst_meta[tag]) == expected


def test_shift_time_image(tmp_path: Path):
    fpath = tmp_path / 'a.jpg'
    shutil.copy(IMG_FIXTURE, fpath)

    geotag.shift_time([fpath], time_shift=1)

    metadata = Exiftool().read([fpath], tags=['DateTimeOriginal'])[0]
    assert metadata['DateTimeOriginal'] == '2024:01:02 04:04:05'
