#!/usr/bin/env python3
"""One Pace Episode Import Automation Script - Optimized Version.

Enterprise-grade implementation with ~84% code reduction from original.
"""

import sys
import re
import json
import csv
import zipfile
import io
import shutil
import argparse
import unicodedata
from pathlib import Path
from typing import Optional, NewType
from enum import Enum
from functools import wraps, cached_property
from dataclasses import dataclass, field
from contextlib import contextmanager
from itertools import groupby

import requests
from bs4 import BeautifulSoup
from pydantic import BaseModel, Field, field_validator
from tenacity import retry, stop_after_attempt, wait_exponential
from pymediainfo import MediaInfo
from lxml import etree as ET

# Type aliases for better readability (Python 3.12+)
type EpisodeMap = dict[str, list[int]]
type SeasonData = dict[str, str | int | list[int]]
type FilePath = Path | str

# NewTypes for semantic clarity
SeasonNumber = NewType('SeasonNumber', int)
EpisodeNumber = NewType('EpisodeNumber', int)


# ============================================================================
# CONFIGURATION
# ============================================================================

@dataclass(slots=True, kw_only=True)
class Config:
    """Centralized configuration with memory optimization."""
    enable_file_discovery: bool = True
    enable_nfo_generation: bool = True
    enable_file_renaming: bool = True
    enable_file_copying: bool = True
    enable_repository_cleanup: bool = True
    enable_library_cleanup: bool = True
    enable_delete_processed: bool = True
    dry_run: bool = False
    verbose_logging: bool = True
    library_path: str = "E:\\Anime\\One Pace Team\\One Pace"
    repository_path: str = Path(__file__).parent.parent
    source_path: Path = Path(__file__).parent
    seasons_json_path: str = repository_path / "dist/seasons.json"
    ep_guide_url: str = field(
        default="https://docs.google.com/spreadsheets/d/1HQRMJgu_zArp-sLnvFMDzOyjdsht87eFLECxMK858lA/export?format=zip")
    title_plot_url: str = field(
        default="https://docs.google.com/spreadsheets/d/1M0Aa2p5x7NioaH9-u8FyHq6rH3t5s6Sccs8GoC6pHAM/export?format=csv")
    supported_extensions: tuple[str, ...] = ('.mkv', '.mp4')
    show_title: str = "One Pace"
    date_format: str = "%Y.%m.%d"
    retry_attempts: int = 3
    recursive_scan: bool = False
    force_overwrite: bool = False

    @classmethod
    def load(cls, args=None) -> 'Config':
        """Load configuration with CLI overrides."""
        config = cls()
        
        if args:
            if args.update_repo:
                # Configure for repository update mode
                if hasattr(args, 'update_target') and args.update_target:
                    # Use custom target directory
                    config.source_path = Path(args.update_target).resolve()
                else:
                    # Default to repository/One Pace
                    config.source_path = Path(__file__).parent.parent / "One Pace"
                config.enable_file_discovery = False  # Don't look for video files
                config.enable_nfo_generation = True
                config.enable_file_renaming = False
                config.enable_file_copying = False
                config.recursive_scan = True  # Always recursive for repo update
            else:
                # Normal mode - scan for video files
                if args.directory:
                    config.source_path = Path(args.directory).resolve()
                # else keep default (tools folder)
                config.recursive_scan = args.recursive
                
            config.dry_run = args.dry_run
            config.force_overwrite = args.force
            config.verbose_logging = not args.quiet
            
            # Handle no-delete-processed flag
            if hasattr(args, 'no_delete_processed'):
                config.enable_delete_processed = not args.no_delete_processed
            
        return config


# Initialize with defaults, will be replaced in main()
config = Config()


# ============================================================================
# LOGGER
# ============================================================================

class Logger:
    """Enhanced logger with structured output and context tracking."""

    ICONS = {
        "start": "→",
        "success": "✓",
        "fail": "✗",
        "warn": "⚠",
        "skip": "⏭",
        "info": "ℹ",
        "debug": "🔍"
    }

    def __init__(self, verbose: bool = True):
        self.verbose = verbose
        self.context_stack: list[str] = []

    def log(self, message: str, status: str = "info", indent: int = 0) -> None:
        """Log a message with appropriate formatting and context."""
        if not self.verbose and status in ("info", "debug"):
            return

        icon = self.ICONS.get(status, "")
        prefix = "  " * (indent + len(self.context_stack))
        context = f"[{' > '.join(self.context_stack)}] " if self.context_stack else ""

        print(f"{prefix}{icon} {context}{message}")

    def error(self, message: str, recovery: list[str] = None) -> None:
        """Log an error with optional recovery suggestions."""
        self.log(message, "fail")
        if recovery:
            print("Recovery options:")
            for i, option in enumerate(recovery, 1):
                print(f"  {i}. {option}")

    @contextmanager
    def context(self, name: str):
        """Context manager for hierarchical logging."""
        self.context_stack.append(name)
        self.log(f"Starting {name}", "start")
        try:
            yield self
        finally:
            self.log(f"Completed {name}", "success")
            self.context_stack.pop()


# Initialize with defaults, will be replaced in main()
logger = Logger()


# ============================================================================
# BASE CLASSES
# ============================================================================

class BaseManager:
    """Base class for all manager components."""

    def __init__(self, **data_stores):
        for key, default in data_stores.items():
            setattr(self, key, default)

    @retry(stop=stop_after_attempt(config.retry_attempts), wait=wait_exponential())
    def fetch_with_retry(self, func, *args, **kwargs):
        """Universal retry wrapper for network operations."""
        return func(*args, **kwargs)


def handle_file_operation(operation_name="file operation"):
    """Decorator for file operations with standardized error handling."""

    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except FileNotFoundError as e:
                logger.error(f"{operation_name} failed: File not found - {e}")
                return False
            except PermissionError as e:
                logger.error(f"{operation_name} failed: Permission denied - {e}",
                             ["Check file/directory permissions", "Run with elevated permissions"])
                return False
            except OSError as e:
                if "No space left" in str(e):
                    logger.error(f"{operation_name} failed: Disk full - {e}",
                                 ["Free up disk space", "Choose different target"])
                else:
                    logger.error(f"{operation_name} failed: {e}")
                return False

        return wrapper

    return decorator


# ============================================================================
# DATA MODELS
# ============================================================================

class FileFormat(Enum):
    ORIGINAL = "original"
    PLEX_FORMAT = "plex"


class EpisodeInfo(BaseModel):
    """Episode identification data."""
    season: Optional[int] = None
    episode: Optional[int] = None
    title: Optional[str] = None
    arc_name: Optional[str] = None  # Preserve arc name for season lookup


class VideoFile(BaseModel):
    """Video file information."""
    filepath: str
    filename: str
    extension: str = Field(pattern=r'^\.(mkv|mp4)$')
    format_type: FileFormat
    parsed_info: Optional[EpisodeInfo] = None

    @field_validator('extension')
    @classmethod
    def normalize_extension(cls, v):
        return ('.' + v if not v.startswith('.') else v).lower()


class EpisodeData(BaseModel):
    """Episode metadata for NFO generation."""
    title: str = Field(min_length=1)
    season: int = Field(gt=0)
    episode: int = Field(gt=0)
    plot: str = ""
    manga_chapters: list[int] = Field(default_factory=list)
    anime_episodes: list[int] = Field(default_factory=list)
    premiered: str = Field(pattern=r'^\d{4}[-\.]\d{2}[-\.]\d{2}$')  # Required, no default
    aired: str = Field(pattern=r'^\d{4}[-\.]\d{2}[-\.]\d{2}$')  # Required, no default
    original_filename: str

    @field_validator('manga_chapters', 'anime_episodes', mode='before')
    @classmethod
    def validate_positive(cls, v):
        # Handle list validation
        if isinstance(v, list):
            for item in v:
                if item < 1:
                    raise ValueError("Must be positive integer")
        return v

    @cached_property
    def manga_range(self) -> str:
        """Format manga chapters as range string."""
        return self._format_ranges(self.manga_chapters)

    @cached_property
    def anime_range(self) -> str:
        """Format anime episodes as range string."""
        return self._format_ranges(self.anime_episodes)

    @staticmethod
    def _format_ranges(numbers: list[int]) -> str:
        """Convert list of numbers to range string using groupby."""
        if not numbers:
            return ""
        ranges = []
        for k, g in groupby(enumerate(sorted(set(numbers))), lambda i_x: i_x[1] - i_x[0]):
            group = list(map(lambda i_x: i_x[1], g))
            ranges.append(f"{group[0]}-{group[-1]}" if len(group) > 1 else str(group[0]))
        return ", ".join(ranges)


