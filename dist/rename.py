#!/usr/bin/env python3

import argparse
import dataclasses
import re
import json
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional
import filecmp

args: Optional[dict] = None
SCRIPT_DIR = Path(__file__).parent
SEASONS_JSON = "seasons.json"
EXCEPTIONS_JSON = "exceptions.json"
SHOW_NAME = "One Pace"
MKV_EXT = ".mkv"
MP4_EXT = ".mp4"
NFO_EXT = ".nfo"


@dataclasses.dataclass
class Episode:
    show: str
    season: int
    number: int
    extended: bool = False
    title: Optional[str] = None
    filepath: Optional[Path] = None

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


def get_episode_from_nfo(filepath: Path) -> Optional[Episode]:
    nfo_pattern = r"^(.*?) - S(\d+)E(\d+) - (.*?)(?:\s\((\w[\w\s\(\)-]+)\))?\.nfo$"
    match = re.search(nfo_pattern, filepath.name)
    if match:
        return Episode(
            show=match.group(1),
            season=int(match.group(2)),
            number=int(match.group(3)),
            title=match.group(4),
            extended=match.group(5) or False,
            filepath=filepath,
        )


def get_episode_from_media(
    filepath: Path, seasons: dict[str, int]
) -> Optional[Episode]:
    media_pattern = rf"\[One Pace\]\[(.*?)\]\s(.*?)\s(\d{{1,2}}(?:-\d{{1,2}})?)(?:\s(\w[\w\s\(\)-]+))?\s\[(?:.*?)\]\[(?:.*?)\]({MKV_EXT}|{MP4_EXT})"
    match = re.search(media_pattern, filepath.name)
    if match:
        season_title = match.group(2)
        episode_number = int(match.group(3))
        season_number = seasons.get(season_title)
        return Episode(
            show=SHOW_NAME,
            season=season_number,
            number=episode_number,
            extended=match.group(4) or False,
            filepath=filepath,
        )


def debugger_is_active() -> bool:
    return hasattr(sys, "gettrace") and sys.gettrace() is not None


def ensure_tag_value(root, tag, value):
    if root.find(tag) is None:
        el = ET.Element(tag)
        el.text = value
        root.append(el)
        return True
    if root.find(tag).text != value:
        root.find(tag).text = value
        return True
    return False


def clean_tree(tree):
    to_remove = []
    found = set()
    for child in tree.getroot():
        if child.tag not in [
            "title",
            "showtitle",
            "season",
            "episode",
            "plot",
            "premiered",
            "aired",
            "seasonnumber",
            "namedseason",
            "showtitle",
        ]:
            to_remove.append(child)
            continue
        if child.text is None:
            to_remove.append(child)
            continue
        if child.tag not in found:
            found.add(child.tag)
        else:
            to_remove.append(child)
    for child in to_remove:
        tree.getroot().remove(child)
    return len(to_remove) > 0


def fix_season_nfo(fpath: Path, sno: int, sname: str):
    try:
        tree = ET.parse(str(fpath.absolute()))
    except Exception as e:
        print(fpath, e)
        return
    root = tree.getroot()
    edited = clean_tree(tree)
    if root.tag == "season":
        edited = ensure_tag_value(root, "title", f"{sno}. {sname}") or edited
        edited = ensure_tag_value(root, "seasonnumber", str(sno)) or edited
    if edited:
        ET.indent(tree)
        tree.write(str(fpath.absolute()), xml_declaration=True, encoding="UTF-8")


def fix_episode_nfo(nfo_data: Episode):
    try:
        tree = ET.parse(str(nfo_data.filepath.absolute()))
    except Exception as e:
        print(nfo_data)
        return
    root = tree.getroot()
    edited = clean_tree(tree)
    if root.tag == "episodedetails":
        edited = (
            ensure_tag_value(
                root,
                "title",
                nfo_data.title + (" (" + nfo_data.extended + ")" if nfo_data.extended else ""),
            )
            or edited
        )
        edited = ensure_tag_value(root, "season", str(nfo_data.season)) or edited
        edited = ensure_tag_value(root, "episode", str(nfo_data.number)) or edited
    if edited:
        ET.indent(tree)
        tree.write(
            str(nfo_data.filepath.absolute()), xml_declaration=True, encoding="UTF-8"
        )


