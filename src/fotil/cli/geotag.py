"""Geotagging business logic."""

import importlib.resources as resources
import re
import shutil

from datetime import datetime as dt
from datetime import timedelta
from pathlib import Path
from typing import Annotated

import typer

from fotil.exiftool import (
    EXIF_DATE_TAGS,
    EXIF_VIDEO_ALL_DATE_TAGS,
    EXIF_VIDEO_DATE_TAGS,
    GPS_TAGS,
    Exiftool,
)

from . import cli_options


# Camera model tags mapping
EXIF_CAMERA_MODEL_TAGS = {
    'Make': None,
    'Model': None,
    'DeviceManufacturer': 'Make',
    'DeviceModelName': 'Model',
}

DEFAULT_CAMERA_MODEL = {
    'SONY': 'ICLE-7M4',
}

# File naming patterns for camera detection
_FNAME_RE_SONY_VIDEO = re.compile(r'C\d\d\d\d.*\.MP4')
_FNAME_RE_SONY_IMAGE = re.compile(r'DSC\d\d\d\d.*')

# Timezone offset tag written by Sony cameras, e.g. "+09:00"
_TZ_OFFSET_RE = re.compile(r'([+-])(\d{2})')

# Local timezone offset in hours
_local_tz_offset = dt.now().astimezone().utcoffset()
LOCAL_TZ_SHIFT_HOUR = (
    int(_local_tz_offset.total_seconds() / 3600) if _local_tz_offset else 0
)


def guess_camera_maker(fname: Path) -> str | None:
    """Guess camera manufacturer from file name or EXIF data.

    Args:
        fname: Path to the file.

    Returns:
        Camera manufacturer name or None.
    """
    if _FNAME_RE_SONY_IMAGE.match(fname.name) or _FNAME_RE_SONY_VIDEO.match(fname.name):
        print('guessed SONY camera file')
        return 'SONY'

    if fname.name.startswith('DSCF'):
        print('guessed Fujifilm camera file')
        return 'Fujifilm'

    exif = Exiftool()
    tags = exif.read([fname], tags=['Make'])
    if tags and 'Make' in tags[0]:
        return tags[0]['Make']

    return None


def _canonic_camera_model_tag(fname: Path, tag_values: dict[str, str]) -> None:
    """Convert camera model tags to canonical form.

    Args:
        fname: Path to the file.
        tag_values: Dictionary of tag values to update.
    """
    for tag, canonic_tag in EXIF_CAMERA_MODEL_TAGS.items():
        if canonic_tag is None or tag not in tag_values:
            continue

        tag_values[canonic_tag] = tag_values[tag]
        del tag_values[tag]

    if 'Make' not in tag_values:
        maker = guess_camera_maker(fname)
        if maker:
            tag_values['Make'] = maker

    if 'Model' not in tag_values:
        maker = tag_values.get('Make')
        model = DEFAULT_CAMERA_MODEL.get(maker) if maker else None
        if model:
            tag_values['Model'] = model


def _guess_video_file_time_zone(fname: Path) -> int:
    """Guess video file timezone based on camera.

    Args:
        fname: Path to the video file.

    Returns:
        Timezone offset in hours.
    """
    maker = guess_camera_maker(fname)
    if maker in ('Fujifilm',):
        return LOCAL_TZ_SHIFT_HOUR
    return 0


def _shift_to_utc_timezone(timezone: int) -> int:
    """Convert timezone offset to UTC offset.

    Args:
        timezone: Timezone offset in hours.

    Returns:
        UTC offset in hours.
    """
    return -timezone


def _shift_to_local_timezone(timezone: int) -> int:
    """Convert timezone offset to local timezone offset.

    Args:
        timezone: Timezone offset in hours.

    Returns:
        Local timezone offset in hours.
    """
    utcshift = _shift_to_utc_timezone(timezone)
    return utcshift + LOCAL_TZ_SHIFT_HOUR


def _format_tz_offset(offset_hour: int) -> str:
    """Format timezone offset in hours as an EXIF offset suffix, e.g. "+09:00"."""
    return f'{offset_hour:+03d}:00'


def _parse_tz_offset_hours(value: str) -> int | None:
    """Parse a timezone offset string like "+09:00" into signed hours."""
    m = _TZ_OFFSET_RE.match(value.strip())
    if not m:
        return None
    offset = int(m.group(2))
    return -offset if m.group(1) == '-' else offset