# ============================================================================
# FILENAME PARSER  
# ============================================================================

def get_special_episode_suffix(filename: str) -> str:
    """Extract special episode suffix (Extended, Alternate, etc.) from filename.
    Returns the full suffix string or empty string if none found."""
    import re
    
    # Look for patterns like (Extended) or (Alternate (G-8))
    # Handle nested parentheses properly
    if '(' in filename and ')' in filename:
        # Find the last complete parenthetical expression
        pattern = r'\(([^()]*(?:\([^()]*\)[^()]*)*)\)(?:[^()]*?)$'
        matches = re.findall(pattern, filename)
        
        for match in reversed(matches):
            # Check if this is a special suffix
            if match.startswith('Extended') or match.startswith('Alternate'):
                return match
    
    # Fallback: check for standalone Extended in filename
    if 'extended' in filename.lower():
        return 'Extended'
    
    return ''

def is_special_episode(filename: str) -> bool:
    """Check if a filename indicates a special episode (Extended, Alternate, etc.)."""
    return bool(get_special_episode_suffix(filename))


def apply_title_sanitization(title: str) -> str:
    """Apply common title sanitization rules for filesystem compatibility.
    This is the core logic shared by both sanitize_filename and normalize_title_for_comparison."""
    if not title:
        return ""
    
    # First, normalize Unicode characters to ASCII equivalents
    # NFD decomposes characters like ō into o + combining macron
    # We then encode to ASCII ignoring errors to remove combining marks
    normalized = unicodedata.normalize('NFD', title)
    ascii_title = normalized.encode('ascii', 'ignore').decode('ascii')
    
    # Apply Windows-specific character replacements
    replacements = {':': ' -', '"': "'", '<': '(', '>': ')', '|': '-',
                    '?': '', '*': '', '/': '-', '\\': '-'}
    for old, new in replacements.items():
        ascii_title = ascii_title.replace(old, new)
    
    # Clean up whitespace and trailing dots
    return re.sub(r'\s+', ' ', ascii_title).strip('. ')


def normalize_title_for_comparison(title: str) -> str:
    """Normalize a title for comparison purposes, applying same rules as sanitize_filename.
    This ensures that titles match even after filesystem sanitization."""
    # Apply the same sanitization as filenames get
    sanitized = apply_title_sanitization(title)
    
    # Additionally remove all apostrophes for comparison
    # This handles cases where apostrophes might be inconsistently present/absent
    # (e.g., "Red Hair's" vs "Red Hairs" due to various processing)
    sanitized = sanitized.replace("'", "")
    
    # Make it lowercase for case-insensitive comparison
    return sanitized.lower()


def flexible_match(str1: str, str2: str, threshold: float = 0.8) -> bool:
    """
    Flexible string matching that handles common variations.
    Returns True if strings are similar enough based on threshold.
    """
    # Normalize both strings
    def normalize(s):
        # Convert to lowercase
        s = s.lower()
        # Replace common separators with spaces
        s = re.sub(r'[-_.,;:]', ' ', s)
        # Remove possessive apostrophes
        s = re.sub(r"'s\b", 's', s)
        # Collapse multiple spaces
        s = re.sub(r'\s+', ' ', s)
        # Remove leading/trailing whitespace
        return s.strip()
    
    norm1 = normalize(str1)
    norm2 = normalize(str2)
    
    # Exact match after normalization
    if norm1 == norm2:
        return True
    
    # Check if one contains the other (for partial titles)
    if norm1 in norm2 or norm2 in norm1:
        return True
    
    # Token-based similarity
    tokens1 = set(norm1.split())
    tokens2 = set(norm2.split())
    
    if not tokens1 or not tokens2:
        return False
    
    # Jaccard similarity
    intersection = tokens1 & tokens2
    union = tokens1 | tokens2
    similarity = len(intersection) / len(union) if union else 0
    
    return similarity >= threshold


class FilenameParser:
    """Configurable filename parser for One Pace and Plex formats."""

    PATTERNS = {
        'original': [
            # Pattern for: [One Pace] Paced One Piece - Arc Name Episode ##
            r'\[One Pace\]\s+Paced One Piece\s*-\s*(.+?)\s+Episode\s+(\d+)',
            # Pattern for: [One Pace][chapters] Arc Name Episode [Extended]
            r'\[One Pace\]\[\d+(?:-\d+)?\]\s*(.+?)\s+(\d+)(?:\s+Extended)?',
            # Pattern for: [One Pace] Arc Name Episode [Extended]
            r'\[One Pace\]\s*(.+?)\s+(\d+)(?:\s+Extended)?',
            # Pattern for: One Pace [chapters] Arc Name Episode [Extended]
            r'One Pace\s*\[\d+(?:-\d+)?\]\s*(.+?)\s+(\d+)(?:\s+Extended)?'
        ],
        'plex': [
            r'One Pace\s*-\s*S(\d+)E(\d+)\s*-\s*(.+)',
            r'One Pace\s+S(\d+)E(\d+)\s+(.+)'
        ]
    }

    def __init__(self):
        # Pre-compile patterns for performance
        self.compiled_patterns = {
            format_type: [re.compile(p, re.IGNORECASE) for p in patterns]
            for format_type, patterns in self.PATTERNS.items()
        }

    def parse(self, filename: str, filepath: str = None) -> EpisodeInfo:
        """Parse filename to extract episode information, with fallback to media metadata."""
        # Remove file extension for cleaner parsing
        from pathlib import Path
        filename_without_ext = Path(filename).stem
        
        # First try to parse from filename (without extension)
        for format_type, patterns in self.compiled_patterns.items():
            for pattern in patterns:
                if match := pattern.search(filename_without_ext):
                    info = self._extract_info(match, format_type)
                    
                    # For original format files, always try to get a better title from media metadata
                    # The filename often only has arc name, not the episode title
                    if filepath and format_type == 'original':
                        media_title = self._extract_title_from_media(filepath)
                        if media_title:
                            info.title = media_title
                    elif filepath and not info.title:
                        # For plex format, only use media if we have no title
                        info.title = self._extract_title_from_media(filepath)
                    
                    return info
        
        # If no pattern matched but we have a filepath, still try to get title from media
        info = EpisodeInfo()
        if filepath:
            info.title = self._extract_title_from_media(filepath)
        
        return info

    def identify_format(self, filename: str) -> FileFormat:
        """Identify file format type."""
        # Remove file extension for cleaner pattern matching
        from pathlib import Path
        filename_without_ext = Path(filename).stem
        
        for pattern in self.compiled_patterns['plex']:
            if pattern.search(filename_without_ext):
                return FileFormat.PLEX_FORMAT
        return FileFormat.ORIGINAL

    def _extract_info(self, match, format_type: str) -> EpisodeInfo:
        """Extract episode info from regex match."""
        groups = match.groups()
        info = EpisodeInfo()

        if format_type == 'plex':
            info.season = int(groups[0])
            info.episode = int(groups[1])
            info.title = groups[2].strip()
        else:  # original format
            # For original patterns, we now have: (arc_name, episode_number)
            if len(groups) == 2:
                arc_name = groups[0].strip()
                # Normalize Whiskey to Whisky for consistency
                if "Whiskey" in arc_name:
                    arc_name = arc_name.replace("Whiskey", "Whisky")
                info.arc_name = arc_name  # Store arc name separately
                info.title = arc_name  # Initially use arc name as title (will be replaced by media title if available)
                info.episode = int(groups[1]) if groups[1].isdigit() else None
                # Season will be determined from arc name in get_episode_metadata
                info.season = None

        return info

    def _extract_title_from_media(self, filepath: str) -> Optional[str]:
        """Extract title from media file metadata using pymediainfo."""
        try:
            media_info = MediaInfo.parse(filepath)
            if media_info.general_tracks:
                movie_name = media_info.general_tracks[0].movie_name
                if movie_name:
                    # Clean up title - remove season name and handle extended
                    # Following the same approach as site_scraper.py
                    if "-" in movie_name:
                        episode_title = movie_name.split("-", 1)[1].strip()
                    else:
                        episode_title = movie_name
                    
                    # Check if file has special suffix
                    special_suffix = get_special_episode_suffix(Path(filepath).name)
                    if special_suffix:
                        episode_title = f"{episode_title} ({special_suffix})"
                    
                    logger.log(f"Extracted title from media metadata: {episode_title}", "debug")
                    return episode_title
        except Exception as e:
            logger.log(f"Could not extract media info from {filepath}: {e}", "debug")
        
        return None