def main():
    global args
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
        "--keep-original",
        action="store_true",
        help="If this flag is passed, the renaming will happen to the .nfo files",
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

    with open(SCRIPT_DIR / SEASONS_JSON, "r") as json_file:
        seasons: dict[str, int] = json.load(json_file)

    with open(SCRIPT_DIR / EXCEPTIONS_JSON, "r") as json_file:
        exceptions: dict[str, dict[str, int]] = json.load(json_file)

    # create a lookup table of nfo data
    nfo_data_lookup: dict[tuple(int, int, bool), Episode] = {}
    nfo_files = (SCRIPT_DIR.parent / SHOW_NAME).rglob(f"*{NFO_EXT}")
    for filepath in nfo_files:
        nfo_data = get_episode_from_nfo(filepath)
        if nfo_data is not None:
            nfo_data_lookup[(nfo_data.season, nfo_data.number, nfo_data.extended)] = (
                nfo_data
            )
            fix_episode_nfo(nfo_data)
            if nfo_data.extended:
                nfo_data_lookup[(nfo_data.season, nfo_data.number, True)] = Episode(
                            show=nfo_data.show,
                            season=nfo_data.season,
                            number=nfo_data.number,
                            title=nfo_data.title + " (" + nfo_data.extended + ")",
                            extended=True,
                            filepath=filepath,
                        )

    # create a pending rename file list
    pending: list[Episode] = []
    pending_snfo: list[tuple(Path, Path)] = []

    # iterate over season folders
    for season_title, season_no in seasons.items():
        if season_no == 0:
            season_name = "Specials"
        else:
            season_name = f"Season {season_no}"
        # Get the season folder
        season_folder = list(show_dir.glob(f"*{season_title}*"))
        if season_folder:
            season_folder = season_folder[0]
        else:
            season_folder = show_dir / season_name

        pending_snfo.append(
            (
                SCRIPT_DIR.parent / SHOW_NAME / season_name / "season.nfo",
                season_folder / "season.nfo",
                season_no,
                season_title,
            )
        )

        # get all exceptions for this folder
        exception_mapping: dict[str, int] = exceptions.get(season_name)
        # get all media files
        media_files = list(season_folder.glob(f"*{MKV_EXT}")) + list(
            season_folder.glob(f"*{MP4_EXT}")
        )
        # iterate over media files
        for filepath in media_files:
            episode = get_episode_from_media(filepath, seasons)
            if episode is not None and season_no != 0:
                # add episode if it exists
                pending.append(episode)
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
                        Episode(SHOW_NAME, season_no, episode_no, False, None, filepath)
                    )

    # rename all files
    copy_if_different(
        SCRIPT_DIR.parent / SHOW_NAME / "tvshow.nfo", show_dir / "tvshow.nfo", dry_run
    )
    for src, dst, sno, sname in pending_snfo:
        fix_season_nfo(src, sno, sname)
        copy_if_different(src, dst, dry_run)

    for poster in (SCRIPT_DIR.parent / SHOW_NAME).glob("*.png"):
        copy_if_different(poster, show_dir / poster.name, dry_run)

    for episode in pending:
        nfo_data = nfo_data_lookup.get(
            (episode.season, episode.number, episode.extended)
        )
        if nfo_data is None:
            nfo_data = nfo_data_lookup.get(
                (episode.season, episode.number, True)
            )
        if nfo_data is None:
            print(
                f"Warning! Episode {episode.number} in season {episode.season} found, but metadata is missing"
            )
            continue

        if args.get("keep_original"):
            rename_nfo(episode, nfo_data, dry_run)
            continue
        else:
            rename_media(episode, nfo_data, dry_run)
            continue


def copy_if_different(src, dst, dry_run):
    if dst.is_file():
        try:
            if filecmp.cmp(src, dst):
                return
        except Exception as e:
            print(f'Issues comparing {src} with {dst}: {e}')
    if dry_run:
        print(f'DRYRUN: copy "{src}" -> "{dst}"')
        return
    print(f'COPYING: "{src}" -> "{dst}"')
    shutil.copy(src, dst)


def rename_nfo(episode, nfo_data, dry_run):
    media = episode.filepath.absolute()
    nfo_fname = media.with_suffix(".nfo")
    copy_if_different(nfo_data.filepath, nfo_fname, dry_run)


def rename_media(episode, nfo_data, dry_run):
    episode.title = nfo_data.title
    new_episode_name = episode.get_file_name(extension=episode.filepath.suffix)
    if episode.filepath.name == new_episode_name:
        return

    if dry_run:
        print(f'DRYRUN: "{episode.filepath.name}" -> "{new_episode_name}"')
        return

    print(f'RENAMING: "{episode.filepath.name}" -> "{new_episode_name}"')
    episode.filepath.rename(episode.filepath.parent.absolute() / new_episode_name)


if __name__ == "__main__":
    main()
