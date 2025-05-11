import shutil
import os
import re
from pathlib import Path
from lxml import etree as ET
import json
from pymediainfo import MediaInfo


# Usage


########################################## Change these to match your system ##########################################
library_path = Path("E:\\Anime\\One Pace Team\\One Pace")  # Where you want the video file to go
tmm_folder = Path("E:\\.One Pace Stuff\\tinyMediaManager\\tv_shows\\One Piece\\Season 35")  # Where episodes will be moved for xml generation.
tmm_cmd = "E:\\.One Pace Stuff\\tinyMediaManager\\tinyMediaManagerCMD.exe tvshow -u -mi"
#######################################################################################################################

one_pace_folder = Path(__file__).parent.parent  # One Pace repo root

# Tasks can only be disabled from the bottom-up
do_nfo_creation = True
do_rename = True
do_move = True
dry_run = False

for file in os.listdir(tmm_folder):
    if file.endswith(("mp4", "mkv")):
        print(file)

        media_info = MediaInfo.parse(tmm_folder / file)
        title = media_info.general_tracks[0].movie_name
        parsed_filename = re.sub(r"\[(.*?)]", "", file.split('.')[0]).strip().rstrip(" Extended") # This is really jank but it works for now

        release_date = input(f'Enter the release date for file "{file}" in  YYYY-MM-DD format')

        # For cases like Koby-Meppo, where an episode number isn't passed
        # Need to make sure the rest of the code can handle / isn't impacted by this scenario
        if any(char.isdigit() for char in parsed_filename[-1]):
            parsed_filename = parsed_filename.rsplit(maxsplit=1)
        else:
            parsed_filename = parsed_filename

        parsed_episode_number = parsed_filename[1].zfill(2)
        parsed_arc_name = parsed_filename[0]

        is_special = False

        with open(one_pace_folder / "dist\\seasons.json") as f:
            try:
                parsed_season_number = str(json.load(f)[parsed_arc_name]).zfill(2)
                title = title.split("-", 1)[1].strip()  # Embedded titles need the season name removed
                if "extended" in file.lower():
                    title = title + " (Extended)"

            except Exception:
                if input("Error parsing season. Is it a special? y/N").lower() == "y":
                    parsed_season_number = "00"
                    parsed_episode_number = input("Enter Episode Number (no leading zeros)").zfill(2)
                    is_special = True

                else:
                    print("Exiting")
                    exit(1)

            if do_nfo_creation:
                print("Creating the NFO file")

                xmlfilepath = (tmm_folder / file.split(".")[0]).with_suffix(".nfo")

                xmlparser = ET.XMLParser(remove_blank_text=True)
                root = ET.Element("episodedetails")

                ET.SubElement(root, 'title').text = title
                # ET.SubElement(root, 'plot').text = plot
                ET.SubElement(root, 'premiered').text = release_date
                ET.SubElement(root, 'aired').text = release_date
                ET.SubElement(root, 'dateadded').text = f"{release_date} 11:00:00"

                ET.ElementTree(root).write(Path(xmlfilepath), method="xml", pretty_print=True, xml_declaration=True, encoding="utf-8", standalone=True)

            if do_rename:
                new_episode_name = f"One Pace - S{parsed_season_number}E{parsed_episode_number} - {title}"
                renamed_video = str(tmm_folder / new_episode_name) + '.mkv'
                renamed_nfo = str(tmm_folder / new_episode_name) + '.nfo'

                os.rename((tmm_folder / file).with_suffix(".mkv"), renamed_video)
                os.rename((tmm_folder / file).with_suffix(".nfo"), renamed_nfo)

                print(new_episode_name)

                if do_move:

                    if is_special:
                        episode_path = library_path / f"Specials"
                        git_path = one_pace_folder / "One Pace" / f"Specials"

                    else:
                        episode_path = library_path / f"Season {parsed_season_number}"
                        git_path = one_pace_folder / "One Pace" / f"Season {parsed_season_number}"

                    print(f"Moving NFO to {git_path}")
                    print(f"Moving Episode to {episode_path}")

                    print(episode_path)
                    print(git_path)

                    if not dry_run:
                        shutil.copy2(renamed_nfo, episode_path)
                        shutil.move(renamed_nfo, git_path)
                        shutil.move(renamed_video, episode_path)

print("Done")