# ============================================================================
# DATA SOURCE MANAGER
# ============================================================================

class DataSourceManager(BaseManager):
    """Downloads and parses external data sources."""

    def __init__(self):
        super().__init__(
            ep_guide_zip_content=None,
            title_plot_data={},
            seasons_mapping={},
            title_source_preference=None,  # 'csv', 'media', or None for ask each time
            date_cache={}  # Cache for user-entered dates by season/episode
        )

    @retry(stop=stop_after_attempt(config.retry_attempts), wait=wait_exponential())
    def fetch_data(self, data_type: str) -> dict:
        """Unified data fetching with automatic storage."""
        configs = {
            'ep_guide': (config.ep_guide_url, self._store_zip, 'ep_guide_zip_content'),
            'title_plot': (config.title_plot_url, self._parse_csv, 'title_plot_data'),
        }

        url, parser, storage_attr = configs[data_type]
        logger.log(f"Fetching {data_type} data")

        response = requests.get(url, timeout=30)
        response.raise_for_status()

        data = parser(response)
        setattr(self, storage_attr, data)
        return data

    @handle_file_operation("Load seasons.json")
    def load_seasons_mapping(self, path: str) -> dict:
        """Load seasons configuration."""
        self.seasons_mapping = json.loads(Path(path).read_text())
        logger.log(f"Loaded {len(self.seasons_mapping)} season mappings", "success")
        return self.seasons_mapping

    def handle_missing_date(self, video_filename: str, season: int, episode: int, title: str) -> str:
        """Handle missing date - must be provided by user."""
        import re
        
        # Check if we have a cached date for this episode
        cache_key = f"S{season:02d}E{episode:02d}"
        if cache_key in self.date_cache:
            return self.date_cache[cache_key]
        
        print(f"\n⚠ Missing release date for {video_filename}")
        print(f"  Season {season}, Episode {episode}: {title}")
        print("\nThe release date could not be found in external sources.")
        print("Please enter the release date for this episode.")
        
        while True:
            date_input = input("Enter date (YYYY-MM-DD or YYYY.MM.DD): ").strip()
            
            if not date_input:
                print("Date is required. Please enter a valid date.")
                continue
                
            if re.match(r'^\d{4}[-\.]\d{2}[-\.]\d{2}$', date_input):
                formatted_date = date_input.replace('-', '.')
                # Cache the date for this episode
                self.date_cache[cache_key] = formatted_date
                return formatted_date
            else:
                print("Invalid format. Please use YYYY-MM-DD or YYYY.MM.DD")
    
    def _handle_title_conflict(self, csv_title: str, media_title: str, episode_key: str) -> str:
        """Handle title conflicts between CSV and media metadata/filename."""
        # If we have a global preference, use it
        if self.title_source_preference == 'csv':
            return csv_title
        elif self.title_source_preference == 'media':
            return media_title
        
        # Create a FileOperationsManager instance to get the sanitized titles
        file_ops = FileOperationsManager()
        sanitized_csv = file_ops.sanitize_filename(csv_title)
        sanitized_media = file_ops.sanitize_filename(media_title)
        
        # Otherwise ask the user
        print(f"\n⚠ Title conflict detected for {episode_key}:")
        print(f"  1. From CSV:             {csv_title}")
        print(f"  2. From media/filename:  {media_title}")
        print(f"\nHow they would appear in filename:")
        print(f"  1. CSV sanitized:        {sanitized_csv}")
        print(f"  2. Media sanitized:      {sanitized_media}")
        print("\nSelect title source:")
        print("  [1] Use CSV title for this episode")
        print("  [2] Use media/filename title for this episode")
        print("  [3] Always use CSV titles")
        print("  [4] Always use media/filename titles")
        print("  [q] Quit")
        
        while True:
            choice = input("\nYour choice: ").strip().lower()
            
            if choice == '1':
                return csv_title
            elif choice == '2':
                return media_title
            elif choice == '3':
                self.title_source_preference = 'csv'
                return csv_title
            elif choice == '4':
                self.title_source_preference = 'media'
                return media_title
            elif choice == 'q':
                logger.log("User chose to quit", "warn")
                sys.exit(0)
            else:
                print("Invalid choice. Please select 1, 2, 3, 4, or q.")
    
    def get_episode_metadata(self, episode_info: EpisodeInfo, filename: str = None) -> SeasonData:
        """Combine metadata from multiple sources."""
        # The title here might come from media metadata (via pymediainfo) or filename
        metadata = {
            'title': episode_info.title or '',
            'season': episode_info.season,
            'episode': episode_info.episode,
            'plot': '',
            'manga_chapters': [],
            'anime_episodes': [],
            'premiered': '',
            'aired': ''
        }
        
        # Check if this is a special episode (Extended, Alternate, etc.)
        special_suffix = get_special_episode_suffix(filename) if filename else ''

        # Auto-detect season and arc from arc_name or title
        arc_name = episode_info.arc_name  # Use preserved arc name if available
        
        if not metadata['season']:
            # First try using the preserved arc_name
            if arc_name:
                # Normalize Whiskey to Whisky for season lookup
                normalized_arc = arc_name.replace("Whiskey", "Whisky") if "Whiskey" in arc_name else arc_name
                for name, number in self.seasons_mapping.items():
                    if name.lower() == normalized_arc.lower():
                        metadata['season'] = number
                        break
            # Fall back to searching in title if no arc_name
            elif episode_info.title:
                for name, number in self.seasons_mapping.items():
                    if name.lower() in episode_info.title.lower():
                        metadata['season'] = number
                        arc_name = name
                        break
        else:
            # We have a season number (e.g., from Plex format), but might not have arc_name
            if not arc_name:
                # First try to find arc name from title
                if episode_info.title:
                    for name, number in self.seasons_mapping.items():
                        if name.lower() in episode_info.title.lower():
                            arc_name = name
                            break
                
                # If still no arc_name, reverse lookup from season number
                if not arc_name:
                    for name, number in self.seasons_mapping.items():
                        if number == metadata['season']:
                            arc_name = name
                            logger.log(f"Found arc name '{name}' for season {metadata['season']}", "debug")
                            break

        # Merge with title/plot data from CSV
        if metadata['season'] and metadata['episode']:
            key = f"S{metadata['season']:02d}E{metadata['episode']:02d}"
            csv_data = self.title_plot_data.get(key, {})
            
            # Handle title comparison if CSV has a different title
            if csv_data and csv_data.get('title'):
                csv_title = csv_data['title']
                media_title = metadata['title']  # This could be from media metadata or filename
                
                # Extract and compare base titles without special suffixes
                csv_suffix = get_special_episode_suffix(csv_title)
                media_suffix = get_special_episode_suffix(media_title) if media_title else ''
                
                # Remove suffixes for comparison
                csv_title_base = csv_title
                if csv_suffix:
                    csv_title_base = csv_title.replace(f" ({csv_suffix})", "").strip()
                
                media_title_base = media_title if media_title else ""
                if media_suffix:
                    media_title_base = media_title.replace(f" ({media_suffix})", "").strip()
                
                # Determine which suffix to use (prefer the one from filename/media)
                final_suffix = special_suffix or csv_suffix or media_suffix
                
                # Normalize base titles for comparison to handle sanitization differences
                csv_base_normalized = normalize_title_for_comparison(csv_title_base)
                media_base_normalized = normalize_title_for_comparison(media_title_base)
                
                # Only prompt if normalized base titles actually differ
                if csv_base_normalized != media_base_normalized and csv_title_base and media_title_base:
                    # Show both options with the final suffix applied
                    csv_with_suffix = f"{csv_title_base} ({final_suffix})" if final_suffix else csv_title_base
                    media_with_suffix = f"{media_title_base} ({final_suffix})" if final_suffix else media_title_base
                    
                    # Let user choose between the titles (both showing the same suffix)
                    chosen_title = self._handle_title_conflict(csv_with_suffix, media_with_suffix, key)
                    # Remove any existing suffix from chosen title
                    chosen_suffix = get_special_episode_suffix(chosen_title)
                    if chosen_suffix:
                        chosen_title = chosen_title.replace(f" ({chosen_suffix})", "").strip()
                    # Add the final suffix if needed
                    if final_suffix:
                        metadata['title'] = f"{chosen_title} ({final_suffix})"
                    else:
                        metadata['title'] = chosen_title
                elif csv_title:  
                    # Use CSV title base and add suffix if needed
                    if final_suffix and not csv_title.endswith(f"({final_suffix})"):
                        metadata['title'] = f"{csv_title_base} ({final_suffix})"
                    else:
                        metadata['title'] = csv_title
                elif media_title:  
                    # Use media title (should already have suffix if applicable)
                    metadata['title'] = media_title
                
                # Always use plot from CSV if available
                if csv_data.get('plot'):
                    metadata['plot'] = csv_data['plot']
            elif not metadata['title'] and special_suffix:
                # No CSV data, but we have a special suffix - ensure it's added
                if metadata['title'] and not metadata['title'].endswith(f"({special_suffix})"):
                    metadata['title'] = f"{metadata['title']} ({special_suffix})"
            
            # Get data from arc HTML if available (dates, chapters, episodes)
            if metadata['episode']:
                # Try with the arc_name first if available
                arc_to_search = arc_name if arc_name else None
                
                # If no arc_name, try to determine from season
                if not arc_to_search and metadata['season']:
                    for name, season_num in self.seasons_mapping.items():
                        if season_num == metadata['season']:
                            arc_to_search = name
                            break
                
                if arc_to_search:
                    html_data = self._get_episode_data_from_arc(arc_to_search, metadata['episode'])
                    if html_data:
                        # Add HTML data (dates, chapters, episodes)
                        if html_data.get('premiered'):
                            metadata['premiered'] = html_data['premiered']
                            metadata['aired'] = html_data['aired']
                        if html_data.get('manga_chapters'):
                            metadata['manga_chapters'] = html_data['manga_chapters']
                        if html_data.get('anime_episodes'):
                            metadata['anime_episodes'] = html_data['anime_episodes']

        return metadata

    def _store_zip(self, response) -> bytes:
        """Store ZIP content for on-demand parsing."""
        return response.content
    
    def _get_episode_data_from_arc(self, arc_name: str, episode_num: int) -> dict:
        """Get episode data (dates, chapters, episodes) from arc HTML."""
        if not self.ep_guide_zip_content:
            return {}
        
        try:
            with zipfile.ZipFile(io.BytesIO(self.ep_guide_zip_content)) as zf:
                html_files = [n for n in zf.namelist() if n.endswith('.html')]
                
                # Try to find matching HTML file using flexible matching
                matching_file = None
                
                for html_file in html_files:
                    file_base = Path(html_file).stem
                    
                    # Use flexible matching
                    if flexible_match(arc_name, file_base):
                        matching_file = html_file
                        logger.log(f"Matched arc '{arc_name}' to file '{html_file}'", "debug")
                        break
                
                if not matching_file:
                    logger.log(f"No HTML file found for arc: {arc_name} (tried {len(html_files)} files)", "debug")
                    return {}
                
                # Parse the specific HTML file
                with zf.open(matching_file) as f:
                    soup = BeautifulSoup(f.read().decode('utf-8'), 'html.parser')
                    return self._extract_episode_data(soup, arc_name, episode_num)
        except Exception as e:
            logger.log(f"Error parsing arc HTML for {arc_name}: {e}", "debug")
            return {}

    def _parse_csv(self, response) -> dict[str, dict[str, str]]:
        """Parse CSV content with arc_title and arc_part structure."""
        # Ensure proper UTF-8 decoding
        csv_text = response.content.decode('utf-8')
        reader = csv.DictReader(io.StringIO(csv_text))
        data = {}
        
        # First, ensure seasons_mapping is loaded
        if not self.seasons_mapping:
            logger.log("Warning: seasons_mapping not loaded before parsing CSV", "warn")
            return data
        
        for row in reader:
            arc_title = row.get('arc_title', '').strip()
            arc_part = row.get('arc_part', '').strip()
            
            if not arc_title or not arc_part:
                continue
            
            # Look up season number from arc title
            season = None
            # First try exact match (case-insensitive)
            for name, number in self.seasons_mapping.items():
                if name.lower() == arc_title.lower():
                    season = number
                    break
            
            # If no exact match, try flexible matching
            if not season:
                for name, number in self.seasons_mapping.items():
                    if flexible_match(arc_title, name, threshold=0.6):
                        season = number
                        logger.log(f"Matched arc '{arc_title}' to '{name}' using flexible matching", "debug")
                        break
            
            if season and arc_part.isdigit():
                episode = int(arc_part)
                key = f"S{season:02d}E{episode:02d}"
                data[key] = {
                    'title': row.get('title_en', '').strip(),
                    'plot': row.get('description_en', '').strip(),
                    'arc_title': arc_title
                }
        
        logger.log(f"Loaded {len(data)} episode titles/plots from CSV", "success")
        return data

    def _extract_episode_data(self, soup, arc_name: str, episode_num: int) -> dict:
        """Extract episode data (dates, chapters, episodes) from HTML table."""
        import re
        
        for table in soup.find_all('table'):
            rows = table.find_all('tr')
            if len(rows) < 2:
                continue
            
            # Google Sheets export structure:
            # Row 0: Contains <thead> with column labels (A, B, C, etc.)
            # Row 1 (tbody first row): Contains actual headers with class="s0" 
            # Row 2+: Data rows
            
            # Check if this looks like a Google Sheets table
            tbody = table.find('tbody')
            if not tbody:
                continue
                
            tbody_rows = tbody.find_all('tr')
            if len(tbody_rows) < 2:
                continue
            
            # First tbody row should contain the actual headers
            header_row = tbody_rows[0]
            header_cells = header_row.find_all('td')
            
            # Look for specific columns by content
            release_date_idx = None
            episode_name_idx = None
            chapters_idx = None
            episodes_idx = None
            
            for idx, cell in enumerate(header_cells):
                text = cell.get_text().strip()
                if 'Release Date' in text:
                    release_date_idx = idx
                elif 'One Pace Episode' in text or ('Episode' in text and episode_name_idx is None):
                    episode_name_idx = idx
                elif 'Chapters' in text:
                    chapters_idx = idx
                elif 'Episodes' in text and episodes_idx is None:  # Avoid conflict with "One Pace Episode"
                    episodes_idx = idx
            
            # If we didn't find essential headers, skip this table
            if episode_name_idx is None:
                continue
            
            # Parse data rows (starting from second tbody row)
            for row in tbody_rows[1:]:
                # Skip freezebar rows (Google Sheets exports include these)
                if 'freezebar' in str(row.get('class', [])):
                    continue
                # Also check if any cell has freezebar class
                cells = row.find_all('td')
                if any('freezebar' in str(cell.get('class', [])) for cell in cells):
                    continue
                    
                if not cells or len(cells) <= episode_name_idx:
                    continue
                
                # Extract episode name and number
                ep_name = cells[episode_name_idx].get_text().strip()
                if not ep_name:  # Skip empty rows
                    continue
                    
                # Special case: some episodes use the arc name as the episode name (single-episode arcs)
                # Check if the episode name matches the arc name (using flexible matching)
                if episode_num == 1 and flexible_match(ep_name, arc_name):
                    # This is a special single-episode arc
                    logger.log(f"Found special single-episode arc: {arc_name}", "debug")
                    result = {}
                    
                    # Extract release date
                    if release_date_idx is not None and len(cells) > release_date_idx:
                        release_date = cells[release_date_idx].get_text().strip()
                        # Accept both YYYY.MM.DD and YYYY-MM-DD formats (with 1 or 2 digit month/day)
                        if re.match(r'^\d{4}[\.-]\d{1,2}[\.-]\d{1,2}$', release_date):
                            # Parse and format the date with zero-padding
                            parts = re.split(r'[\.-]', release_date)
                            year = parts[0]
                            month = parts[1].zfill(2)  # Zero-pad to 2 digits
                            day = parts[2].zfill(2)    # Zero-pad to 2 digits
                            formatted_date = f'{year}.{month}.{day}'
                            # Store internally with dots for consistency, will convert to dashes in NFO
                            result['premiered'] = formatted_date
                            result['aired'] = formatted_date
                            logger.log(f"Found release date for {arc_name} episode {episode_num}: {release_date}", "debug")
                    
                    # Extract manga chapters
                    if chapters_idx is not None and len(cells) > chapters_idx:
                        chapters_text = cells[chapters_idx].get_text().strip()
                        result['manga_chapters'] = self._parse_chapter_episode_range(chapters_text, 'Ch.')
                        if result['manga_chapters']:
                            logger.log(f"Found manga chapters for {arc_name} episode {episode_num}: {chapters_text}", "debug")
                    
                    # Extract anime episodes  
                    if episodes_idx is not None and len(cells) > episodes_idx:
                        episodes_text = cells[episodes_idx].get_text().strip()
                        result['anime_episodes'] = self._parse_chapter_episode_range(episodes_text, 'Ep.')
                        if result['anime_episodes']:
                            logger.log(f"Found anime episodes for {arc_name} episode {episode_num}: {episodes_text}", "debug")
                    
                    return result
                
                # Regular case: parse episode number from names like "Syrup Village 01" or "Syrup Village 1"
                match = re.search(r'\b(\d+)\b\s*$', ep_name)
                if match:
                    ep_num_from_name = int(match.group(1))
                    if ep_num_from_name == episode_num:
                        # Found the matching episode
                        result = {}
                        
                        # Extract release date
                        if release_date_idx is not None and len(cells) > release_date_idx:
                            release_date = cells[release_date_idx].get_text().strip()
                            # Accept both YYYY.MM.DD and YYYY-MM-DD formats (with 1 or 2 digit month/day)
                            if re.match(r'^\d{4}[\.-]\d{1,2}[\.-]\d{1,2}$', release_date):
                                # Parse and format the date with zero-padding
                                parts = re.split(r'[\.-]', release_date)
                                year = parts[0]
                                month = parts[1].zfill(2)  # Zero-pad to 2 digits
                                day = parts[2].zfill(2)    # Zero-pad to 2 digits
                                formatted_date = f'{year}.{month}.{day}'
                                # Store internally with dots for consistency, will convert to dashes in NFO
                                result['premiered'] = formatted_date
                                result['aired'] = formatted_date
                                logger.log(f"Found release date for {arc_name} episode {episode_num}: {release_date}", "debug")
                        
                        # Extract manga chapters
                        if chapters_idx is not None and len(cells) > chapters_idx:
                            chapters_text = cells[chapters_idx].get_text().strip()
                            result['manga_chapters'] = self._parse_chapter_episode_range(chapters_text, 'Ch.')
                            if result['manga_chapters']:
                                logger.log(f"Found manga chapters for {arc_name} episode {episode_num}: {chapters_text}", "debug")
                        
                        # Extract anime episodes  
                        if episodes_idx is not None and len(cells) > episodes_idx:
                            episodes_text = cells[episodes_idx].get_text().strip()
                            result['anime_episodes'] = self._parse_chapter_episode_range(episodes_text, 'Ep.')
                            if result['anime_episodes']:
                                logger.log(f"Found anime episodes for {arc_name} episode {episode_num}: {episodes_text}", "debug")
                        
                        return result
        
        logger.log(f"No data found for {arc_name} episode {episode_num}", "debug")
        return {}

    @staticmethod
    def _parse_number_list(s: str) -> list[int]:
        """Parse number ranges like '4-7, 9, 10-11'."""
        if not s:
            return []
        numbers = []
        for part in s.split(','):
            if '-' in part:
                try:
                    start, end = map(int, part.split('-'))
                    numbers.extend(range(start, end + 1))
                except ValueError:
                    continue
            else:
                try:
                    numbers.append(int(part.strip()))
                except ValueError:
                    continue
        return sorted(set(numbers))
    
    def _parse_chapter_episode_range(self, text: str, prefix: str = '') -> list[int]:
        """Parse chapter/episode ranges from text like 'Ch. 23-25' or 'Ep. 9-10'."""
        if not text:
            return []
        
        import re
        # Remove prefix if present (Ch., Ep., etc.)
        if prefix:
            text = text.replace(prefix, '').strip()
        
        # Extract all number ranges and individual numbers
        # Matches patterns like: 23-25, 9-10, 17, etc.
        numbers = []
        
        # Handle ranges (e.g., "23-25")
        for match in re.finditer(r'(\d+)\s*-\s*(\d+)', text):
            start, end = int(match.group(1)), int(match.group(2))
            numbers.extend(range(start, end + 1))
            # Remove the matched range from text to avoid double-processing
            text = text.replace(match.group(0), '')
        
        # Handle individual numbers not part of ranges
        for match in re.finditer(r'\b(\d+)\b', text):
            numbers.append(int(match.group(1)))
        
        return sorted(set(numbers))


