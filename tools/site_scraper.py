import shutil
import subprocess
import os
import re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from pathlib import Path
from lxml import etree as ET
import json
import datetime


# Usage
# When a new epiosde releases, put it in the One Piece TinyMediaManager folder (tmm_folder). The season folder doesn't matter, since we parse that from the filename
# Then run `python site_scraper.py` and wait. The NFO will automatically be copied to the git repo and your One Pace folder, along with the video file.

########################################## Change these to match your system ##########################################
library_path = Path("E:\\Anime\\One Pace Team\\One Pace")  # Where you want the video file to go
tmm_folder = Path("E:\\.One Pace Stuff\\tinyMediaManager\\tv_shows\\One Piece\\Season 35")  # Where episodes will be moved for xml generation.
tmm_cmd = "E:\\.One Pace Stuff\\tinyMediaManager\\tinyMediaManagerCMD.exe tvshow -u -mi"
#######################################################################################################################


def updateTag(key, value, delete=False):
    existing_tag = tree.find(key)

    if value is not None:
        value = str(value)

    if existing_tag is not None:
        if delete:
            root.remove(existing_tag)
            return
        existing_tag.text = value

    else:
        ET.SubElement(root, key).text = value


one_pace_folder = Path(__file__).parent.parent  # One Pace repo root

# Tasks can only be disabled from the bottom-up
do_tmm = True
do_selenium = True
do_nfo_rewrite = True
do_rename = True
do_move = True


for file in os.listdir(tmm_folder):
    if file.endswith(("mp4", "mkv")):
        print(file)

        parsed_filename = re.sub(r"\[(.*?)]", "", file.split('.')[0]).strip()

        # For cases like Koby-Meppo, where an episode number isn't passed
        # Need to make sure the rest of the code can handle / isn't impacted by this scenario
        if any(char.isdigit() for char in parsed_filename[-1]):
            parsed_filename = parsed_filename.rsplit(maxsplit=1)
        else:
            parsed_filename = parsed_filename

        parsed_episode_number = parsed_filename[1].zfill(2)
        parsed_arc_name = parsed_filename[0]

        with open(one_pace_folder / "dist\\seasons.json") as f:
            parsed_season_number = str(json.load(f)[parsed_arc_name]).zfill(2)

        if do_tmm:
            if not Path(str(tmm_folder / file)).with_suffix(".nfo").exists():
                print("Generating NFO files via TinyMediaManager")
                generate_nfo = subprocess.run(tmm_cmd, capture_output=True, text=True)

            if do_selenium:
                print("Scrapping data from One Pace")

                driver = webdriver.Firefox()
                driver.implicitly_wait(10)
                driver.get("https://onepace.net/watch")

                episode_name = f"{parsed_arc_name.lower().replace(" ", "-")}-{parsed_episode_number}"

                # Open episode card
                episode_card = driver.find_element(By.XPATH, f"//img[contains(@src, '{episode_name}')]")
                driver.execute_script("arguments[0].click();", episode_card)

                # Find episode card
                episode_info = WebDriverWait(driver, 5).until(EC.presence_of_element_located((By.XPATH, "//div[contains(@class, 'Carousel_infoContainer')]")))

                # Parse the fields we want
                title = driver.find_element(By.XPATH, "//div[contains(@class, 'Carousel_infoContainer')]/h3").text
                description = driver.find_element(By.XPATH, "//div[contains(@class, 'Carousel_infoContainer')]/p[contains(@class, 'Carousel_description')]").text
                manga_chapters = driver.find_element(By.XPATH, "//div[contains(@class, 'Carousel_infoContainer')]/p[contains(text(), 'Manga Chapter')]").text
                anime_episodes = driver.find_element(By.XPATH, "//div[contains(@class, 'Carousel_infoContainer')]/p[contains(text(), 'Anime Episode')]").text
                release_date = driver.find_element(By.XPATH, "//div[contains(@class, 'Carousel_infoContainer')]/p[contains(text(), 'Released on')]").text

                release_date = release_date.split(": ")[-1]
                month, day, year = release_date.split("/")

                release_date = datetime.datetime(int(year), int(month), int(day)).strftime("%Y-%m-%d")

                # Line breaks to match the One Pace site's formatting
                plot = f"{description}\n\n{manga_chapters}\n\n{anime_episodes}"

                print(title)
                print(description)
                print(manga_chapters)
                print(anime_episodes)
                print(release_date)

                print(plot)

                driver.close()

                if do_nfo_rewrite:
                    print("Rewriting the NFO file")

                    xmlfilepath = (tmm_folder / file.split(".")[0]).with_suffix(".nfo")

                    xmlparser = ET.XMLParser(remove_blank_text=True)
                    tree = ET.parse(xmlfilepath)
                    root = tree.getroot()

                    updateTag('title', title)
                    updateTag('originaltitle', None)
                    updateTag('showtitle', 'One Pace')
                    updateTag('season', parsed_season_number)

                    for i in root.findall('uniqueid'):
                        print("Killing child (uniqueid)")
                        root.remove(i)

                    updateTag('id', None)  # Fixes formatting from child-killing loop

                    # Kill children of <ratings>
                    for i in root.findall('.//rating'):
                        print("Killing child (rating)")
                        i.getparent().remove(i)

                    updateTag('ratings', None)  # Fixes formatting from child-killing loop
                    updateTag('userrating', '0.0')
                    updateTag('plot', plot)
                    updateTag('runtime', '0')
                    updateTag('mpaa', None)
                    updateTag('premiered', release_date)
                    updateTag('aired', release_date)
                    updateTag('watched', 'false')
                    updateTag('playcount', None, True)
                    updateTag('trailer', None, True)
                    updateTag('epbookmark', None, True)
                    updateTag('code', None, True)
                    updateTag('user_note', None, True)
                    updateTag('episode_groups', '', True)

                    ET.ElementTree(root).write(Path(xmlfilepath), method="xml", pretty_print=True, xml_declaration=True, encoding="utf-8", standalone=True)

                if do_rename:
                    new_episode_name = f"One Pace - S{parsed_season_number}E{parsed_episode_number} - {title}"
                    renamed_video = str(tmm_folder / new_episode_name) + '.mkv'
                    renamed_nfo = str(tmm_folder / new_episode_name) + '.nfo'

                    os.rename((tmm_folder / file).with_suffix(".mkv"), renamed_video)
                    os.rename((tmm_folder / file).with_suffix(".nfo"), renamed_nfo)

                    print(new_episode_name)

                    if do_move:
                        git_path = one_pace_folder / "One Pace" / f"Season {parsed_season_number}"
                        episode_path = library_path / f"Season {parsed_season_number}"
                        
                        print(f"Moving NFO to {git_path}")
                        print(f"Moving Episode to {episode_path}")
                        
                        print(episode_path)
                        print(git_path)

                        shutil.copy2(renamed_nfo, episode_path)
                        shutil.move(renamed_nfo, git_path)
                        shutil.move(renamed_video, episode_path)


print("Done")
