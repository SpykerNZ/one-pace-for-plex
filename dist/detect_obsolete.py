#!/usr/bin/env python3
"""
Detect obsolete One Piece episodes in a One Pace library.

This script analyzes video files and their NFO metadata to identify:
- Original One Piece episodes that should be removed
- Missing NFO files that need to be added to the repository
- Valid One Pace episodes
"""

import argparse
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass, field


@dataclass
class Episode:
    """Represents an episode with its metadata."""
    season: int
    episode: int
    filepath: Path
    nfo_path: Optional[Path] = None
    is_extended: bool = False
    title: Optional[str] = None
    has_anime_episodes: bool = False  # True if NFO contains "Anime Episode(s):"


@dataclass
class ScanResults:
    """Results from scanning the library."""
    valid_one_pace: List[Episode] = field(default_factory=list)
    obsolete_original: List[Episode] = field(default_factory=list)
    missing_nfo: List[Episode] = field(default_factory=list)


class ObsoleteEpisodeDetector:
    """Detects obsolete One Piece episodes in a One Pace library."""
    
    def __init__(self, library_path: str = None, verbose: bool = False):
        """Initialize the detector with paths."""
        # Set paths
        self.library_path = Path(library_path) if library_path else Path.cwd()
        self.script_dir = Path(__file__).parent
        self.verbose = verbose
        
        # Supported extensions
        self.video_extensions = ('.mkv', '.mp4')
        
        # Load seasons mapping
        self.seasons = self._load_seasons_json()
        
        # Build covered episodes index from library NFOs
        self.covered_episodes = self._build_covered_episodes_index()
        
    def _load_seasons_json(self) -> Dict[str, int]:
        """Load the seasons.json file."""
        seasons_file = self.script_dir / "seasons.json"
        if seasons_file.exists():
            with open(seasons_file, 'r') as f:
                return json.load(f)
        return {}
    
    def _extract_anime_episodes_from_plot(self, plot_text: str) -> List[int]:
        """Extract anime episode numbers from plot text."""
        if not plot_text:
            return []
        
        episodes = []
        
        # Flexible pattern to match various formats:
        # "Episodes:", "Episode(s):", "Anime Episode(s):", "Anime Episodes:", etc.
        pattern = r'(?:Anime\s+)?Episodes?\(?s?\)?:\s*([\d\-,\s]+)'
        
        match = re.search(pattern, plot_text, re.IGNORECASE)
        if match:
            episodes_str = match.group(1)
            # Parse ranges and individual numbers
            for part in episodes_str.split(','):
                part = part.strip()
                if '-' in part:
                    # Handle range like "179-181" or "1000-1003"
                    try:
                        start, end = map(int, part.split('-'))
                        episodes.extend(range(start, end + 1))
                    except ValueError:
                        continue
                else:
                    # Handle single number
                    try:
                        episodes.append(int(part))
                    except ValueError:
                        continue
        
        return sorted(set(episodes))  # Remove duplicates and sort
    
    def _build_covered_episodes_index(self) -> set:
        """Build index of anime episodes covered by One Pace NFOs in library."""
        covered = set()
        
        # Find all NFO files in the library
        for nfo_file in self.library_path.rglob("*.nfo"):
            # Skip season.nfo and tvshow.nfo
            if nfo_file.name in ('season.nfo', 'tvshow.nfo'):
                continue
            
            # Check if this is a One Pace NFO
            if self.is_one_pace_episode(nfo_file):
                # Extract anime episodes from plot
                try:
                    tree = ET.parse(str(nfo_file))
                    root = tree.getroot()
                    plot_elem = root.find('plot')
                    if plot_elem is not None and plot_elem.text:
                        anime_episodes = self._extract_anime_episodes_from_plot(plot_elem.text)
                        covered.update(anime_episodes)
                except Exception as e:
                    if self.verbose:
                        print(f"Error parsing NFO {nfo_file}: {e}")
        
        if self.verbose:
            print(f"Found {len(covered)} anime episodes covered by One Pace")
        
        return covered
    
    def parse_episode_from_filename(self, filepath: Path) -> Optional[Episode]:
        """Parse episode information from a video filename."""
        filename = filepath.name
        
        # Try Plex format first: One Pace - S##E## - Title.mkv
        plex_pattern = r'One Pace\s*-\s*S(\d+)E(\d+)\s*-\s*(.*?)\.(?:mkv|mp4)'
        match = re.search(plex_pattern, filename, re.IGNORECASE)
        if match:
            season = int(match.group(1))
            episode = int(match.group(2))
            title = match.group(3).strip()
            is_extended = "Extended" in title or "Alternate" in title
            return Episode(
                season=season,
                episode=episode, 
                filepath=filepath,
                is_extended=is_extended,
                title=title
            )
        
        # Try original One Pace format: [One Pace][chapters] Arc Name Episode
        original_pattern = r'\[One Pace\].*?(\d+)(?:\s+Extended)?'
        match = re.search(original_pattern, filename)
        if match:
            episode_num = int(match.group(1))
            # Try to determine season from arc name in filename
            season = None
            for arc_name, season_num in self.seasons.items():
                if arc_name.lower() in filename.lower():
                    season = season_num
                    break
            
            if season:
                is_extended = "extended" in filename.lower()
                return Episode(
                    season=season,
                    episode=episode_num,
                    filepath=filepath,
                    is_extended=is_extended
                )
        
        # Try to match original One Piece episode patterns (e.g., Episode 1010)
        # These are likely obsolete episodes
        original_op_patterns = [
            r'Episode\s+(\d{4,})',  # Episode 1010
            r'One\s+Piece\s+(\d{4,})',  # One Piece 1010
            r'OP\s*(\d{4,})',  # OP1010
        ]
        
        for pattern in original_op_patterns:
            match = re.search(pattern, filename, re.IGNORECASE)
            if match:
                episode_num = int(match.group(1))
                # High episode numbers in Season 35 (Wano)
                if 1000 <= episode_num <= 1200:
                    return Episode(
                        season=35,  # Wano arc
                        episode=episode_num,
                        filepath=filepath,
                        title=filename
                    )
        
        return None
    
    def is_one_pace_episode(self, nfo_path: Path) -> bool:
        """
        Check if an NFO file represents a One Pace episode.
        One Pace episodes have episode references in their plot (Episodes:, Episode(s):, etc).
        """
        try:
            tree = ET.parse(str(nfo_path))
            root = tree.getroot()
            
            # Find the plot element
            plot_elem = root.find('plot')
            if plot_elem is not None and plot_elem.text:
                # Use flexible regex to detect One Pace marker
                # Matches: "Episodes:", "Episode(s):", "Anime Episode(s):", etc.
                pattern = r'(?:Anime\s+)?Episodes?\(?s?\)?:'
                return re.search(pattern, plot_elem.text, re.IGNORECASE) is not None
            
        except Exception as e:
            if self.verbose:
                print(f"Error parsing NFO {nfo_path}: {e}")
        
        return False
    
    def scan_library(self) -> ScanResults:
        """Scan the library for video files and categorize them."""
        results = ScanResults()
        
        print(f"Scanning library: {self.library_path}")
        
        # Find all video files
        video_files = []
        for ext in self.video_extensions:
            video_files.extend(self.library_path.rglob(f"*{ext}"))
        
        print(f"Found {len(video_files)} video files")
        
        for video_file in video_files:
            # Skip if it's in a git repo subdirectory
            if ".git" in str(video_file):
                continue
            
            # Parse episode info from filename
            episode = self.parse_episode_from_filename(video_file)
            if not episode:
                if self.verbose:
                    print(f"Could not parse: {video_file.name}")
                continue
            
            # Skip Season 0 (Specials)
            if episode.season == 0:
                if self.verbose:
                    print(f"Skipping special: {video_file.name}")
                continue
            
            # Check for corresponding NFO file
            nfo_path = video_file.with_suffix('.nfo')
            
            if nfo_path.exists():
                episode.nfo_path = nfo_path
                
                # Check if it's a One Pace episode based on NFO content
                if self.is_one_pace_episode(nfo_path):
                    episode.has_anime_episodes = True
                    results.valid_one_pace.append(episode)
                else:
                    # NFO exists but doesn't have the One Pace marker
                    # Check if this episode number is covered by One Pace
                    if episode.episode in self.covered_episodes:
                        # This is an obsolete original episode covered by One Pace
                        results.obsolete_original.append(episode)
                    else:
                        # This might be an original episode not covered by One Pace
                        # or a One Pace episode with malformed NFO
                        results.missing_nfo.append(episode)
            else:
                # No NFO file found
                # Check if this episode is covered by One Pace
                if episode.episode in self.covered_episodes:
                    # Likely an obsolete original episode
                    results.obsolete_original.append(episode)
                else:
                    results.missing_nfo.append(episode)
        
        return results
    
    def generate_report(self, results: ScanResults, json_output: bool = False) -> str:
        """Generate a report from the scan results."""
        if json_output:
            # Generate JSON report
            report_data = {
                "valid_one_pace": len(results.valid_one_pace),
                "obsolete_original": [
                    {
                        "season": ep.season,
                        "episode": ep.episode,
                        "file": str(ep.filepath.name)
                    }
                    for ep in sorted(results.obsolete_original, key=lambda e: (e.season, e.episode))
                ],
                "missing_nfo": [
                    {
                        "season": ep.season,
                        "episode": ep.episode,
                        "file": str(ep.filepath.name)
                    }
                    for ep in sorted(results.missing_nfo, key=lambda e: (e.season, e.episode))
                ]
            }
            return json.dumps(report_data, indent=2)
        
        # Generate text report
        lines = []
        lines.append("=" * 60)
        lines.append("ONE PACE LIBRARY ANALYSIS")
        lines.append("=" * 60)
        lines.append("")
        
        # Obsolete original episodes
        if results.obsolete_original:
            lines.append(f"OBSOLETE ORIGINAL EPISODES ({len(results.obsolete_original)} files)")
            lines.append("These appear to be original One Piece episodes that should be removed:")
            lines.append("-" * 40)
            
            # Group by season for cleaner output
            by_season = {}
            for ep in sorted(results.obsolete_original, key=lambda e: (e.season, e.episode)):
                if ep.season not in by_season:
                    by_season[ep.season] = []
                by_season[ep.season].append(ep)
            
            for season, episodes in sorted(by_season.items()):
                lines.append(f"\nSeason {season}:")
                for ep in episodes:
                    lines.append(f"  Episode {ep.episode}: {ep.filepath.name}")
            lines.append("")
        
        # Missing NFO files
        if results.missing_nfo:
            lines.append(f"MISSING NFO FILES ({len(results.missing_nfo)} files)")
            lines.append("These video files have no NFO metadata:")
            lines.append("-" * 40)
            for ep in sorted(results.missing_nfo, key=lambda e: (e.season, e.episode)):
                extended_str = " (Extended)" if ep.is_extended else ""
                lines.append(f"  Season {ep.season}, Episode {ep.episode}{extended_str}: {ep.filepath.name}")
            lines.append("")
        
        # Valid One Pace episodes
        lines.append(f"VALID ONE PACE EPISODES: {len(results.valid_one_pace)} files")
        lines.append("")
        
        # Summary
        lines.append("=" * 60)
        lines.append("SUMMARY")
        lines.append("=" * 60)
        total_issues = len(results.obsolete_original) + len(results.missing_nfo)
        
        if total_issues == 0:
            lines.append("✓ No issues found! Your library appears to be properly organized.")
        else:
            lines.append(f"Found {total_issues} total issues:")
            if results.obsolete_original:
                lines.append(f"  - {len(results.obsolete_original)} obsolete files to remove")
            if results.missing_nfo:
                lines.append(f"  - {len(results.missing_nfo)} missing NFO files")
        
        lines.append("")
        
        return "\n".join(lines)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Detect obsolete One Piece episodes in a One Pace library"
    )
    parser.add_argument(
        "-d", "--directory",
        help="Path to the One Pace library directory (default: current directory)",
        default=None
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output results in JSON format"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show verbose output during scanning"
    )
    
    args = parser.parse_args()
    
    # Create detector
    detector = ObsoleteEpisodeDetector(
        library_path=args.directory,
        verbose=args.verbose
    )
    
    # Scan library
    results = detector.scan_library()
    
    # Generate and print report
    report = detector.generate_report(results, json_output=args.json)
    print(report)
    
    # Return exit code based on issues found
    total_issues = len(results.obsolete_original) + len(results.missing_nfo)
    return 1 if total_issues > 0 else 0


if __name__ == "__main__":
    exit(main())