# ============================================================================
# FILE MANAGERS
# ============================================================================

class FileDiscoveryEngine:
    """Discovers and categorizes video files."""

    def __init__(self):
        self.parser = FilenameParser()

    @handle_file_operation("Scan directory")
    def scan_directory(self, path: FilePath, recursive: bool = False) -> list[VideoFile]:
        """Scan for video files."""
        directory = Path(path).resolve()
        glob_pattern = "**/*" if recursive else "*"
        
        files = []
        for f in directory.glob(glob_pattern):
            if f.is_file() and f.suffix in config.supported_extensions:
                files.append(VideoFile(
                    filepath=str(f),
                    filename=f.name,
                    extension=f.suffix,
                    format_type=self.parser.identify_format(f.name),
                    parsed_info=self.parser.parse(f.name, str(f))
                ))
        return files
    
    @handle_file_operation("Scan NFO files")
    def scan_nfo_files(self, path: FilePath, recursive: bool = False) -> list[Path]:
        """Scan for existing NFO files in repository."""
        directory = Path(path).resolve()
        glob_pattern = "**/*.nfo" if recursive else "*.nfo"
        
        nfo_files = []
        for f in directory.glob(glob_pattern):
            # Skip season.nfo and tvshow.nfo
            if f.name not in ['season.nfo', 'tvshow.nfo']:
                nfo_files.append(f)
        return nfo_files


