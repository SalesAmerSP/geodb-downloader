"""Finder and selector for GeoLocationUpdates_Pulse across product versions."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
import re
from typing import Optional

try:
    from packaging.version import InvalidVersion, Version
    from packaging.version import parse as parse_pkg_version
except ImportError:
    parse_pkg_version = None

from geodb_download.models import (
    ContainerInfo,
    FileInfo,
    PulseMatch,
    VersionInfo,
)

logger = logging.getLogger(__name__)

# Default patterns matching GeoLocation containers and Pulse update files
DEFAULT_CONTAINER_PATTERN = r"(?i)geolocation|pulse"
DEFAULT_FILE_PATTERN = r"(?i)pulse"

IGNORED_EXTENSIONS = (
    ".md5",
    ".sig",
    ".384.sig",
    ".sha256",
    ".txt",
    ".html",
    ".pdf",
)


def parse_date(date_str: Optional[str]) -> datetime:
    """Parse various date formats or find dates embedded in strings."""
    if not date_str:
        return datetime.min

    cleaned = date_str.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"

    # Standard ISO formats
    try:
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except Exception:
        pass

    # Common explicit formats
    for fmt in (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
        "%Y%m%d",
        "%d-%b-%Y",
        "%d/%m/%Y",
    ):
        try:
            return datetime.strptime(cleaned, fmt)
        except Exception:
            pass

    # Regex search for date pattern YYYY-MM-DD or YYYYMMDD in text/filename
    m = re.search(r"(20\d\d)[-_]?([01]\d)[-_]?([0-3]\d)", cleaned)
    if m:
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except Exception:
            pass

    return datetime.min


def version_sort_key(version_str: str) -> tuple:
    """Generate a sort key for product versions, preferring semantic versioning."""
    if not version_str:
        return ()

    cleaned = version_str.strip().lstrip("vV")
    if parse_pkg_version is not None:
        try:
            return (1, parse_pkg_version(cleaned))
        except Exception:
            pass

    # Fallback to numeric / token extraction
    parts = []
    for token in re.split(r"([0-9]+)", cleaned):
        if token.isdigit():
            parts.append(int(token))
        elif token:
            parts.append(token)
    return (0, tuple(parts))


def extract_best_date(file_info: FileInfo, container: ContainerInfo, version: VersionInfo) -> datetime:
    """Extract the most accurate timestamp for a file candidate."""
    # Priority 1: File metadata uploadDate
    if file_info.meta and file_info.meta.upload_date:
        d = parse_date(file_info.meta.upload_date)
        if d != datetime.min:
            return d

    # Priority 2: Embedded date in file name or description
    d = parse_date(file_info.filename)
    if d != datetime.min:
        return d
    d = parse_date(file_info.description)
    if d != datetime.min:
        return d

    # Priority 3: Container releaseDate
    if container.release_date:
        d = parse_date(container.release_date)
        if d != datetime.min:
            return d

    # Priority 4: Version releaseDate
    if version.release_date:
        d = parse_date(version.release_date)
        if d != datetime.min:
            return d

    return datetime.min


class GeoDBFinder:
    """Finds and resolves the latest GeoLocationUpdates_Pulse files across product versions."""

    def __init__(
        self,
        container_pattern: str = DEFAULT_CONTAINER_PATTERN,
        file_pattern: str = DEFAULT_FILE_PATTERN,
    ):
        self.container_pattern = container_pattern
        self.file_pattern = file_pattern
        self.container_re = re.compile(container_pattern)
        self.file_re = re.compile(file_pattern)

    def is_payload_file(self, filename: str) -> bool:
        """Check if file is an actual data payload and not a signature/checksum/readme."""
        fn = filename.lower()
        return not fn.endswith(IGNORED_EXTENSIONS)

    def is_matching_container(self, container: ContainerInfo) -> bool:
        """Check if container name or description matches the GeoLocation Pulse pattern."""
        c_name = container.container or ""
        desc = container.description or ""
        # If searching for Pulse, exclude Edge containers unless explicitly requested
        if "pulse" in self.container_pattern.lower() and "edge" in c_name.lower() and "pulse" not in c_name.lower():
            return False
        return bool(
            self.container_re.search(c_name)
            or self.container_re.search(desc)
        )

    def is_matching_file(self, file_info: FileInfo, container: Optional[ContainerInfo] = None) -> bool:
        """Check if file is a valid Pulse update file."""
        if not self.is_payload_file(file_info.filename):
            return False

        # If the container itself explicitly indicates Pulse (e.g. GeoLocationUpdates_Pulse)
        if container and re.search(r"(?i)pulse", container.container or ""):
            return True

        # Otherwise check if file name or description matches the file pattern
        return bool(
            self.file_re.search(file_info.filename or "")
            or self.file_re.search(file_info.description or "")
        )

    def find_matches_in_version(
        self,
        version: VersionInfo,
        product_family: str,
        product_line: str,
    ) -> list[PulseMatch]:
        """Find all matching GeoLocationUpdates_Pulse files in a given product version."""
        matches: list[PulseMatch] = []

        for container in version.containers:
            if not self.is_matching_container(container):
                continue

            for f in container.files:
                if not self.is_matching_file(f, container):
                    continue

                best_date = extract_best_date(f, container, version)
                matches.append(
                    PulseMatch(
                        product_family=product_family,
                        product_line=product_line,
                        product_version=version.version,
                        container_name=container.container,
                        file_info=f,
                        container_release_date=container.release_date,
                        parsed_date=best_date,
                    )
                )

        # Sort matches descending: most recent date first, then by filename
        matches.sort(key=lambda m: (m.parsed_date, m.filename), reverse=True)
        return matches

    def find_latest_for_version(
        self,
        version: VersionInfo,
        product_family: str,
        product_line: str,
    ) -> Optional[PulseMatch]:
        """Return the single latest GeoLocationUpdates_Pulse file for a product version."""
        matches = self.find_matches_in_version(version, product_family, product_line)
        return matches[0] if matches else None

    def find_latest_per_version(
        self,
        versions: list[VersionInfo],
        product_family: str,
        product_line: str,
    ) -> dict[str, PulseMatch]:
        """Return a mapping of version_string -> latest PulseMatch for each product version."""
        result: dict[str, PulseMatch] = {}
        for v in versions:
            match = self.find_latest_for_version(v, product_family, product_line)
            if match:
                result[v.version] = match
        return result

    def sort_versions(self, versions: list[VersionInfo], reverse: bool = True) -> list[VersionInfo]:
        """Sort product versions by semantic versioning (newest first by default)."""
        return sorted(versions, key=lambda v: version_sort_key(v.version), reverse=reverse)
