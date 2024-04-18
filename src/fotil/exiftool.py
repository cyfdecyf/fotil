import json
import os
import shutil
import subprocess

from datetime import datetime
from pathlib import Path


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

    def __init__(self, exiftool_path: str | None = None) -> None:
        self.exiftool_path = exiftool_path if exiftool_path else shutil.which('exiftool')

        if self.exiftool_path is None:
            msg = 'exiftool not found in PATH'
            raise FileNotFoundError(msg)

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