class MetadataProcessor:
    """Handles NFO generation and metadata processing."""

    def generate_nfo_content(self, episode_data: EpisodeData) -> str:
        """Generate NFO XML content using lxml for proper XML handling."""
        # Create root element
        root = ET.Element("episodedetails")
        
        # Add basic episode info
        ET.SubElement(root, 'title').text = episode_data.title
        ET.SubElement(root, 'showtitle').text = config.show_title
        ET.SubElement(root, 'season').text = str(episode_data.season)
        ET.SubElement(root, 'episode').text = str(episode_data.episode)
        
        # Build plot with manga/anime info
        plot = episode_data.plot.strip()
        if episode_data.manga_range or episode_data.anime_range:
            plot += "\n\n"
            if episode_data.manga_range:
                plot += f"Manga Chapter(s): {episode_data.manga_range}\n\n"
            if episode_data.anime_range:
                plot += f"Anime Episode(s): {episode_data.anime_range}"
        
        ET.SubElement(root, 'plot').text = plot
        
        # Add dates (convert from YYYY.MM.DD to YYYY-MM-DD if needed)
        premiered = episode_data.premiered.replace('.', '-') if episode_data.premiered else ""
        aired = episode_data.aired.replace('.', '-') if episode_data.aired else ""
        
        ET.SubElement(root, 'premiered').text = premiered
        ET.SubElement(root, 'aired').text = aired
        
        # Convert to string with proper XML formatting
        return ET.tostring(
            root,
            pretty_print=True,
            xml_declaration=True,
            encoding='UTF-8'
        ).decode('utf-8')

    @handle_file_operation("Check existing NFO")
    def check_existing_nfo(self, season: int, episode: int, dirs: list[str]) -> Optional[str]:
        """Check for existing NFO files."""
        patterns = [f"*S{season:02d}E{episode:02d}*.nfo", f"*S{season}E{episode}*.nfo"]

        for directory in filter(lambda d: Path(d).exists(), dirs):
            for pattern in patterns:
                if files := list(Path(directory).glob(pattern)):
                    return str(files[0])
        return None


