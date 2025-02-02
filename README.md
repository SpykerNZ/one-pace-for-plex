# One Pace for Plex

This guide explains how to set up One Pace for Plex or Jellyfin. It has been only tested with Jellyfin, but it should work with Plex as well.

#### Features:

- Episodes grouped by One Pace arcs
- Custom metadata files for each episode
- Custom posters for each season
- Option to keep original file names from One Pace downloads
- Option to rename One Pace episodes to standard SxxEyy format
  - Allows to include episodes not completed by the One Pace team yet

## Final Result

### Specific One Pace show available in your Plex library.

![One Pace Series View](images/series-view.png)

### Show split into the different One Pace seasons.

![One Pace Seasons View](images/seasons-view.png)

## Requirements

- Plex (w/ XBMCnfoTVImporter) or Jellyfin
- Python 3.7+

## Install Instructions

### 2. Download One Pace Episodes

Download all the One Pace episodes you wish to add and place them in their respective season folders.

- Keep the default One Pace episode naming (do not make any changes!)
- You can omit any season you don't want to include, and add them later if you wish.
- The folder names for each season can be either `Season 1`, `Season 2`, etc. or any text you prefer that includes the season name (e.g. `One Pace S01 - Romance Dawn`, `One Pace S02 - Orange Town`, etc.)

```
    └───media
        ├───anime
        │   ├───One Pace
        │   │   ├───One Pace S01 - Romance Dawn
        │   │   │   └───[One Pace][1] Romance Dawn 01 [1080p][FB72C13F].mkv
        │   │   └───Season 2
        │   │       └───[One Pace][8-11] Orange Town 01 [1080p][2388DB63].mkv
        ├───movies
        └───tvshows
```

### 3. Download Missing One Piece Episodes

One Pace does not currently cover the entire series. Thus, you will need to add missing episodes to fill out your collection.

Current missing episodes:

- Season 16: 189-195, 207
- Season 35: 991-1085

See the [One Pace Episode Spreadsheet](https://docs.google.com/spreadsheets/d/1HQRMJgu_zArp-sLnvFMDzOyjdsht87eFLECxMK858lA/) for up-to-date information on what episodes are available. Check column Q to see which original One Piece episodes need to be added to your library.

Place the missing episodes in their respective season folders.

```
    └───media
        ├───anime
        │   ├───One Pace
        │   │   └───Season 7
        │   │       ├───One Piece - 46 - Chase Straw Hat! Little Buggy's Big Adventure!.mkv
        │   │       ├───One Pace - S07E46 - Chase Straw Hat! Little Buggy's Big Adventure!.nfo
        │   │       ├───One Piece - 47 - The Wait is Over! The Return of Captain Buggy!.mkv
        │   │       └───One Pace - S07E47 - The Wait is Over! The Return of Captain Buggy!.nfo
        ├───movies
        └───tvshows
```

### 4. File Renaming (w/ Python)

This approach uses python to rename all your files, which is a bit more complex but allows for more flexibility.

- Works on Windows/Linux/Mac
- Allows dry-running to check renaming
- Can modify exceptions.json to suit your needs. [^1]

1. Clone this repo to any directory you prefer.
   a. In alternative, download this repo as a zip file and extract it to any directory you prefer.
2. Open a shell/powershell terminal.
3. Change directory to where your One Pace script folder is: e.g. `cd /home/myself/one-pace-to-jellyfin/`
4. Run the script in dry-run mode to see what change would occur (you can try with Docker or Python):
   a. If you want to rename media files to the standard SxxEyy format:

   ```shell
   # if you extracted the zip file in the same directory as your One Pace episodes
   python3 rename.py --dry-run
   # if you have your One Pace episodes in a different directory
   python3 rename.py --dry-run --directory '/media/anime/One Pace'
   ```

   b. If you want to keep the original One Pace file names:

   ```shell
   # if you extracted the zip file in the same directory as your One Pace episodes
   python3 rename.py --dry-run --keep-original
   # if you have your One Pace episodes in a different directory
   python3 rename.py --dry-run --keep-original --directory '/media/anime/One Pace'
   ```

   c. If you want to use Docker, prepend the commands with:

   - `docker run --rm -v "$PWD":/data -w="/data" python:3` if the script is in the same directory as your One Pace episodes
   - `docker run --rm -v "$PWD":/data -w="/data" -v "/path/to/your/one-pace-folder":/media python:3` if the script is in a different directory

     e.g.

   ```shell
   docker run --rm -v "$PWD":/data -w="/data" python:3 python rename.py -- --dry-run
   docker run --rm -v "$PWD":/data -w="/data" -v "/path/to/One Pace":/media python:3 python rename.py -- --dry-run --keep-original --directory '/media'
   ```

5. Once you are okay with the changes you see, remove the `--dry-run` flag from the command and run it again.
   Your files will be renamed to the corresponding One Piece episode.
6. In Jellyfin, you may need to refresh the One Pace show metadata, or just wait for the next library scan.

[^1]: Inside 'exceptions.json' you can map any file name to a specific episode number. It looks in your specified season directory to see if any of the .mkv files have matching text in their filenames, then renames it as the corresponding episode number if found. If you have some strange episode naming, you may need to modify this json and add your episode filenames.

### 5. (Plex ONLY) Install XBMCnfoTVImporter

You need to install [XBMCnfoTVImporter](https://github.com/gboudreau/XBMCnfoTVImporter.bundle) for plex in order to scan in One Pace. Follow the instructions and install.

### 6. (Plex ONLY) Scan In Plex

You need to swap to the XBMCnfoTVImporter agent in Plex to scan your new One Pace folder.

1. Open Plex
2. Navigate to your anime library
3. Click 'Manage Library' -> 'Edit...'
4. Click on the 'Advanced' tab
5. Click the 'Agent' dropdown box. (and note what you have set to currently so that you can change it back)
6. Select the 'XBMCnfoTVImporter' option. (If this does not exist XBMCnfoTVImporter may not be installed correctly)
7. Click "Save Changes"
8. Click "Scan Library Files"
9. One Pace should get scanned into your library
10. Once it is complete, change your agent back to what you had originally!

Notes:

- This method will scan in One Pace without interfering with your existing shows.
- Don't press "Refresh all metadata" in plex as this may mess up your other shows.

## Acknowledgements

- Thanks to [@tomatoshadow](https://github.com/Tomatoshadow) for creating all the nfo files and original instructions for this plex setup
- Inspired by this alternative plex setup [one-pace-to-plex](https://github.com/Matroxt/one-pace-to-plex) by [@Matroxt](https://github.com/Matroxt)
- Cheers to [/u/piratezekk](https://www.reddit.com/user/piratezekk) for the awesome posters!
- Shoutout to the [One Pace Team](https://onepace.net) - thanks for putting together this amazing project!
- Thanks to [@SpykerNZ](https:://github.com/SpykerNZ) for the base of this repo