def _shooting_tz_offset(fpath: Path, camera_tz: int) -> int:
    """Timezone offset in hours of the shooting location for a video file.

    Sony cameras store the camera timezone in the rtmd "TimeZone" tag; use it
    when present, and otherwise assume the camera clock timezone.

    Args:
        fpath: Path to the video file.
        camera_tz: Camera clock timezone offset in hours, as fallback.

    Returns:
        Timezone offset in hours.
    """
    tags = Exiftool().read([fpath], tags=['TimeZone'])
    if tags:
        offset = _parse_tz_offset_hours(tags[0].get('TimeZone', ''))
        if offset is not None:
            return offset
    return camera_tz


def _write_video_creation_date(exif: Exiftool, fpath: Path, tz_hour: int) -> None:
    """Write Keys:CreationDate with local time + tz, like iPhone videos.

    macOS Photos and QuickTime Player prefer this vendor tag over the naive
    QuickTime times, which the geotag video flow leaves in UTC. Skipped when
    the video already carries one, e.g. from an iPhone.

    Args:
        exif: Exiftool instance.
        fpath: Path to the video file.
        tz_hour: Shooting location timezone offset in hours.
    """
    existing = exif.read([fpath], tags=['CreationDate'])
    if existing and 'CreationDate' in existing[0]:
        if cli_options.verbose:
            print(f'{fpath} already has CreationDate, keep it')
        return

    tags = exif.read([fpath], tags=['CreateDate'])
    if not tags or 'CreateDate' not in tags[0]:
        return

    try:
        utc_time = Exiftool.parse_date(tags[0]['CreateDate'])
    except ValueError:
        print(f'ignore parse date error for {fpath} CreateDate {tags[0]["CreateDate"]}')
        return

    local_time = utc_time + timedelta(hours=tz_hour)
    value = f'{local_time:%Y:%m:%d %H:%M:%S}{_format_tz_offset(tz_hour)}'
    exif.write([fpath], {'Keys:CreationDate': value})


def _filter_files_with_tags(
    fpaths: list[Path], tags: list[str], verbose: bool = False
) -> list[Path]:
    """Filter out files that already have the specified tags.

    Args:
        fpaths: List of file paths.
        tags: List of tag names to check.
        verbose: Whether to print verbose output.

    Returns:
        List of file paths that don't have the specified tags.
    """
    exif = Exiftool()
    notag_fpaths = []
    skip_files = []

    for f in fpaths:
        metadata = exif.read([f], tags=tags)
        # exiftool -json always includes a "SourceFile" key, so check the
        # requested tags instead of the dict length.
        if metadata and all(tag not in metadata[0] for tag in tags):
            notag_fpaths.append(f)
        else:
            skip_files.append(f)

    if verbose and skip_files:
        print(f'skip files: {", ".join(str(f) for f in skip_files)}')

    return notag_fpaths


def _expand_directories(fpaths: list[Path], pattern: str | None = None) -> list[Path]:
    """Expand directories to list of matching files.

    Args:
        fpaths: List of file paths or directories.
        pattern: Glob pattern to match files in directories.

    Returns:
        List of file paths.
    """
    if pattern is None:
        return [f for f in fpaths if f.is_file()]

    result = []
    for f in fpaths:
        if f.is_dir():
            matches = sorted(f.glob(pattern))
            result.extend(matches)
        else:
            result.append(f)

    return result


def is_video(fname: Path) -> bool:
    """Check if file is a video file.

    Args:
        fname: Path to the file.

    Returns:
        True if the file is a video.
    """
    return fname.suffix.lower() in ('.mov', '.mp4')


def _shift_all_time_tags(exif: Exiftool, fpaths: list[Path], shift: int) -> None:
    """Shift all supported time tags, splitting video and picture files.

    For files whose recording device time was wrong. exiftool shift moves the
    wall time only, so a value with a timezone suffix keeps its suffix -- such a
    value from a correctly-clocked device already holds the right absolute time
    and must not be shifted.

    For videos this includes Keys:CreationDate and EncodingTime, the tags macOS
    Photos reads.

    Args:
        exif: Exiftool instance.
        fpaths: List of file paths.
        shift: Time shift in hours (can be negative).
    """
    video_fpaths = [f for f in fpaths if is_video(f)]
    pic_fpaths = [f for f in fpaths if not is_video(f)]

    if video_fpaths:
        exif.shift_time(video_fpaths, shift, tags=EXIF_VIDEO_ALL_DATE_TAGS)
    if pic_fpaths:
        exif.shift_time(pic_fpaths, shift, tags=EXIF_DATE_TAGS)