class FileOperationsManager:
    """Handles file operations with Windows compatibility."""

    RESERVED_NAMES = {'CON', 'PRN', 'AUX', 'NUL'} | {f'{x}{i}' for x in ['COM', 'LPT'] for i in range(1, 10)}

    def sanitize_filename(self, title: str) -> str:
        """Sanitize for Windows compatibility and normalize Unicode characters."""
        # Use the shared sanitization logic
        return apply_title_sanitization(title)

    def generate_plex_filename(self, season: int, episode: int, title: str) -> str:
        """Generate Plex-compatible filename."""
        return f"One Pace - S{season:02d}E{episode:02d} - {self.sanitize_filename(title)}"

    @contextmanager
    def batch_operation(self, operation_name: str):
        """Context manager for batch file operations with automatic rollback."""
        completed = []
        try:
            logger.log(f"Starting {operation_name}", "start")
            yield completed
            logger.log(f"Completed {operation_name}", "success")
        except Exception as e:
            logger.error(f"Failed {operation_name}: {e}")
            for path in completed:
                Path(path).unlink(missing_ok=True)
            raise

    def copy_files(self, source: FilePath, targets: list[FilePath],
                   filename: str = None, nfo: str = None) -> bool:
        """Copy video and NFO files to targets."""
        source_path = Path(source)
        filename = filename or source_path.name

        with self.batch_operation("file copy") as completed:
            for target_dir in map(Path, targets):
                target_dir.mkdir(parents=True, exist_ok=True)

                if config.dry_run:
                    logger.log(f"DRY RUN: Would copy to {target_dir}", "info")
                else:
                    dest = target_dir / filename
                    shutil.copy2(source_path, dest)
                    completed.append(dest)

                    if nfo:
                        nfo_path = dest.with_suffix('.nfo')
                        nfo_path.write_text(nfo, encoding='utf-8')
                        completed.append(nfo_path)

                    logger.log(f"Copied to {target_dir}", "success")
        return True

    def write_nfo(self, nfo_content: str, video_filepath: FilePath, 
                  new_filename: str = None) -> bool:
        """Write NFO file alongside the video file."""
        if not nfo_content:
            return False
            
        video_path = Path(video_filepath)
        
        # Determine the NFO filename based on whether we're renaming
        if new_filename:
            nfo_filename = Path(new_filename).with_suffix('.nfo').name
        else:
            nfo_filename = video_path.with_suffix('.nfo').name
            
        # Write NFO in the same directory as the video file
        nfo_path = video_path.parent / nfo_filename
        
        with self.batch_operation("NFO write") as completed:
            if config.dry_run:
                logger.log(f"DRY RUN: Would write NFO to {nfo_path}", "info")
            else:
                nfo_path.write_text(nfo_content, encoding='utf-8')
                completed.append(nfo_path)
                logger.log(f"Wrote NFO to {nfo_path}", "success")
        
        return True


class CleanupManager:
    """Manages cleanup of original anime episodes."""

    @handle_file_operation("Find original episodes")
    def find_original_episodes(self, episodes: list[int], path: FilePath) -> list[str]:
        """Find original One Piece anime episode files (not One Pace files)."""
        if not episodes or not path:
            return []

        search_dir = Path(path)
        if not search_dir.exists():
            return []

        import re
        found_files = []
        extensions = ['*.nfo'] + [f"*{ext}" for ext in config.supported_extensions]
        
        for ext in extensions:
            for f in search_dir.rglob(ext):
                filename = f.name.lower()
                
                # Skip One Pace files
                if 'one pace' in filename or 'one-pace' in filename:
                    continue
                
                # Look for original One Piece episode patterns
                # Common patterns: "One Piece 001", "One Piece - 001", "One Piece E001", "OP001", etc.
                for ep in episodes:
                    # Patterns to match original anime episodes
                    patterns = [
                        rf'\bone\s*piece\s*-?\s*0*{ep}\b',  # "One Piece 001", "One Piece - 001"
                        rf'\bone\s*piece\s*-?\s*e0*{ep}\b',  # "One Piece E001"
                        rf'\bop\s*0*{ep}\b',  # "OP001"
                        rf'\bepisode\s*0*{ep}\b',  # "Episode 001"
                        rf'(?:^|[^\d])0*{ep}(?:[^\d]|$)',  # Standalone episode number (but not in SxxExx format)
                    ]
                    
                    # Check if it's NOT a One Pace season/episode format
                    if not re.search(r's\d+e\d+', filename):
                        for pattern in patterns:
                            if re.search(pattern, filename):
                                found_files.append(str(f))
                                break
                        
        return list(set(found_files))  # Remove duplicates

    def prompt_for_deletion(self, files: list[str]) -> bool:
        """Prompt user for deletion confirmation."""
        if not files:
            return False

        logger.log(f"Found {len(files)} files to clean up:")
        for i, f in enumerate(files[:5], 1):
            print(f"  {i}. {Path(f).name}")
        if len(files) > 5:
            print(f"  ... and {len(files) - 5} more")

        return input("\nDelete these files? (y/n): ").strip().lower() in ['y', 'yes']

    @handle_file_operation("Delete files")
    def delete_files(self, files: list[str]) -> bool:
        """Delete files sequentially."""
        if not files:
            return True

        for file_path in files:
            Path(file_path).unlink(missing_ok=True)
        return True

    @handle_file_operation("Delete files")
    def delete_processed_video(self, video_filepath: str) -> bool:
        """Delete the processed video file after confirmation."""
        if config.dry_run:
            logger.log(f"DRY RUN: Would delete processed video: {Path(video_filepath).name}", "info")
            return True
            
        # Prompt for confirmation unless force flag is set
        if not config.force_overwrite:
            response = input(f"\nDelete processed video file '{Path(video_filepath).name}'? (y/n/a for all): ").strip().lower()
            if response == 'a':
                config.force_overwrite = True  # Set force flag to skip future prompts
            elif response not in ['y', 'yes']:
                logger.log("Skipped deletion of processed video", "skip")
                return False
        
        try:
            Path(video_filepath).unlink()
            logger.log(f"Deleted processed video: {Path(video_filepath).name}", "success")
            return True
        except Exception as e:
            logger.log(f"Failed to delete processed video: {e}", "warn")
            return False
    
    def perform_cleanup(self, episode_data: EpisodeData) -> bool:
        """Perform cleanup of original anime episodes."""
        if not config.enable_repository_cleanup and not config.enable_library_cleanup:
            return True
        
        cleanup_performed = False
        
        # Find original anime episodes that this One Pace episode replaces
        if episode_data.anime_episodes:
            paths_to_search = []
            
            if config.enable_repository_cleanup:
                paths_to_search.append(config.repository_path)
            if config.enable_library_cleanup and config.library_path:
                paths_to_search.append(config.library_path)
            
            for path in paths_to_search:
                files = self.find_original_episodes(episode_data.anime_episodes, path)
                if files and self.prompt_for_deletion(files):
                    if self.delete_files(files):
                        logger.log(f"Deleted {len(files)} original episode files", "success")
                        cleanup_performed = True
        
        return cleanup_performed


# ============================================================================
# MAIN PIPELINE
# ============================================================================

def is_one_pace_episode(nfo_path: Path) -> bool:
    """Check if an NFO file is for a One Pace episode (not original One Piece)."""
    try:
        content = nfo_path.read_text(encoding='utf-8')
        # One Pace episodes have chapter/episode information in their plot
        # Patterns to match:
        # - "Manga Chapter(s): 1-3" or "Chapter(s): 1-3"
        # - "Anime Episode(s): 1-3" or "Episode(s): 1-3"
        # - Also handles "Unavailable" for specials
        chapter_pattern = r'(?:Manga\s+)?Chapter\s*\(?s?\)?:\s*(?:\d+|\w+)'
        episode_pattern = r'(?:Anime\s+)?Episode\s*\(?s?\)?:\s*(?:\d+|\w+)'
        
        has_chapters = re.search(chapter_pattern, content, re.IGNORECASE)
        has_episodes = re.search(episode_pattern, content, re.IGNORECASE)
        
        # One Pace episodes have at least one of these markers
        # Original One Piece episodes have neither
        return bool(has_chapters or has_episodes)
    except Exception as e:
        # If we can't read the file, raise the error
        raise RuntimeError(f"Failed to read NFO file {nfo_path}: {e}")

