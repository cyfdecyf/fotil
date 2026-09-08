import shutil

from datetime import datetime as dt
from datetime import timedelta
from pathlib import Path

import pytest

from fotil.cli import geotag
from fotil.exiftool import Exiftool


DATA_DIR = Path(__file__).resolve().parent / 'data'
VIDEO_FIXTURE = DATA_DIR / 'video' / 'test.mp4'
IMG_FIXTURE = DATA_DIR / 'img' / 'a.jpg'
# iPhone 16 photo with its GPS fix in the EXIF GPS IFD (no ItemList
# GPSCoordinates), the source shape that broke copy-gps to AVIF.
HEIC_GPS_FIXTURE = DATA_DIR.parents[1] / 'docs' / 'samples' / 'iPhone16-photo.heic'
HEIC_GPS = {
    'GPSLatitude': 34.429875,
    'GPSLongitude': 135.238280555556,
    'GPSAltitude': 3.910400838,
}

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


def _read_gps(fpath: Path) -> dict[str, float]:
    meta = Exiftool().read([fpath], tags=list(HEIC_GPS))[0]
    return {tag: float(meta[tag]) for tag in HEIC_GPS}


def test_write_gps_splits_picture_and_video_tags(tmp_path: Path):
    """Pictures get EXIF GPS tags only, videos a rebuilt Keys:GPSCoordinates.

    The container GPSCoordinates tag must not reach picture files: on AVIF
    exiftool resolves it to ItemList:GPSCoordinates and rejects the
    "lat lon, alt" value with "Longitude out of range".
    """
    written: dict[tuple[Path, ...], dict[str, str]] = {}

    class FakeExiftool:
        def write(self, fpaths, tags, *, overwrite_original=False):
            written[tuple(fpaths)] = tags

    pic = tmp_path / 'DSC00001.avif'
    video = tmp_path / 'C0001.MP4'
    geotag._write_gps(
        FakeExiftool(),  # type: ignore[arg-type]
        [pic, video],
        {
            'GPSCoordinates': '34.429875 135.238280555556, 3.910400838',
            'GPSLatitude': '34.429875',
            'GPSLongitude': '135.238280555556',
            'GPSAltitude': '3.910400838',
            'GPSAltitudeRef': '0',
        },
    )

    assert written[(pic,)] == {
        'GPSLatitude': '34.429875',
        'GPSLatitudeRef': 'N',
        'GPSLongitude': '135.238280555556',
        'GPSLongitudeRef': 'E',
        'GPSAltitude': '3.910400838',
        'GPSAltitudeRef': '0',
    }
    assert written[(video,)] == {'Keys:GPSCoordinates': '+34.4299+135.2383+003.910/'}


def test_copy_gps_heic_to_picture(tmp_path: Path):
    dst = tmp_path / 'dst.heic'
    shutil.copy(HEIC_GPS_FIXTURE, dst)
    Exiftool().write([dst], {'GPS:all': ''}, overwrite_original=True)
    assert 'GPSLatitude' not in Exiftool().read([dst], tags=['GPSLatitude'])[0]

    geotag.copy_gps(HEIC_GPS_FIXTURE, [dst])

    assert _read_gps(dst) == pytest.approx(HEIC_GPS)


def test_copy_gps_heic_to_video(tmp_path: Path):
    dst = tmp_path / 'dst.mp4'
    shutil.copy(VIDEO_FIXTURE, dst)

    geotag.copy_gps(HEIC_GPS_FIXTURE, [dst])

    # Keys:GPSCoordinates is written with 4 (coordinates) / 3 (altitude)
    # decimals, and exiftool derives the composite GPS tags from it.
    assert _read_gps(dst) == pytest.approx(HEIC_GPS, abs=1e-3)
