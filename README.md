# One Pace To Plex

This guide explains how to setup One Pace for Plex

#### Features:
- Episodes grouped by One Pace arcs
- Custom metadata files for each episode
- Automatic renaming of One Pace episodes to correct format required for this project
- Allows to include episodes not completed by the One Pace team yet

## Final Result

### Specific One Pace show available in your Plex library.

![One Pace Series View](images/series-view.png)

### Show split into the different One Pace seasons. 

![One Pace Seasons View](images/seasons-view.png)

## Requirements

- Plex
- Python 3.7+
- XBMCnfoTVImporter

## Install Instructions

### 1. Copy Folder Structre

Download this repo as a zip file then copy the "One Pace" folder to your Anime or TV folder as used in Plex.

```
    └───media
        ├───anime
        │   ├───One Pace
        ├───movies
        └───tvshows
```

### 2. Download One Pace Episodes

Download all the One Pace episodes you wish to add and place them in their respective season folders.

 - Keep the default One Pace episode naming (do not make any changes!)
 - You can delete any season folders you don't want to include, and add them later if you wish.

```
    └───media
        ├───anime
        │   ├───One Pace    
        │   │   ├───Season 01
        │   │   │   ├───[One Pace][1] Romance Dawn 01 [1080p][FB72C13F].mkv     
        │   │   │   └───One Pace - S01E01 - Romance Dawn, the Dawn of an Adventure.nfo           
        │   │   └───Season 02
        │   │       ├───[One Pace][8-11] Orange Town 01 [1080p][2388DB63].mkv    
        │   │       └───One Pace - S02E01 - Enter Nami.nfo      
        ├───movies
        └───tvshows
```

### 3. Download Missing One Piece Episodes

One Pace does not currently cover the entire series. Thus you will need to add missing episodes to fill out your collection.

Current missing episodes:
- Season 7: 46,47
- Season 14: 121-130
- Season 15: 145,151,152
- Season 16: 160-195, 207
- Season 18: 250-263
- Season 24: 453-456

See the [One Pace Episode Spreadsheet](https://docs.google.com/spreadsheets/d/1HQRMJgu_zArp-sLnvFMDzOyjdsht87eFLECxMK858lA/) for a more up to date information on what episodes are avaliable. Check column P for episodes that are still to be completed.

Place the missing episodes in their respective season folders.

```
    └───media
        ├───anime
        │   ├───One Pace    
        │   │   └───Season 07
        │   │       ├───One Piece - 46 - Chase Straw Hat! Little Buggy's Big Adventure!.mkv     
        │   │       ├───One Pace - S07E46 - Chase Straw Hat! Little Buggy's Big Adventure!.nfo           
        │   │       ├───One Piece - 47 - The Wait is Over! The Return of Captain Buggy!.mkv    
        │   │       └───One Pace - S07E47 - The Wait is Over! The Return of Captain Buggy!.nfo      
        ├───movies
        └───tvshows
```

### 4. File Renaming

#### Option A - Windows Executable

1. Copy rename.exe to your One Pace directory. (from /dist/ foler)

```
    └───media
        └───anime
            └───One Pace
                ├───Season 01
                └───Season 02
                └───rename.exe
```

2.  Open executable to run.

3.  Your files will be renamed automagically!

4.  Check output to see what files were renamed.

#### Option B - Python

This approach uses python to rename all your files, which is a bit more complex but allows for more flexibility. 
- Allows dry-running to check renaming
- Can modify exceptions.json to suit your needs. [^1]

1. Copy the rename.py, seasons.json and exceptions.json file to your One Pace directory. (from /scripts/ foler)

```
    └───media
        └───anime
            └───One Pace
                ├───Season 01
                └───Season 02
                └───rename.py
                └───seasons.json
                └───exceptions.json
```

2.  Open a shell/powershell terminal.

2.  Change directory to where your One Pace script folder is: `cd /media/anime/One Pace/`

4.  Run the script in dry-run mode to see what change would occur (you can try with Docker or Python):
    a) Python: `python3 rename.py --dry-run` or `python rename.py --dry-run`
    b) Docker: `docker run --rm -v "$PWD":/data -w="/data" python:3 python rename.py --dry-run`

5.  Once you are okay with the changes you see, remove the `--dry-run` flag from the command and run it again.
    Your files will be renamed to the corresponding One Piece episode, i.e.:
    "[One Pace][1] Romance Dawn 01 [1080p][FB72C13F].mkv" -> "One Pace - S01E01 - Romance Dawn, the Dawn of an Adventure.mkv"

[^1]: Inside 'exceptions.json' each missing episode is stored. This is a simple lookup table for matching your episode filenames to the correct .nfo file. It looks in your season directory to see if any of the .mkv files include the given episode number, then adds it if a match is found. If you have some strange episode naming, you may need to modify this json and add your episode filenames.

### 5. Install XBMCnfoTVImporter

You need to install [XBMCnfoTVImporter](https://github.com/gboudreau/XBMCnfoTVImporter.bundle) for plex in order to scan in One Pace. Follow the instructions and install.

### 6. Scan In Plex

You need to swap to the XBMCnfoTVImporter agent in Plex to scan your new One Pace folder. 

1. Open Plex
2. Navigate to your anime library
3. Click 'Manage Library' -> 'Edit...'
4. Click on the 'Advanced' tab
5. Click the 'Agent' dropdown box. (and note what you have set to currently so you can change it back)
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
