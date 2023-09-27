import argparse
import dataclasses
import re
import json
import os
import sys
from pathlib import Path
from typing import Optional

args = None

SEASONS_JSON = "seasons.json"
EXCEPTIONS_JSON = "exceptions.json"
SHOW_NAME = "One Pace"
MKV_EXT = ".mkv"
NFO_EXT = ".nfo"


@dataclasses.dataclass
class Episode:
    show: str
    season: int
    number: int
    title: Optional[str] = None

    @property
    def episode_id(self) -> str:
        return f"S{self.season:02d}E{self.number:02d}"

    def get_file_name(self, extension: str = MKV_EXT):
        return f"{self.show} - {self.episode_id} - {self.title}{extension}"


def get_episode_from_id(show_name: str, id: str) -> Optional[Episode]:
    id_pattern = r"S(\d+)E(\d+)"
    match = re.search(id_pattern, id)
    if match:
        return Episode(
            show=show_name, season=int(match.group(1)), number=int(match.group(2))
        )


def get_episode_from_nfo(filename: str) -> Optional[Episode]:
    nfo_pattern = r"^(.*?) - S(\d+)E(\d+) - (.*?)\.nfo$"
    match = re.search(nfo_pattern, filename)
    if match:
        return Episode(
            show=match.group(1),
            season=int(match.group(2)),
            number=int(match.group(3)),
            title=match.group(4),
        )


def get_episode_from_mkv(filename: str, seasons: dict[str, int]) -> Optional[Episode]:
    mkv_pattern = (
        r"\[One Pace\]\[(.*?)\]\s(.*?)\s(\d{1,2}(?:-\d{1,2})?)\s\[(.*?)\]\[(.*?)\]\.mkv"
    )
    match = re.search(mkv_pattern, filename)
    if match:
        season_title = match.group(2)
        episode_number = int(match.group(3))
        season_number = seasons.get(season_title)
        return Episode(
            show=SHOW_NAME,
            season=season_number,
            number=episode_number,
        )
    # Special case for koby meppo as doesn't match standard regex for one pace episodes
    if "The Trials of Koby-Meppo" in filename:
        return Episode(
            show=SHOW_NAME,
            season=11,
            number=1,
        )


def debugger_is_active() -> bool:
    return hasattr(sys, "gettrace") and sys.gettrace() is not None


def main():
    parser = argparse.ArgumentParser(
        description="Rename One Pace files to matching .nfo file format"
    )
    parser.add_argument(
        "-d",
        "--directory",
        nargs="?",
        help="Data directory (path to where the root One Pace folder is)",
        default=None,
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="If this flag is passed, the output will only show how the files would be renamed",
    )
    args = vars(parser.parse_args())

    if (arg_dir := args.get("directory")) is None:
        show_dir = Path.cwd()
    else:
        show_dir = Path(arg_dir)

    dry_run = args.get("dry_run")

    if debugger_is_active():
        dry_run = True
        show_dir = Path.cwd() / (SHOW_NAME + " - Debug")

    with open(SEASONS_JSON, "r") as json_file:
        seasons: dict[str, int] = json.load(json_file)

    with open(EXCEPTIONS_JSON, "r") as json_file:
        exceptions: dict[dict[str, int]] = json.load(json_file)

    # create a lookup table of nfo data
    nfo_data_lookup: dict[tuple(int, int), Episode] = {}
    nfo_files = show_dir.rglob(f"*{NFO_EXT}")
    for filepath in nfo_files:
        nfo_data = get_episode_from_nfo(filepath.name)
        if nfo_data is not None:
            nfo_data_lookup[(nfo_data.season, nfo_data.number)] = nfo_data

    # create a pending rename file list
    pending: list[tuple[str, Episode]] = []

    # iterate over season folders
    for season_no in seasons.values():
        season_name = f"Season {season_no}"
        # Get the season folder
        season_folder = Path(show_dir / season_name)
        # get all exceptions for this folder
        exception_mapping: dict[str, int] = exceptions.get(season_name)
        # get all mkv files
        mkv_files = season_folder.rglob(f"*{MKV_EXT}")
        # iterate over mkv files
        for filepath in mkv_files:
            episode = get_episode_from_mkv(filepath.name, seasons)
            if episode is not None:
                # add episode if it exists
                pending.append((str(filepath), episode))
            elif exception_mapping is not None:
                # otherwise check if an exception
                matches = set()
                for exception_str, exception_ep in exception_mapping.items():
                    if exception_str in filepath.name:
                        episode_no = exception_ep
                        matches.add(filepath)
                if len(matches) >= 2:
                    print("Warning! Multiple exception episodes found:")
                    for match in matches:
                        print(match)
                    continue
                elif len(matches) == 1:
                    pending.append(
                        (
                            str(filepath),
                            Episode(SHOW_NAME, season_no, episode_no),
                        )
                    )

    # rename all files
    for filepath, episode in pending:
        nfo_data = nfo_data_lookup.get((episode.season, episode.number))
        if nfo_data is None:
            continue
        episode.title = nfo_data.title
        new_episode_name = episode.get_file_name()

        if dry_run:
            print('DRYRUN: "{}" -> "{}"'.format(Path(filepath).name, new_episode_name))
            continue

        print('RENAMING: "{}" -> "{}"'.format(Path(filepath).name, new_episode_name))
        os.rename(filepath, Path(filepath).parent.absolute() / new_episode_name)


if __name__ == "__main__":
    main()