def parse_nfo_filename(nfo_path: Path) -> Optional[EpisodeInfo]:
    """Parse episode information from NFO filename."""
    # Pattern: One Pace - S##E## - Title.nfo
    # The title already includes any special suffix in parentheses
    pattern = r"One Pace - S(\d+)E(\d+) - (.+?)\.nfo"
    match = re.match(pattern, nfo_path.name)
    
    if match:
        info = EpisodeInfo(
            season=int(match.group(1)),
            episode=int(match.group(2)),
            title=match.group(3).strip()  # Title includes any suffix like (Extended) or (Alternate (G-8))
        )
        return info
    return None


def update_repository_nfos(managers: dict, args) -> None:
    """Update NFO files in the repository with latest metadata."""
    
    with logger.context("Repository NFO Update"):
        # Scan all NFO files in repository
        nfo_files = managers['discovery'].scan_nfo_files(
            config.source_path,  # Will be "One Pace" folder when --update-repo
            recursive=config.recursive_scan
        )
        
        logger.log(f"Found {len(nfo_files)} episode NFO files to check", "info")
        
        updated_count = 0
        skipped_count = 0
        failed_count = 0
        unchanged_count = 0
        
        for nfo_path in nfo_files:
            # Skip original One Piece episodes (not One Pace)
            try:
                if not is_one_pace_episode(nfo_path):
                    logger.log(f"Skipping original One Piece episode: {nfo_path.name}", "skip")
                    skipped_count += 1
                    continue
            except RuntimeError as e:
                logger.log(f"Error reading {nfo_path.name}: {e}", "fail")
                failed_count += 1
                continue
            
            # Parse episode info from NFO filename
            episode_info = parse_nfo_filename(nfo_path)
            if not episode_info:
                logger.log(f"Could not parse: {nfo_path.name}", "warn")
                failed_count += 1
                continue
            
            # Special handling for Season 0 (Specials)
            if episode_info.season == 0:
                logger.log(f"Skipping special episode: {nfo_path.name} (Season 0)", "skip")
                skipped_count += 1
                continue
            
            # Find arc name from season mapping
            arc_name = None
            if episode_info.season:
                for name, season_num in managers['data'].seasons_mapping.items():
                    if season_num == episode_info.season:
                        arc_name = name
                        episode_info.arc_name = arc_name
                        logger.log(f"Season {episode_info.season} maps to arc '{arc_name}'", "debug")
                        break
            
            # If we couldn't find arc name, try to match from title
            if not arc_name and episode_info.title:
                # Try to match title against all known arc names
                for name in managers['data'].seasons_mapping.keys():
                    if flexible_match(name, episode_info.title, threshold=0.6):
                        arc_name = name
                        episode_info.arc_name = arc_name
                        logger.log(f"Matched title '{episode_info.title}' to arc '{arc_name}'", "debug")
                        break
            
            # Get latest metadata from external sources
            metadata = managers['data'].get_episode_metadata(episode_info, nfo_path.name)
            
            if not metadata.get('season') or not metadata.get('episode'):
                logger.log(f"Could not get metadata for: {nfo_path.name}", "warn")
                failed_count += 1
                continue
            
            # Handle missing dates
            if not metadata.get('premiered'):
                metadata['premiered'] = managers['data'].handle_missing_date(
                    nfo_path.name,
                    metadata['season'],
                    metadata['episode'],
                    metadata.get('title', '')
                )
                metadata['aired'] = metadata['premiered']
            
            # Create episode data object
            try:
                episode_data = EpisodeData(
                    title=metadata.get('title', f"Episode {metadata['episode']}"),
                    season=metadata['season'],
                    episode=metadata['episode'],
                    plot=metadata.get('plot', ''),
                    manga_chapters=metadata.get('manga_chapters', []),
                    anime_episodes=metadata.get('anime_episodes', []),
                    premiered=metadata['premiered'],
                    aired=metadata.get('aired', metadata['premiered']),
                    original_filename=nfo_path.name
                )
            except Exception as e:
                logger.log(f"Failed to create episode data for {nfo_path.name}: {e}", "fail")
                failed_count += 1
                continue
            
            # Generate new NFO content
            new_nfo_content = managers['meta'].generate_nfo_content(episode_data)
            
            # Check if NFO file needs renaming based on title change
            expected_nfo_filename = managers['file'].generate_plex_filename(
                episode_data.season,
                episode_data.episode,
                episode_data.title
            ) + '.nfo'
            
            needs_rename = nfo_path.name != expected_nfo_filename
            
            # Compare with existing content
            content_changed = False
            try:
                existing_content = nfo_path.read_text(encoding='utf-8')
                if new_nfo_content.strip() != existing_content.strip():
                    content_changed = True
            except Exception as e:
                logger.log(f"Could not read {nfo_path.name}: {e}", "warn")
                content_changed = True  # Assume it needs updating if we can't read it
            
            if not content_changed and not needs_rename:
                # No changes needed
                unchanged_count += 1
                continue
            
            # Show what will change
            if needs_rename:
                logger.log(f"Rename needed: {nfo_path.name} -> {expected_nfo_filename}", "info")
            if content_changed:
                logger.log(f"Content update needed: {nfo_path.name}", "info")
            
            if not args.force and not args.dry_run:
                if needs_rename:
                    response = input(f"  Rename and update {nfo_path.name}? (y/n/a for all): ").lower()
                else:
                    response = input(f"  Update {nfo_path.name}? (y/n/a for all): ").lower()
                if response == 'a':
                    args.force = True
                elif response != 'y':
                    skipped_count += 1
                    continue
            
            if not args.dry_run:
                # If renaming is needed, handle it
                if needs_rename:
                    new_nfo_path = nfo_path.parent / expected_nfo_filename
                    # Check if target already exists and is different from source
                    if new_nfo_path.exists() and new_nfo_path != nfo_path:
                        logger.log(f"  Target NFO already exists: {expected_nfo_filename}", "warn")
                        response = input(f"    Overwrite existing file? (y/n): ").lower()
                        if response != 'y':
                            skipped_count += 1
                            continue
                        # Delete the existing target file
                        new_nfo_path.unlink()
                    
                    # Write new content to the old file first (to preserve it if rename fails)
                    nfo_path.write_text(new_nfo_content, encoding='utf-8')
                    
                    # Now rename the file (atomic operation)
                    try:
                        nfo_path.rename(new_nfo_path)
                        logger.log(f"  Renamed: {nfo_path.name} -> {expected_nfo_filename}", "success")
                    except OSError as e:
                        # If rename fails (e.g., cross-filesystem), fall back to copy+delete
                        logger.log(f"  Rename failed, using copy+delete: {e}", "debug")
                        new_nfo_path.write_text(new_nfo_content, encoding='utf-8')
                        if nfo_path != new_nfo_path and nfo_path.exists():
                            nfo_path.unlink()
                            logger.log(f"  Renamed: {nfo_path.name} -> {expected_nfo_filename}", "success")
                        else:
                            logger.log(f"  Updated: {nfo_path.name}", "success")
                else:
                    # Just update content
                    nfo_path.write_text(new_nfo_content, encoding='utf-8')
                    logger.log(f"  Updated: {nfo_path.name}", "success")
            else:
                if needs_rename:
                    logger.log(f"  DRY RUN: Would rename {nfo_path.name} -> {expected_nfo_filename}", "info")
                if content_changed:
                    logger.log(f"  DRY RUN: Would update content of {nfo_path.name}", "info")
            
            updated_count += 1
        
        # Summary
        logger.log(f"\nSummary:", "info")
        logger.log(f"  Updated: {updated_count} files", "success")
        logger.log(f"  Unchanged: {unchanged_count} files", "info")
        logger.log(f"  Skipped: {skipped_count} files", "info")
        logger.log(f"  Failed: {failed_count} files", "warn" if failed_count > 0 else "info")


