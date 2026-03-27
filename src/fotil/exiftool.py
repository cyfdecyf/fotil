import json
import os
import shutil
import subprocess

from datetime import datetime
from pathlib import Path

from fotil.cli import cli_options


EXIF_DATE_TAGS = ['CreateDate', 'DateTimeOriginal', 'ModifyDate', 'DateCreated']

EXIF_VIDEO_DATE_TAGS = [
    *EXIF_DATE_TAGS,
    'MediaCreateDate',
    'MediaModifyDate',
    'TrackCreateDate',
    'TrackModifyDate',
]

EXIF_CREATE_DATE_TAGS = [
    'CreateDate',
    'DateTimeOriginal',
    'DateCreated',
    'MediaCreateDate',
    'TrackCreateDate',
    # Some jpeg files saved from apps may have no above tags. Use modify date as fallback.
    'FileModifyDate',
]

GPS_TAGS = [
    'GPSCoordinates',
    'GPSAltitude',
    'GPSAltitudeRef',
    'GPSLatitude',
    'GPSLongitude',
    'GPSPosition',
    'GPSCoordinates',
]


class Exiftool:
    """
    Exiftool class to handle exiftool command line operations.
    """

    def __init__(self, exiftool_path: str | None = None, verbose: bool = False) -> None:
        exiftool_path = exiftool_path if exiftool_path else shutil.which('exiftool')
        if exiftool_path is None:
            raise FileNotFoundError(f'exiftool not found')

        self.exiftool_path: Path = Path(exiftool_path)
        self.verbose: bool = cli_options.verbose

    def read(
        self,
        fpaths: list[Path],
        tags: list[str] | None = None,
        cd_dir: Path | None = None,
    ) -> list[dict[str, str]]:
        """Read metadata from file.

        Args:
            tags: list of exif tags to read. Use `exiftool -s <img>` to see available tags.
                If None, defaults to all create date related tags.
            cd_dir: change directory to this before running exiftool command.

        Returns: list, access tag value with lst[idx][tag].
        """
        # Prefix tags with '-' to use in command.
        tags = EXIF_CREATE_DATE_TAGS if tags is None else tags
        tags = (f'-{t}' for t in tags)

        # -quite supresses summary message on stderr.
        cmd = [self.exiftool_path, '-json', '-quiet', '-n', *tags, *fpaths]

        saved_dir = None
        if cd_dir:
            saved_dir = Path.cwd()
            os.chdir(cd_dir)

        output = subprocess.check_output(cmd, text=True)

        if cd_dir:
            os.chdir(saved_dir)

        return json.loads(output)

    @staticmethod
    def parse_date(dt: str) -> datetime:
        """Parse date outpt from exiftool.

        Args:
            dt: date string from exiftool.
                Format 'YYYY:MM:DD HH:MM:SS' or with timezone suffix.
        """
        for tzstr in ('+', 'T'):
            if tzstr in dt:
                # Strip off timezone info.
                dt = dt[: dt.index(tzstr)]
                break
        return datetime.strptime(dt, '%Y:%m:%d %H:%M:%S')

    @staticmethod
    def create_date(exif: dict[str, str]) -> datetime:
        """Get create date from exif metadata.

        Args:
            exif: exif metadata.

        Returns: datetime object.
        """
        for tag in EXIF_CREATE_DATE_TAGS:
            if tag in exif:
                try:
                    return Exiftool.parse_date(exif[tag])
                except ValueError:
                    print(
                        f'ignore parse date error for {exif["SourceFile"]} {tag} {exif[tag]}'
                    )

        msg = f'no date tag found in exif metadata for {exif["SourceFile"]}'
        raise ValueError(msg)

    def write(
        self,
        fpaths: list[Path],
        tags: dict[str, str],
        overwrite_original: bool = False,
    ) -> None:
        """Write metadata to files.

        Args:
            fpaths: List of file paths to write to.
            tags: Dictionary of tag names and values to write.
            overwrite_original: If True, overwrite original files instead of creating backups.
        """
        cmd = [str(self.exiftool_path), '-api', 'largefilesupport=1', '-quiet']

        if overwrite_original:
            cmd.append('-overwrite_original')

        for tag, value in tags.items():
            if tag == 'SourceFile':
                continue
            cmd.append(f'-{tag}={value}')

        cmd.extend([str(f) for f in fpaths])

        if self.verbose:
            print(f'Running: {" ".join(cmd)}')

        subprocess.run(cmd, check=True)

    def geotag(
        self,
        fpaths: list[Path],
        gpslog: list[Path],
        overwrite_original: bool = False,
    ) -> None:
        """Add geotag to files using GPS log files.

        Args:
            fpaths: List of file paths to geotag.
            gpslog: List of GPS log file paths.
            overwrite_original: If True, overwrite original files.
        """
        cmd = [str(self.exiftool_path), '-api', 'largefilesupport=1', '-quiet']

        if overwrite_original:
            cmd.append('-overwrite_original')

        for log in gpslog:
            cmd.extend(['-geotag', str(log)])

        cmd.extend([str(f) for f in fpaths])

        if self.verbose:
            print(f'Running: {" ".join(cmd)}')

        _ = subprocess.run(cmd, check=True)

    def shift_time(
        self,
        fpaths: list[Path],
        time_shift: int,
        tags: list[str] | None = None,
        overwrite_original: bool = False,
    ) -> None:
        """Shift time in EXIF metadata.

        Args:
            fpaths: List of file paths to shift time.
            time_shift: Time shift in hours (can be negative).
            tags: List of tag names to shift. If None, defaults to all date tags.
            overwrite_original: If True, overwrite original files.
        """
        if tags is None:
            tags = EXIF_DATE_TAGS

        cmd = [str(self.exiftool_path), '-api', 'largefilesupport=1', '-quiet']

        if overwrite_original:
            cmd.append('-overwrite_original')

        sign = '-' if time_shift < 0 else '+'
        shift = abs(time_shift)

        for tag in tags:
            cmd.append(f'-{tag}{sign}={shift}')

        cmd.extend([str(f) for f in fpaths])

        if self.verbose:
            print(f'Running: {" ".join(cmd)}')

        _ = subprocess.run(cmd, check=True)
