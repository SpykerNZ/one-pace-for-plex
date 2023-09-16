# One Pace To Plex

This guide explains how to setup One Pace for Plex

#### Features:
- Episodes grouped by One Pace arcs
- Custom metadata files for each episode
- Automatic renaming of One Pace episodes to correct format required for this project
- Can include episodes not completed by the One Pace team yet
- Currently supports up to Drum Island Arc (Feel free to contribute to help adding more!)

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
        └───tvshowsW
```

### 2. Download One Pace Episodes

Download all the one pace episodes you wish to add and place them in their respective season folders.

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


### 3. File Renaming

1. Copy the rename.py, seasons.json and exceptions.json file to your One Pace directory

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

### 4. Install XBMCnfoTVImporter

You need to install [XBMCnfoTVImporter](https://github.com/gboudreau/XBMCnfoTVImporter.bundle) for plex in order to scan in One Pace. Follow the instructions and install.

### 5. Scan In Plex

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

- Thanks to [@tomatoshadow](https://github.com/Tomatoshadow) for creating the original nfos and instructions for this plex setup
- Inspired by this alternative plex setup [one-pace-to-plex](https://github.com/Matroxt/one-pace-to-plex) by [@Matroxt](https://github.com/Matroxt)
- Cheers to [/u/piratezekk](https://www.reddit.com/user/piratezekk) for the awesome posters! 
- Shoutout to the [One Pace Team](https://onepace.net) - thanks for putting together this amazing project!
