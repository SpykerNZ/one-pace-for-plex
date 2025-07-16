import shutil
import os
import re
import requests
import csv
from pathlib import Path
from lxml import etree as ET
import json
import datetime
from pymediainfo import MediaInfo
import zipfile
import tempfile
from bs4 import BeautifulSoup


# Usage
# This script handles both original One Pace files and already-renamed Plex format files.
#
# For new episodes: Put video files in new_ep_location folder and run `python site_scraper.py`
# For already renamed files: The script will detect Plex format and generate NFO files without renaming

########################################## Change these to match your system ##########################################
library_path = Path("E:\\Anime\\One Pace Team\\One Pace")  # Where you want the video file to go
new_ep_location = Path("H:\\DevFolder\\one-pace-for-plex-my-fork\\tools")  # Where episodes will be moved for xml generation
#######################################################################################################################

GOOGLE_SHEETS_URL = "https://docs.google.com/spreadsheets/d/1M0Aa2p5x7NioaH9-u8FyHq6rH3t5s6Sccs8GoC6pHAM/export?format=csv"
EPISODE_GUIDE_URL = "https://docs.google.com/spreadsheets/d/1HQRMJgu_zArp-sLnvFMDzOyjdsht87eFLECxMK858lA/export?format=zip"


one_pace_folder = Path(__file__).parent.parent  # One Pace repo root

def download_episode_guide():
    """Download and extract the HTML episode guide from Google Sheets"""
    print("Downloading latest episode guide...")
    try:
        response = requests.get(EPISODE_GUIDE_URL)
        response.raise_for_status()
        
        # Create temporary directory
        temp_dir = tempfile.mkdtemp()
        zip_path = Path(temp_dir) / "episode_guide.zip"
        
        # Save zip file
        with open(zip_path, 'wb') as f:
            f.write(response.content)
        
        # Extract zip
        extract_dir = Path(temp_dir) / "episode_guide"
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
        
        print(f"Episode guide extracted to: {extract_dir}")
        return extract_dir
        
    except Exception as e:
        print(f"Error downloading episode guide: {e}")
        return None

def parse_episode_html(html_dir, arc_name, episode_number):
    """Parse HTML file to extract episode data"""
    try:
        html_file = Path(html_dir) / f"{arc_name}.html"
        if not html_file.exists():
            print(f"Warning: {html_file} not found")
            return None
            
        with open(html_file, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f.read(), 'html.parser')
        
        # Find the table
        table = soup.find('table', class_='waffle')
        if not table:
            print(f"Warning: No table found in {html_file}")
            return None
        
        # Find rows (skip header row)
        rows = table.find('tbody').find_all('tr')[1:]  # Skip header row
        
        for row in rows:
            cells = row.find_all('td')
            if len(cells) >= 5:
                episode_name = cells[1].get_text(strip=True)
                
                # Check if this is the episode we're looking for
                if episode_name and episode_number in episode_name:
                    chapters = normalize_text(cells[2].get_text(strip=True))
                    episodes = normalize_text(cells[3].get_text(strip=True))
                    release_date = normalize_text(cells[4].get_text(strip=True))
                    
                    # Convert date format from YYYY.MM.DD to YYYY-MM-DD
                    if release_date and '.' in release_date:
                        release_date = release_date.replace('.', '-')
                    
                    return {
                        'chapters': chapters,
                        'episodes': episodes,
                        'release_date': release_date
                    }
        
        print(f"Warning: Episode {episode_number} not found in {arc_name}")
        return None
        
    except Exception as e:
        print(f"Error parsing {arc_name}.html: {e}")
        return None

def normalize_text(text):
    """Normalize special characters in text"""
    if not text:
        return text
    
    # Remove "Ep." and "Ch." prefixes
    text = re.sub(r'\b(Ep|Ch)\.\s*', '', text)
    
    # Find and fix number ranges with various dash characters
    def fix_ranges(match):
        full_match = match.group(0)
        # Extract all numbers from this segment
        numbers = re.findall(r'\d+', full_match)
        if len(numbers) == 2:
            # It's a range
            return f"{numbers[0]}-{numbers[1]}"
        else:
            # Single number, return as-is
            return numbers[0] if numbers else full_match
    
    # Replace number ranges with proper formatting
    text = re.sub(r'\d+\s*[—–−]\s*\d+', fix_ranges, text)
    
    # Ensure proper spacing after commas
    text = re.sub(r',\s*', ', ', text)
    
    return text.strip()

def sanitize_filename(filename):
    """Sanitize filename to remove invalid characters for Windows/cross-platform compatibility"""
    if not filename:
        return filename

    # Replace specific characters with better alternatives
    sanitized = filename.replace('"', "'")  # Replace double quotes with single quotes
    sanitized = sanitized.replace(':', ' -')  # Replace colons with " - "

    # Remove other invalid Windows characters
    for char in '<>/\\|?*':
        sanitized = sanitized.replace(char, '')

    return sanitized