def _get_tag_file() -> Path:
    """Get the path to the tag.jpg resource file.

    Returns:
        Path to tag.jpg.
    """
    with resources.as_file(resources.files('fotil.static') / 'tag.jpg') as p:
        return p


# ---- CLI commands ----

app = typer.Typer(help='Geotagging operations.')


@app.command(name='shift')
def shift_time(
    fpaths: Annotated[list[Path], typer.Argument(help='Files to shift time')],
    time_shift: Annotated[
        int,
        typer.Option(
            '--time-shift',
            '-s',
            help='Shift time tags by N hours (negative to shift back)',
        ),
    ],
) -> None:
    """Shift time in EXIF metadata.

    This is designed for files whose recording device time was wrong: a wrong
    camera clock, or a camera left in the home timezone while shooting abroad
    (e.g. recording Shanghai wall time for videos shot in Japan), so the
    recorded absolute time itself is incorrect. Do NOT use it on files from
    devices with correct time and timezone (e.g. iPhone videos): their
    timezone-suffixed values already hold the right absolute time and shifting
    would corrupt it. Fixing a timezone label on a correct time means
    rewriting the value, not shifting it.

    Most useful to convert video file time to UTC. Apple's Photos app considers
    video date time without time zone info as in UTC. This behavior is different
    from handling picture files.

    For video files all time tags are shifted, including Keys:CreationDate and
    EncodingTime which macOS Photos reads. A value with a timezone suffix keeps
    its suffix while the wall time is shifted.
    """
    exif = Exiftool(verbose=cli_options.verbose)
    _shift_all_time_tags(exif, fpaths, time_shift)


@app.command()
def copy_time(
    src: Annotated[Path, typer.Argument(help='Source file')],
    dst_paths: Annotated[list[Path], typer.Argument(help='Destination files')],
    time_shift: Annotated[
        int,
        typer.Option(
            '--time-shift',
            '-s',
            help='Shift copied time tags by N hours (e.g. 1 for videos shot in '
            'Japan with camera clock left in Shanghai time)',
        ),
    ] = 0,
) -> None:
    """Copy time tags from source to destinations.

    macOS convert video service changes video create, modify date time and drops
    some other tags. Use this to copy these tags from original video file. With
    --time-shift, also fix videos shot in another timezone while the camera
    clock stayed in the home timezone.
    """
    time_tags = [
        'TrackCreateDate',
        'TrackModifyDate',
        'MediaCreateDate',
        'MediaModifyDate',
        'ModifyDate',
        'DateTimeOriginal',
        'CreateDate',
        'CreationDate',
        'EncodingTime',
    ]

    # Tags that live in the QuickTime Keys directory. Writing them without a
    # group prefix is ambiguous in exiftool (same-named XMP tag wins), so they
    # must be written with the explicit "Keys:" prefix for video files.
    video_keys_tags = {'CreationDate'}

    exif = Exiftool(verbose=cli_options.verbose)
    tag_values = exif.read([src], tags=time_tags + list(EXIF_CAMERA_MODEL_TAGS.keys()))

    if not tag_values:
        return

    _canonic_camera_model_tag(src, tag_values[0])
    src_tags = tag_values[0]

    def _write_time(file_paths: list[Path], tag_values: dict[str, str]) -> None:
        video_files = [f for f in file_paths if is_video(f)]
        pic_files = [f for f in file_paths if not is_video(f)]

        if pic_files:
            pic_tags = {k: v for k, v in tag_values.items() if k not in video_keys_tags}
            exif.write(pic_files, pic_tags, overwrite_original=False)

        if video_files:
            video_tags: dict[str, str] = {}
            for tag, value in tag_values.items():
                if tag in video_keys_tags:
                    video_tags[f'Keys:{tag}'] = value
                else:
                    video_tags[tag] = value
            exif.write(video_files, video_tags, overwrite_original=False)

    _write_time(dst_paths, src_tags)

    if time_shift != 0:
        _shift_all_time_tags(exif, dst_paths, time_shift)