def process_episode(video_file: VideoFile, managers: dict) -> bool:
    """Process single video file."""
    try:
        with logger.context(f"Processing {video_file.filename}"):
            # Get metadata
            metadata = managers['data'].get_episode_metadata(video_file.parsed_info, video_file.filename)

            if not metadata.get('season') or not metadata.get('episode'):
                logger.log(f"Cannot determine season/episode from parsed info: {video_file.parsed_info}, metadata: {metadata}", "warn")
                return False
            
            # Skip specials (Season 0)
            if metadata.get('season') == 0:
                logger.log(f"Skipping special episode: {video_file.filename} (Season 0)", "skip")
                return True  # Return True to indicate it was "processed" (skipped intentionally)

            # Format metadata as it will appear in NFO file
            def format_ranges(numbers: list[int]) -> str:
                """Format list of numbers as range string."""
                if not numbers:
                    return ""
                from itertools import groupby
                ranges = []
                for k, g in groupby(enumerate(sorted(set(numbers))), lambda i_x: i_x[1] - i_x[0]):
                    group = list(map(lambda i_x: i_x[1], g))
                    ranges.append(f"{group[0]}-{group[-1]}" if len(group) > 1 else str(group[0]))
                return ", ".join(ranges)
            
            # Build plot as it will appear in NFO
            formatted_plot = metadata.get('plot', '').strip()
            manga_range = format_ranges(metadata.get('manga_chapters', []))
            anime_range = format_ranges(metadata.get('anime_episodes', []))
            if manga_range:
                formatted_plot += f" Manga chapters: {manga_range}."
            if anime_range:
                formatted_plot += f" Anime episodes: {anime_range}."
            
            # Convert dates to YYYY-MM-DD format
            premiered = metadata.get('premiered', '').replace('.', '-') if metadata.get('premiered') else 'N/A'
            aired = metadata.get('aired', '').replace('.', '-') if metadata.get('aired') else 'N/A'
            
            # Log formatted metadata as it will appear in NFO
            logger.log(f"Complete metadata (as NFO):", "info")
            logger.log(f"  Title: {metadata['title']}", "info")
            logger.log(f"  Season: {metadata['season']}, Episode: {metadata['episode']}", "info")
            logger.log(f"  Plot: {formatted_plot[:150]}{'...' if len(formatted_plot) > 150 else ''}", "debug")
            logger.log(f"  Premiered: {premiered}, Aired: {aired}", "debug")
            
            # Create episode data
            try:
                # Handle missing dates by prompting user
                premiered = metadata.get('premiered')
                aired = metadata.get('aired')
                
                if not premiered:
                    # Get date from user
                    premiered = managers['data'].handle_missing_date(
                        video_file.filename,
                        metadata['season'],
                        metadata['episode'],
                        metadata.get('title', '')
                    )
                
                if not aired:
                    aired = premiered  # Use same date for both if only one is missing
                
                episode_data = EpisodeData(
                    title=metadata.get('title', f"Episode {metadata['episode']}"),
                    season=metadata['season'],
                    episode=metadata['episode'],
                    plot=metadata.get('plot', ''),
                    manga_chapters=metadata.get('manga_chapters', []),
                    anime_episodes=metadata.get('anime_episodes', []),
                    premiered=premiered,
                    aired=aired,
                    original_filename=video_file.filename
                )
            except Exception as validation_error:
                logger.error(f"EpisodeData validation failed for file '{video_file.filename}':\n"
                           f"Parsed info: {video_file.parsed_info}\n"
                           f"Metadata values: {metadata}\n"
                           f"Validation error: {validation_error}")
                return False

            # Generate NFO if enabled
            nfo_content = None
            if config.enable_nfo_generation:
                search_dirs = [d for d in [config.library_path, config.repository_path] if d]
                existing_nfo = managers['meta'].check_existing_nfo(
                    episode_data.season, episode_data.episode, search_dirs
                )

                if not existing_nfo or input(f"Overwrite existing NFO? (y/n): ").lower() == 'y':
                    nfo_content = managers['meta'].generate_nfo_content(episode_data)

            # Generate filename if enabled
            new_filename = None
            if config.enable_file_renaming:
                new_filename = managers['file'].generate_plex_filename(
                    episode_data.season, episode_data.episode, episode_data.title
                ) + video_file.extension

            # Copy files if enabled
            if config.enable_file_copying:
                target_dirs = [
                    Path(config.library_path) / f"Season {episode_data.season}",
                    Path(config.repository_path) / "One Pace" / f"Season {episode_data.season}"
                ]
                managers['file'].copy_files(
                    video_file.filepath,
                    [str(d) for d in target_dirs if d.parent],
                    new_filename or video_file.filename,
                    nfo_content
                )
            # If NFO generation is enabled but file copying is not, write NFO separately
            elif config.enable_nfo_generation and nfo_content:
                managers['file'].write_nfo(
                    nfo_content, 
                    video_file.filepath,
                    new_filename  # Pass new filename if renaming is enabled
                )

            # Cleanup original anime episodes if enabled
            if config.enable_repository_cleanup or config.enable_library_cleanup:
                managers['cleanup'].perform_cleanup(episode_data)

            # Delete the processed video file after successful processing
            # Only delete if file was successfully copied (if copying was enabled) and deletion is enabled
            if config.enable_file_copying and config.enable_delete_processed:
                managers['cleanup'].delete_processed_video(video_file.filepath)
            
            return True

    except Exception as e:
        logger.error(f"Failed to process '{video_file.filename}': {e}\n"
                   f"File path: {video_file.filepath}\n"
                   f"Parsed info: {video_file.parsed_info}")
        return False


def main():
    """Main entry point."""
    # Parse command-line arguments
    parser = argparse.ArgumentParser(
        description="One Pace Episode Import and NFO Management Tool"
    )
    parser.add_argument(
        '-d', '--directory',
        help='Directory to scan for video files (default: script directory)'
    )
    parser.add_argument(
        '-r', '--recursive',
        action='store_true',
        help='Recursively scan subdirectories'
    )
    parser.add_argument(
        '--update-repo',
        action='store_true',
        help='Update NFO files in repository with latest metadata'
    )
    parser.add_argument(
        '--update-target',
        help='Target directory for --update-repo command (default: repository/One Pace)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without making them'
    )
    parser.add_argument(
        '--force',
        action='store_true',
        help='Skip confirmation prompts'
    )
    parser.add_argument(
        '--quiet',
        action='store_true',
        help='Reduce output verbosity'
    )
    parser.add_argument(
        '--no-delete-processed',
        action='store_true',
        help='Do not delete processed video files after copying'
    )
    
    args = parser.parse_args()
    
    # Load config with CLI overrides
    global config
    config = Config.load(args)
    
    # Initialize logger with verbosity setting
    global logger
    logger = Logger(verbose=config.verbose_logging)
    
    with logger.context("One Pace Episode Import"):
        # Validation for normal mode
        if not args.update_repo:
            if not any([config.enable_file_discovery, config.enable_nfo_generation,
                       config.enable_file_renaming, config.enable_file_copying]):
                logger.log("All features disabled. Enable at least one.", "warn")
                return 0
            
            if config.enable_file_copying and not config.library_path:
                logger.error("Library path required for file copying")
                return 1
        
        # Initialize managers
        managers = {
            'data': DataSourceManager(),
            'discovery': FileDiscoveryEngine(),
            'meta': MetadataProcessor(),
            'file': FileOperationsManager(),
            'cleanup': CleanupManager()
        }
        
        # Load external data sources
        with logger.context("Loading Data"):
            try:
                # Load seasons mapping first since CSV parsing depends on it
                managers['data'].load_seasons_mapping(config.seasons_json_path)
                # Then load CSV and HTML data
                managers['data'].fetch_data('title_plot')
                managers['data'].fetch_data('ep_guide')
            except Exception as e:
                logger.error(f"Failed to load data: {e}")
                if input("Continue anyway? (y/n): ").lower() != 'y':
                    return 1
        
        if args.update_repo:
            # Repository update mode - update NFOs with latest metadata
            update_repository_nfos(managers, args)
        else:
            # Normal mode - process video files in specified directory
            if config.enable_file_discovery:
                with logger.context("File Discovery"):
                    logger.log(f"Scanning directory: {config.source_path}", "info")
                    video_files = managers['discovery'].scan_directory(
                        config.source_path,
                        recursive=config.recursive_scan
                    )
                    
                    if not video_files:
                        logger.log("No video files found", "warn")
                        return 0
                    
                    logger.log(f"Found {len(video_files)} video files", "success")
                    
                    # Process files sequentially
                    for vf in video_files:
                        process_episode(vf, managers)
        
        logger.log("Processing complete!", "success")
        return 0


if __name__ == "__main__":
    sys.exit(main())