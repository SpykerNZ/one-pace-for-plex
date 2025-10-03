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
    extended: str = ""  # Empty string for non-extended, or "Extended", "Alternate (G-8)", etc.
    title: Optional[str] = None
    filepath: Optional[Path] = None

    @property
    def episode_id(self) -> str:
        return f"S{self.season:02d}E{self.number:02d}"

    def get_file_name(self, extension: str = MKV_EXT):
        title_with_extended = self.title
        if self.extended:
            # Add the extended suffix if not already in the title
            if f"({self.extended})" not in self.title:
                title_with_extended = f"{self.title} ({self.extended})"
        return f"{self.show} - {self.episode_id} - {title_with_extended}{extension}"


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
            extended=match.group(5) or "",
            filepath=filepath,
        )


def get_episode_from_media(
    filepath: Path, seasons: dict[str, int]
) -> Optional[Episode]:
    # First try Plex format: One Pace - S##E## - Title.mkv
    plex_pattern = rf"{SHOW_NAME}\s*-\s*S(\d+)E(\d+)\s*-\s*(.*?)({MKV_EXT}|{MP4_EXT})$"
    match = re.search(plex_pattern, filepath.name, re.IGNORECASE)
    if match:
        season_number = int(match.group(1))
        episode_number = int(match.group(2))
        title = match.group(3).strip()
        # Check if it's an extended episode
        extended = ""
        # Match (Extended) or (Alternate ...) - handle nested parentheses
        # Look for the last parenthesized group that starts with Extended or Alternate
        if title.endswith(")"):
            # Find the matching opening parenthesis for the last closing one
            paren_depth = 0
            for i in range(len(title) - 1, -1, -1):
                if title[i] == ")":
                    paren_depth += 1
                elif title[i] == "(":
                    paren_depth -= 1
                    if paren_depth == 0:
                        # Found the matching opening parenthesis
                        suffix = title[i+1:-1]  # Content between parentheses
                        # Consider any parenthetical suffix as "extended" content
                        # This allows for April Fools, Extended, Alternate, or any other variant
                        extended = suffix
                        title = title[:i].strip()
                        break
        return Episode(
            show=SHOW_NAME,
            season=season_number,
            number=episode_number,
            extended=extended,
            title=title,
            filepath=filepath,
        )
    
    # Try "Paced One Piece" format: [One Pace] Paced One Piece - Arc Name Episode ## [quality][hash].mkv
    paced_pattern = rf"\[One Pace\]\s+Paced One Piece\s*-\s*(.+?)\s+Episode\s+(\d+)"
    match = re.search(paced_pattern, filepath.name, re.IGNORECASE)
    if match:
        season_title = match.group(1).strip()
        episode_number = int(match.group(2))
        # Normalize Whiskey to Whisky for season lookup
        if "Whiskey" in season_title:
            season_title = season_title.replace("Whiskey", "Whisky")
        # Normalize Arabasta to Alabasta for season lookup
        if "Arabasta" in season_title:
            season_title = season_title.replace("Arabasta", "Alabasta")
        # Case-insensitive season lookup
        season_number = None
        for key, value in seasons.items():
            if key.lower() == season_title.lower():
                season_number = value
                break
        return Episode(
            show=SHOW_NAME,
            season=season_number,
            number=episode_number,
            extended="",
            filepath=filepath,
        )
    
    # Fall back to original One Pace format
    media_pattern = rf"\[One Pace\]\[(.*?)\]\s(.*?)\s(\d{{1,2}}(?:-\d{{1,2}})?)(?:\s(\w[\w\s\(\)-]+))?\s\[(?:.*?)\]\[(?:.*?)\]({MKV_EXT}|{MP4_EXT})"
    match = re.search(media_pattern, filepath.name)
    if match:
        season_title = match.group(2)
        episode_number = int(match.group(3))
        # Normalize Whiskey to Whisky for season lookup
        if "Whiskey" in season_title:
            season_title = season_title.replace("Whiskey", "Whisky")
        # Normalize Arabasta to Alabasta for season lookup
        if "Arabasta" in season_title:
            season_title = season_title.replace("Arabasta", "Alabasta")
        # Case-insensitive season lookup
        season_number = None
        for key, value in seasons.items():
            if key.lower() == season_title.lower():
                season_number = value
                break
        return Episode(
            show=SHOW_NAME,
            season=season_number,
            number=episode_number,
            extended=match.group(4) or "",
            filepath=filepath,
        )

    # workaround for older releases
    media_pattern_misc = rf"\[One Pace\] Paced One Piece - (.*?) Episode (\d{{2}}) \[(\d+p)\]\[([A-F0-9]{{8}})\]({MKV_EXT}|{MP4_EXT})"
    match = re.search(media_pattern_misc, filepath.name)
    if match:
        season_title = match.group(1)
        episode_number = int(match.group(2))
        season_number = seasons.get(season_title)
        return Episode(
            show=SHOW_NAME,
            season_number=season_number,
            number=episode_number,
            extended=False,
            filepath=filepath,
        )


def debugger_is_active() -> bool:
    return hasattr(sys, "gettrace") and sys.gettrace() is not None


### NFO PATCH METHODS ###


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