@app.command()
def copy_gps(
    src: Annotated[Path, typer.Argument(help='Source file with GPS')],
    dst_paths: Annotated[list[Path], typer.Argument(help='Destination files')],
    time_shift: Annotated[
        str,
        typer.Option(
            '--time-shift',
            '-t',
            help='Time shift in hours, or "auto" to guess from filename',
        ),
    ] = '0',
) -> None:
    """Copy GPS tags from source to destinations."""
    if time_shift == 'auto':
        time_zone = _guess_video_file_time_zone(dst_paths[0])
        time_shift = str(_shift_to_utc_timezone(time_zone))

    verbose = cli_options.verbose
    exif = Exiftool(verbose=verbose)
    tags_list = exif.read([src], tags=GPS_TAGS)

    if not tags_list:
        return

    tags = tags_list[0].copy()

    if 'GPSCoordinates' not in tags and 'GPSPosition' in tags and 'GPSAltitude' in tags:
        tags['GPSCoordinates'] = f'{tags["GPSPosition"]}, {tags["GPSAltitude"]}'
        if verbose:
            print(f'{src} has no GPSCoordinates, add it')

    if 'GPSPosition' in tags:
        del tags['GPSPosition']

    time_shift_int = int(time_shift)

    # For video files, write GPS using Keys:GPSCoordinates to create proper mdta
    # key registration (com.apple.quicktime.location.ISO6709), matching the
    # format iOS uses. Also reformat coordinates to ISO-6709 since newer exiftool
    # no longer accepts the "lat lon, alt" format correctly.
    def _write_gps(file_paths: list[Path], tag_values: dict[str, str]) -> None:
        video_files = [f for f in file_paths if is_video(f)]
        pic_files = [f for f in file_paths if not is_video(f)]

        if pic_files:
            exif.write(pic_files, tag_values, overwrite_original=False)

        if video_files:
            video_tags: dict[str, str] = {}
            if 'GPSLatitude' in tag_values and 'GPSLongitude' in tag_values:
                lat = float(tag_values['GPSLatitude'])
                lon = float(tag_values['GPSLongitude'])
                alt = (
                    float(tag_values['GPSAltitude']) if 'GPSAltitude' in tag_values else 0
                )
                video_tags['Keys:GPSCoordinates'] = f'{lat:+.4f}{lon:+.4f}{alt:+08.3f}/'
                if 'LocationAccuracyHorizontal' in tag_values:
                    video_tags['Keys:LocationAccuracyHorizontal'] = tag_values[
                        'LocationAccuracyHorizontal'
                    ]
            exif.write(video_files, video_tags, overwrite_original=False)

    if time_shift_int != 0:
        for f in dst_paths:
            _write_gps([f], tags)
            if is_video(f):
                exif.shift_time([f], time_shift_int, tags=EXIF_VIDEO_DATE_TAGS)
            else:
                exif.shift_time([f], time_shift_int, tags=EXIF_DATE_TAGS)
    else:
        _write_gps(dst_paths, tags)

    if verbose:
        dst_fname = ', '.join([str(d) for d in dst_paths])
        print(f'add GPS tag for video file {dst_fname}')


@app.command(name='image')
def image(
    fpaths: Annotated[
        list[Path],
        typer.Option('--fpath', '-f', help='Files or directories to add geotag'),
    ],
    gpslog_paths: Annotated[
        list[Path], typer.Option('--gpslog', '-g', help='GPS log files')
    ],
    pattern: Annotated[
        str,
        typer.Option('--pattern', '-p', help='Glob pattern for directories'),
    ] = '*.jpg',
    overwrite_original: Annotated[
        bool,
        typer.Option('--overwrite', '-o', help='Overwrite original files'),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            '--force', help='Update GPS tag even if files already contain GPS tags'
        ),
    ] = False,
) -> None:
    """Add geotag for image files."""
    verbose = cli_options.verbose
    fpaths = _expand_directories(fpaths, pattern)

    if not force:
        fpaths = _filter_files_with_tags(fpaths, GPS_TAGS, verbose)

    if len(fpaths) == 0:
        print('no files need to process')
        return

    exif = Exiftool(verbose=verbose)
    exif.geotag(fpaths, gpslog_paths, overwrite_original=overwrite_original)