# Tasks can only be disabled from the bottom-up
generate_nfo = True
do_sheets_fetch = True
do_nfo_rewrite = True
do_rename = True
do_move = True

dry_run = False  # Preview operations without execution

# Download episode guide
html_dir = download_episode_guide()

# Fetch episode data from Google Sheets once before processing files
episode_data = {}
if do_sheets_fetch:
    print("Fetching episode data from Google Sheets")
    try:
        response = requests.get(GOOGLE_SHEETS_URL)
        response.raise_for_status()
        
        # Parse CSV data
        csv_data = csv.reader(response.text.splitlines())
        episode_data = {}
        
        # Skip header row if present
        header = next(csv_data, None)
        
        for row in csv_data:
            if len(row) >= 4:  # Ensure we have all required columns
                arc_title = row[0].strip()
                arc_part = row[1].strip()
                title_en = row[2].strip()
                description_en = row[3].strip()
                
                # Create episode key for lookup
                if arc_title and arc_part:
                    episode_key = f"{arc_title}_{arc_part.zfill(2)}"
                    episode_data[episode_key] = {
                        'title': title_en,
                        'description': description_en,
                        'arc_title': arc_title,
                        'arc_part': arc_part
                    }
    except Exception as e:
        print(f"Error fetching episode data: {e}")
        episode_data = {}

def reverse_lookup_arc(season_number):
    """Reverse lookup arc name from season number"""
    with open(one_pace_folder / "dist/seasons.json") as f:
        seasons = json.load(f)
        for arc_name, season_num in seasons.items():
            if str(season_num).zfill(2) == str(season_number).zfill(2):
                return arc_name
    return None