def clean_tree(fpath: Path):
    try:
        tree = ET.parse(str(fpath.absolute()))
    except Exception as e:
        print(fpath, e)
        return
    root = tree.getroot()
    to_remove = []
    found = set()
    for child in root:
        if child.tag not in [
            "title",
            "originaltitle",
            "sorttitle",
            "showtitle",
            "season",
            "episode",
            "plot",
            "premiered",
            "aired",
            "seasonnumber",
            "namedseason",
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
        root.remove(child)
    return root, tree, len(to_remove) > 0


def save_tree(tree, edited: bool, fpath: Path):
    if edited:
        ET.indent(tree)
        tree.write(str(fpath.absolute()), xml_declaration=True, encoding="UTF-8")


def fix_season_nfo(fpath: Path, sno: int, sname: str):
    root, tree, edited = clean_tree(fpath)
    if root.tag == "season":
        edited = ensure_tag_value(root, "title", f"{sno}. {sname}") or edited
        edited = ensure_tag_value(root, "seasonnumber", str(sno)) or edited
    save_tree(tree, edited, fpath)


def fix_episode_nfo(nfo_data: Episode):
    root, tree, edited = clean_tree(nfo_data.filepath)
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
    save_tree(tree, edited, nfo_data.filepath)


### NFO PATCH METHODS /END ###


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
    parser.add_argument(
        "--patch-nfo",
        action="store_true",
        help="If this flag is passed, the source .nfo files will be patched if the information is different",
    )
    args = vars(parser.parse_args())

    if (arg_dir := args.get("directory")) is None:
        show_dir = Path.cwd()
    else:
        show_dir = Path(arg_dir)

    dry_run = args.get("dry_run")
    patch_nfo = args.get("patch_nfo")

    if debugger_is_active():
        dry_run = True
        show_dir = Path.cwd() / (SHOW_NAME + " - Debug")

    with open(SCRIPT_DIR / SEASONS_JSON, "r") as json_file:
        seasons: dict[str, int] = json.load(json_file)

    with open(SCRIPT_DIR / EXCEPTIONS_JSON, "r") as json_file:
        exceptions: dict[str, dict[str, int]] = json.load(json_file)

    # create a lookup table of nfo data
    # Key is (season, episode, is_extended) where is_extended is boolean
    nfo_data_lookup: dict[tuple(int, int, bool), Episode] = {}
    nfo_files = (SCRIPT_DIR.parent / SHOW_NAME).rglob(f"*{NFO_EXT}")
    for filepath in nfo_files:
        nfo_data = get_episode_from_nfo(filepath)
        if nfo_data is not None:
            is_extended = bool(nfo_data.extended)
            nfo_data_lookup[(nfo_data.season, nfo_data.number, is_extended)] = nfo_data
            if patch_nfo:
                fix_episode_nfo(nfo_data)

    # create a pending rename file list
    pending: list[Episode] = []
    pending_snfo: list[tuple[Path, Path]] = []

    # iterate over season folders
    for season_title, season_no in seasons.items():
        if season_no == 0:
            season_name = "Specials"
        else:
            season_name = f"Season {season_no}"
        # Get the season folder - only look for directories
        season_folders = [p for p in show_dir.glob(f"*{season_title}*") if p.is_dir()]
        if season_folders:
            season_folder = season_folders[0]
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
            if episode is not None:
                # add episode if it exists (including Specials/Season 0)
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
                        Episode(SHOW_NAME, season_no, episode_no, "", None, filepath)
                    )

    # rename all files
    copy_if_different(
        SCRIPT_DIR.parent / SHOW_NAME / "tvshow.nfo", show_dir / "tvshow.nfo", dry_run
    )
    for src, dst, sno, sname in pending_snfo:
        if patch_nfo:
            fix_season_nfo(src, sno, sname)
        copy_if_different(src, dst, dry_run)

    for poster in (SCRIPT_DIR.parent / SHOW_NAME).glob("*.png"):
        copy_if_different(poster, show_dir / poster.name, dry_run)

    # Collect warnings by type for grouped display
    warnings_by_type = {}
    episodes_without_nfo = []
    
    for episode in pending:
        # Look up NFO data based on whether episode is extended
        is_extended = bool(episode.extended)
        nfo_data = nfo_data_lookup.get(
            (episode.season, episode.number, is_extended)
        )
        
        if nfo_data is None:
            episodes_without_nfo.append(episode)
            continue

        if args.get("keep_original"):
            rename_nfo(episode, nfo_data, dry_run)
            continue
        else:
            rename_media(episode, nfo_data, dry_run)
            continue

    # Display grouped warnings
    if episodes_without_nfo:
        print("\nWarning! The following episodes exist in your library but not in the One-Pace-For-Plex NFOs. They may be obsolete One Piece episodes:")
        for episode in episodes_without_nfo:
            # Use 4 digits for episodes >= 1000, 2 digits otherwise
            ep_format = "04d" if episode.number >= 1000 else "02d"
            # Only show extended type if it's not a regular episode
            episode_type = f" ({episode.extended})" if episode.extended else ""
            print(f"  - S{episode.season:02d}E{episode.number:{ep_format}}{episode_type}")
        
        print("\nSome episodes without NFO files were found.")
        print("Run the following command for detailed library analysis:")
        # Use the same paths relative to where the user is running the command
        detect_obsolete_path = SCRIPT_DIR / "detect_obsolete.py"
        library_path = args.get("directory") or "."
        print(f'python3 {detect_obsolete_path} -d "{library_path}" --verbose')


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

    target_path = episode.filepath.parent.absolute() / new_episode_name
    
    if dry_run:
        print(f'DRYRUN: rename "{episode.filepath.name}" -> "{new_episode_name}"')
        return

    # Check if target already exists and is different from source
    if target_path.exists() and target_path != episode.filepath.absolute():
        print(f'OVERWRITING: "{episode.filepath.name}" -> "{new_episode_name}" (replacing existing file)')
        target_path.unlink()  # Delete the existing target file
    else:
        print(f'RENAMING: "{episode.filepath.name}" -> "{new_episode_name}"')
    
    episode.filepath.rename(target_path)


if __name__ == "__main__":
    main()