@app.command(name='video')
def video(
    fpaths: Annotated[
        list[Path],
        typer.Option('--fpath', '-f', help='Files or directories to add geotag'),
    ],
    gpslog_paths: Annotated[
        list[Path], typer.Option('--gpslog', '-g', help='GPS log files')
    ],
    pattern: Annotated[
        str,
        typer.Option('--pattern', '-p', help='Glob pattern for directories'),
    ] = '',
    timezone: Annotated[
        str,
        typer.Option(
            '--timezone',
            '-t',
            help='Timezone for input video files (hour offset to UTC or "auto")',
        ),
    ] = 'auto',
    shooting_tz: Annotated[
        str,
        typer.Option(
            '--shooting-tz',
            help='Shooting location timezone offset in hours, stored in Keys:CreationDate '
            '("auto": Sony TimeZone tag, else the --timezone value)',
        ),
    ] = 'auto',
    force: Annotated[
        bool,
        typer.Option(
            '--force', help='Update GPS tag even if files already contain GPS tags'
        ),
    ] = False,
) -> None:
    """Add geotag for video files.

    exiftool can geotag all jpeg files under a single directory but not for
    mov (QuickTime) file. For mov files, we copy an empty jpeg file and set its
    creation time the same as the mov file. Let exiftool do geotag then copy the
    geotag to mov file.

    Also write Keys:CreationDate with local time + timezone, the vendor tag
    iPhone videos carry and macOS Photos / QuickTime Player prefer over the
    naive QuickTime times (which are left in UTC).
    """
    verbose = cli_options.verbose
    fpaths = _expand_directories(fpaths, pattern if pattern else None)

    if not force:
        fpaths = _filter_files_with_tags(fpaths, GPS_TAGS, verbose)

    if len(fpaths) == 0:
        print('no files need to process')
        return

    timezone_int: int
    if timezone == 'auto':
        timezone_int = _guess_video_file_time_zone(fpaths[0])
    else:
        timezone_int = int(timezone)

    time_shift = _shift_to_utc_timezone(timezone_int)
    tag_file_time_shift = _shift_to_local_timezone(timezone_int)

    print('====== generate geotag tmp jpg files for each video file ======')
    video2tag: dict[Path, Path] = {}
    exif = Exiftool(verbose=verbose)

    for vfile in fpaths:
        dst = vfile.with_name(f'{vfile.stem}_fuji_geotag_tmp.jpg')
        video2tag[vfile] = dst

        # exiftool can't create files, so seed the tmp jpg from the bundled
        # empty jpeg (shutil.copy overwrites any stale one).
        shutil.copy(_get_tag_file(), dst)

        tags_list = exif.read([vfile], tags=['CreateDate'])
        if tags_list and 'CreateDate' in tags_list[0]:
            create_date = tags_list[0]['CreateDate']
            date_tag_values = dict.fromkeys(EXIF_DATE_TAGS, create_date)

            exif.write([dst], date_tag_values, overwrite_original=True)

            if tag_file_time_shift != 0:
                exif.shift_time(
                    [dst],
                    tag_file_time_shift,
                    tags=EXIF_DATE_TAGS,
                    overwrite_original=True,
                )

            print(f'\t{dst} created')

    print('====== geotag for all tmp jpg files ======')
    image(
        list(video2tag.values()),
        gpslog_paths,
        overwrite_original=True,
        force=True,
    )

    print('====== copy GPS from tmp jpg to video ======')
    for vfile in fpaths:
        geotag_jpg_file = video2tag[vfile]
        copy_gps(geotag_jpg_file, [vfile], time_shift=str(time_shift))
        geotag_jpg_file.unlink()

    print('====== add Keys:CreationDate for video files ======')
    for vfile in fpaths:
        if shooting_tz == 'auto':
            tz_hour = _shooting_tz_offset(vfile, timezone_int)
        else:
            tz_hour = int(shooting_tz)
        _write_video_creation_date(exif, vfile, tz_hour)


@app.command(name='camera')
def make_model(
    fpaths: Annotated[
        list[Path], typer.Option('--fpath', '-f', help='Files or directories')
    ],
    make: Annotated[str, typer.Option('--make', '-m', help='Camera manufacturer')],
    model: Annotated[str, typer.Option('--model', '-M', help='Camera model')],
    force: Annotated[
        bool,
        typer.Option(
            '--force',
            '-F',
            help='Update make and model tags even if files already contain those tags',
        ),
    ] = False,
) -> None:
    """Set camera manufacturer and model."""
    verbose = cli_options.verbose
    if not force:
        fpaths = _filter_files_with_tags(fpaths, ['Make', 'Model'], verbose)

    if len(fpaths) == 0:
        print('no files need to process')
        return

    exif = Exiftool(verbose=verbose)
    exif.write(fpaths, {'Make': make, 'Model': model}, overwrite_original=False)