for file in os.listdir(new_ep_location):
    if file.endswith(("mp4", "mkv")):
        print(file)

        # Detect if file is already renamed to Plex format
        plex_format_match = re.match(r"One Pace - S(\d+)E(\d+) - (.+)", file.split('.')[0])
        
        if plex_format_match:
            # Already renamed file - extract info from Plex format
            season_num = plex_format_match.group(1).zfill(2)
            episode_num = plex_format_match.group(2).zfill(2)
            existing_title = plex_format_match.group(3)
            
            # Reverse lookup arc name
            arc_name = reverse_lookup_arc(int(season_num))
            if not arc_name:
                print(f"Error: Could not find arc name for season {season_num}")
                continue
                
            parsed_season_number = season_num
            parsed_episode_number = episode_num
            parsed_arc_name = arc_name
            already_renamed = True
        else:
            # Original format - use existing parsing logic
            parsed_filename = re.sub(r"\[(.*?)]", "", file.split('.')[0]).strip().rstrip(" Extended")

            # For cases like Koby-Meppo, where an episode number isn't passed
            if any(char.isdigit() for char in parsed_filename[-1]):
                parsed_filename = parsed_filename.rsplit(maxsplit=1)
            else:
                parsed_filename = [parsed_filename, "01"]  # Default episode number

            parsed_episode_number = parsed_filename[1].zfill(2)
            parsed_arc_name = parsed_filename[0]
            already_renamed = False

        is_special = False
        
        with open(one_pace_folder / "dist/seasons.json") as f:
            try:
                parsed_season_number = str(json.load(f)[parsed_arc_name]).zfill(2)
            except KeyError:
                if input(f"Error parsing season for '{parsed_arc_name}'. Is it a special? y/N: ").lower() == "y":
                    parsed_season_number = "00"
                    parsed_episode_number = input("Enter Episode Number (no leading zeros): ").zfill(2)
                    is_special = True
                else:
                    print("Exiting")
                    continue

        # Extract title from media info if available
        media_title = None
        try:
            media_info = MediaInfo.parse(new_ep_location / file)
            media_title = media_info.general_tracks[0].movie_name
            if media_title:
                # Clean up title - remove season name and handle extended
                if "-" in media_title:
                    media_title = media_title.split("-", 1)[1].strip()
                if "extended" in file.lower():
                    media_title = media_title + " (Extended)"
        except Exception as e:
            print(f"Could not extract media info: {e}")

        # Get title and description from Google Sheets if available
        sheet_title = None
        sheet_description = None
        if do_sheets_fetch:
            episode_key = f"{parsed_arc_name}_{parsed_episode_number}"
            if episode_key in episode_data:
                episode_info = episode_data[episode_key]
                sheet_title = episode_info['title']
                sheet_description = episode_info['description']

        # Get episode data from HTML guide
        html_data = None
        release_date = None
        if html_dir:
            html_data = parse_episode_html(html_dir, parsed_arc_name, parsed_episode_number)
            if html_data:
                release_date = html_data['release_date']
            else:
                print(f"Warning: Could not find episode data in HTML guide for {parsed_arc_name} {parsed_episode_number}")

        # Fallback for release date if not found in HTML or is "To Be Released"
        if not release_date or release_date == "To Be Released":
            release_date = input(f'No release date found for "{file}". Enter release date in YYYY-MM-DD format: ')

        # Resolve title conflicts
        if sheet_title and media_title and sheet_title != media_title:
            print(f"Title conflict found:")
            print(f"1. Google Sheets: {sheet_title}")
            print(f"2. Media Info: {media_title}")
            choice = input("Choose title (1 or 2): ")
            title = sheet_title if choice == "1" else media_title
        elif sheet_title:
            title = sheet_title
        elif media_title:
            title = media_title
        else:
            raise Exception(f"No title available from Google Sheets or media metadata for {file}")

        # Set description/plot with enhanced coverage info
        base_description = sheet_description if sheet_description else "Episode description not available"
        
        if html_data and html_data.get('chapters') and html_data.get('episodes'):
            plot = f"{base_description}\n\nManga Chapter(s): {html_data['chapters']}\n\nAnime Episode(s): {html_data['episodes']}"
        else:
            plot = base_description

        if generate_nfo:
            if not Path(str(new_ep_location / file)).with_suffix(".nfo").exists():
                print("Creating the NFO file")

                xmlfilepath = (new_ep_location / file.split(".")[0]).with_suffix(".nfo")

                xmlparser = ET.XMLParser(remove_blank_text=True)
                root = ET.Element("episodedetails")

                ET.SubElement(root, 'title').text = title
                ET.SubElement(root, 'showtitle').text = 'One Pace'
                ET.SubElement(root, 'season').text = str(int(parsed_season_number))
                ET.SubElement(root, 'episode').text = str(int(parsed_episode_number))
                ET.SubElement(root, 'plot').text = plot
                ET.SubElement(root, 'premiered').text = release_date
                ET.SubElement(root, 'aired').text = release_date

                ET.ElementTree(root).write(Path(xmlfilepath), method="xml", pretty_print=True, xml_declaration=True, encoding="utf-8", standalone=True)


                if do_rename and not already_renamed:
                    sanitized_title = sanitize_filename(title)
                    new_episode_name = f"One Pace - S{parsed_season_number}E{parsed_episode_number} - {sanitized_title}"
                    renamed_video = str(new_ep_location / new_episode_name) + '.mkv'
                    renamed_nfo = str(new_ep_location / new_episode_name) + '.nfo'

                    if not dry_run:
                        os.rename((new_ep_location / file).with_suffix(".mkv"), renamed_video)
                        os.rename((new_ep_location / file).with_suffix(".nfo"), renamed_nfo)
                    else:
                        print(f"[DRY RUN] Would rename {file} to {new_episode_name}.mkv")

                    print(new_episode_name)

                    if do_move:
                        if is_special:
                            git_path = one_pace_folder / "One Pace" / "Specials"
                            episode_path = library_path / "Specials"
                        else:
                            git_path = one_pace_folder / "One Pace" / f"Season {int(parsed_season_number)}"
                            episode_path = library_path / f"Season {int(parsed_season_number)}"
                        
                        print(f"Moving NFO to {git_path}")
                        print(f"Moving Episode to {episode_path}")

                        if not dry_run:
                            shutil.copy2(renamed_nfo, episode_path)
                            shutil.move(renamed_nfo, git_path)
                            shutil.move(renamed_video, episode_path)
                        else:
                            print(f"[DRY RUN] Would copy NFO to {episode_path}")
                            print(f"[DRY RUN] Would move NFO to {git_path}")
                            print(f"[DRY RUN] Would move video to {episode_path}")
                elif already_renamed:
                    # For already renamed files, handle both NFO and video
                    if do_move:
                        existing_nfo = (new_ep_location / file.split(".")[0]).with_suffix(".nfo")
                        existing_video = new_ep_location / file
                        if is_special:
                            git_path = one_pace_folder / "One Pace" / "Specials"
                            episode_path = library_path / "Specials"
                        else:
                            git_path = one_pace_folder / "One Pace" / f"Season {int(parsed_season_number)}"
                            episode_path = library_path / f"Season {int(parsed_season_number)}"
                        
                        print(f"Moving NFO to {git_path}")
                        print(f"Moving Episode to {episode_path}")
                        
                        if not dry_run:
                            shutil.copy2(existing_nfo, git_path)
                            shutil.move(existing_video, episode_path)
                        else:
                            print(f"[DRY RUN] Would copy NFO to {git_path}")
                            print(f"[DRY RUN] Would move video to {episode_path}")


print("Done")
