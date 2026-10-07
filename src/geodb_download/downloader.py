"""File downloader with streaming, progress reporting, and hash verification."""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from pathlib import Path
import sys
import time
from typing import Callable, Optional

import requests

from geodb_download.models import FileLinksResponse

logger = logging.getLogger(__name__)


class DownloaderError(Exception):
    """Base error for download operations."""
    pass


class ChecksumMismatchError(DownloaderError):
    """Raised when downloaded file hash does not match expected metadata."""
    pass


def format_bytes(num_bytes: Optional[int]) -> str:
    """Format bytes into human-readable string (KB, MB, GB)."""
    if num_bytes is None:
        return "Unknown size"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:3.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} PB"


def format_time(seconds: float) -> str:
    """Format seconds into MM:SS or HH:MM:SS."""
    if seconds < 0 or seconds > 86400 * 7:
        return "--:--"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h:02d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def verify_file_hashes(
    file_path: Path,
    expected_sha256: Optional[str] = None,
    expected_md5: Optional[str] = None,
) -> bool:
    """Verify an existing file against expected sha256 and md5 hashes."""
    if not expected_sha256 and not expected_md5:
        return True

    sha256_hasher = hashlib.sha256() if expected_sha256 else None
    md5_hasher = hashlib.md5() if expected_md5 else None

    with open(file_path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            if sha256_hasher:
                sha256_hasher.update(chunk)
            if md5_hasher:
                md5_hasher.update(chunk)

    if sha256_hasher and expected_sha256:
        calculated_hex = sha256_hasher.hexdigest().lower()
        calculated_b64 = base64.b64encode(sha256_hasher.digest()).decode("ascii")
        exp_clean = expected_sha256.strip()
        if calculated_hex != exp_clean.lower() and calculated_b64 != exp_clean:
            return False

    if md5_hasher and expected_md5:
        calculated_md5 = md5_hasher.hexdigest().lower()
        if calculated_md5 != expected_md5.strip().lower():
            return False

    return True


class FileDownloader:
    """Manages downloading files from pre-signed URLs with progress and checksum validation."""

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()

    def select_download_url(
        self,
        links_response: FileLinksResponse,
        preferred_location: Optional[str] = None,
    ) -> str:
        """Select best URL from available download links based on location."""
        if not links_response.download_links:
            raise DownloaderError(f"No download links available for {links_response.filename}")

        if preferred_location:
            pref = preferred_location.strip().lower()
            for link in links_response.download_links:
                if link.location and pref in link.location.lower():
                    return link.href

        # Default to first link
        return links_response.download_links[0].href

    def download(
        self,
        links_response: FileLinksResponse,
        dest_dir: Path | str,
        filename: Optional[str] = None,
        preferred_location: Optional[str] = None,
        skip_existing: bool = True,
        overwrite: bool = False,
        verify_checksum: bool = True,
        show_progress: bool = True,
        chunk_size: int = 1024 * 1024,
    ) -> Path:
        """Download file and verify checksum."""
        target_dir = Path(dest_dir)
        target_dir.mkdir(parents=True, exist_ok=True)

        target_filename = filename or links_response.filename or "GeoLocationUpdates_Pulse.zip"
        dest_path = target_dir / target_filename
        part_path = target_dir / f"{target_filename}.part"

        expected_sha256 = (
            links_response.meta.sha256
            if links_response.meta and links_response.meta.sha256
            else None
        )
        expected_md5 = links_response.md5 or (
            links_response.meta.md5
            if links_response.meta and links_response.meta.md5
            else None
        )

        # Check if already exists and valid
        if dest_path.exists() and not overwrite:
            if skip_existing:
                if verify_checksum:
                    if verify_file_hashes(dest_path, expected_sha256, expected_md5):
                        logger.info("File '%s' already exists and checksum verified. Skipping.", dest_path)
                        return dest_path
                    else:
                        logger.warning("File '%s' exists but checksum does not match. Re-downloading...", dest_path)
                else:
                    logger.info("File '%s' already exists. Skipping download.", dest_path)
                    return dest_path

        download_url = self.select_download_url(links_response, preferred_location)
        logger.info("Downloading '%s' from %s", target_filename, download_url[:80] + "...")

        try:
            resp = self.session.get(download_url, stream=True, timeout=60.0)
            resp.raise_for_status()
        except requests.RequestException as e:
            raise DownloaderError(f"Failed to initiate download of {target_filename}: {e}") from e

        total_bytes = None
        content_length = resp.headers.get("Content-Length")
        if content_length:
            try:
                total_bytes = int(content_length)
            except ValueError:
                pass
        if total_bytes is None and links_response.bytes:
            total_bytes = links_response.bytes

        sha256_hasher = hashlib.sha256() if verify_checksum and expected_sha256 else None
        md5_hasher = hashlib.md5() if verify_checksum and expected_md5 else None

        downloaded_bytes = 0
        start_time = time.time()
        last_progress_time = 0.0

        is_tty = sys.stdout.isatty() and show_progress

        try:
            with open(part_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=chunk_size):
                    if not chunk:
                        continue
                    f.write(chunk)
                    chunk_len = len(chunk)
                    downloaded_bytes += chunk_len

                    if sha256_hasher:
                        sha256_hasher.update(chunk)
                    if md5_hasher:
                        md5_hasher.update(chunk)

                    # Update progress at most every 0.2 seconds
                    now = time.time()
                    if is_tty and (now - last_progress_time >= 0.2 or downloaded_bytes == total_bytes):
                        last_progress_time = now
                        elapsed = max(0.001, now - start_time)
                        speed = downloaded_bytes / elapsed
                        if total_bytes and total_bytes > 0:
                            percent = (downloaded_bytes / total_bytes) * 100
                            eta = (total_bytes - downloaded_bytes) / speed if speed > 0 else 0
                            bar_width = 30
                            filled = int(bar_width * downloaded_bytes // total_bytes)
                            bar = "█" * filled + "░" * (bar_width - filled)
                            msg = (
                                f"\r  [{bar}] {percent:5.1f}% | "
                                f"{format_bytes(downloaded_bytes)}/{format_bytes(total_bytes)} | "
                                f"{format_bytes(int(speed))}/s | ETA: {format_time(eta)}"
                            )
                        else:
                            msg = (
                                f"\r  Downloaded: {format_bytes(downloaded_bytes)} | "
                                f"{format_bytes(int(speed))}/s"
                            )
                        sys.stdout.write(msg)
                        sys.stdout.flush()

            if is_tty:
                sys.stdout.write("\n")
                sys.stdout.flush()

        except Exception as e:
            if part_path.exists():
                try:
                    part_path.unlink()
                except OSError:
                    pass
            raise DownloaderError(f"Download interrupted for {target_filename}: {e}") from e

        # Validate Checksums
        if verify_checksum:
            if sha256_hasher and expected_sha256:
                calc_hex = sha256_hasher.hexdigest().lower()
                calc_b64 = base64.b64encode(sha256_hasher.digest()).decode("ascii")
                exp_clean = expected_sha256.strip()
                if calc_hex != exp_clean.lower() and calc_b64 != exp_clean:
                    part_path.unlink(missing_ok=True)
                    raise ChecksumMismatchError(
                        f"SHA-256 mismatch for {target_filename}!\n"
                        f"Expected: {exp_clean}\n"
                        f"Calculated (hex): {calc_hex}\n"
                        f"Calculated (base64): {calc_b64}"
                    )
                logger.debug("SHA-256 verified successfully: %s", calc_hex)

            if md5_hasher and expected_md5:
                calc_md5 = md5_hasher.hexdigest().lower()
                exp_clean = expected_md5.strip().lower()
                if calc_md5 != exp_clean:
                    part_path.unlink(missing_ok=True)
                    raise ChecksumMismatchError(
                        f"MD5 mismatch for {target_filename}!\n"
                        f"Expected: {exp_clean}\n"
                        f"Calculated: {calc_md5}"
                    )
                logger.debug("MD5 verified successfully: %s", calc_md5)

        # Atomic rename part file to final destination
        if dest_path.exists():
            dest_path.unlink()
        part_path.rename(dest_path)

        duration = time.time() - start_time
        avg_speed = downloaded_bytes / max(0.001, duration)
        logger.info(
            "Download complete: '%s' (%s in %.2fs, %s/s)",
            dest_path,
            format_bytes(downloaded_bytes),
            duration,
            format_bytes(int(avg_speed)),
        )
        return dest_path
