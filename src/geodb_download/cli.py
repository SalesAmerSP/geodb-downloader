"""Command-line interface for downloading MyF5 GeoLocationUpdates_Pulse files."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path
import sys
from typing import Optional

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*args, **kwargs):
        pass

from geodb_download.client import (
    DEFAULT_AUTH_URL,
    DEFAULT_DOWNLOADS_API_URL,
    STAGE_AUTH_URL,
    MyF5AuthError,
    MyF5Client,
    MyF5Error,
)
from geodb_download.downloader import FileDownloader, format_bytes
from geodb_download.finder import (
    DEFAULT_CONTAINER_PATTERN,
    DEFAULT_FILE_PATTERN,
    GeoDBFinder,
)
from geodb_download.models import PulseMatch, VersionInfo

logger = logging.getLogger("geodb_download")


def configure_logging(verbose: bool = False, quiet: bool = False) -> None:
    """Set up console logging format and level."""
    if quiet:
        level = logging.ERROR
    elif verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    # Remove any existing handlers
    root_logger.handlers.clear()
    root_logger.addHandler(handler)


def get_client(
    client_id: Optional[str] = None,
    client_secret: Optional[str] = None,
    stage: bool = False,
    auth_url: Optional[str] = None,
    api_url: Optional[str] = None,
    env_file: Optional[str] = None,
) -> MyF5Client:
    """Instantiate MyF5Client resolving credentials from arguments, env, or .env file."""
    if env_file:
        load_dotenv(dotenv_path=env_file)
    else:
        # Load default .env if present
        load_dotenv()

    resolved_id = (
        client_id
        or os.getenv("MYF5_CLIENT_ID")
        or os.getenv("F5_CLIENT_ID")
    )
    resolved_secret = (
        client_secret
        or os.getenv("MYF5_CLIENT_SECRET")
        or os.getenv("F5_CLIENT_SECRET")
    )

    if not resolved_id or not resolved_secret:
        sys.stderr.write(
            "\nError: Missing MyF5 API credentials!\n"
            "Please provide them via:\n"
            "  1. Flags: --client-id <ID> --client-secret <SECRET>\n"
            "  2. Environment variables: MYF5_CLIENT_ID and MYF5_CLIENT_SECRET\n"
            "  3. A .env file in the current directory\n\n"
        )
        sys.exit(1)

    target_auth_url = auth_url or (STAGE_AUTH_URL if stage else DEFAULT_AUTH_URL)
    target_api_url = api_url or DEFAULT_DOWNLOADS_API_URL

    return MyF5Client(
        client_id=resolved_id,
        client_secret=resolved_secret,
        auth_url=target_auth_url,
        api_base_url=target_api_url,
    )


def resolve_product_lines(
    client: MyF5Client,
    product_family: str,
    product_line: Optional[str] = None,
) -> list[str]:
    """Resolve and validate product lines for a given family."""
    metadata = client.get_metadata()
    family_match = None
    for f in metadata:
        if f.name.lower() == product_family.lower():
            family_match = f
            break

    if not family_match:
        available = [f.name for f in metadata]
        raise MyF5Error(
            f"Product family '{product_family}' not found. Available families: {', '.join(available)}"
        )

    all_lines = [pl.name for pl in family_match.product_lines]

    if not product_line:
        # If product_line not given, check if BIG-IP lines exist and return them
        return all_lines

    # Verify requested product line exists (case-insensitive match)
    for line in all_lines:
        if line.lower() == product_line.lower():
            return [line]

    raise MyF5Error(
        f"Product line '{product_line}' not found in family '{product_family}'.\n"
        f"Available lines: {', '.join(all_lines)}"
    )


def execute_download(
    client: MyF5Client,
    finder: GeoDBFinder,
    downloader: FileDownloader,
    family: str,
    line: str,
    target_version: Optional[str] = None,
    all_versions: bool = False,
    latest_version_only: bool = True,
    output_dir: Path | str = "./downloads",
    organize_by_version: bool = False,
    dry_run: bool = False,
    preferred_location: Optional[str] = None,
    skip_existing: bool = True,
    overwrite: bool = False,
    verify_checksum: bool = True,
) -> list[Path]:
    """Execute search and download for the latest GeoLocationUpdates_Pulse file(s)."""
    logger.info("Fetching versions for %s / %s...", family, line)
    versions = client.get_all_product_versions(family, line)
    if not versions:
        logger.warning("No versions found for %s / %s", family, line)
        return []

    # Sort versions semantically (newest first)
    sorted_versions = finder.sort_versions(versions, reverse=True)

    # Determine which versions to process
    versions_to_process: list[VersionInfo] = []
    if target_version:
        matched_v = [v for v in sorted_versions if v.version.lower() == target_version.lower().lstrip("v")]
        if not matched_v:
            # Try exact match
            matched_v = [v for v in sorted_versions if v.version.lower() == target_version.lower()]
        if not matched_v:
            avail = [v.version for v in sorted_versions]
            raise MyF5Error(
                f"Version '{target_version}' not found for {family}/{line}.\n"
                f"Available versions: {', '.join(avail[:15])}{'...' if len(avail) > 15 else ''}"
            )
        versions_to_process = matched_v
    elif all_versions:
        versions_to_process = sorted_versions
    elif latest_version_only:
        versions_to_process = [sorted_versions[0]]

    # For each version, find the latest Pulse file
    matches_to_download: list[PulseMatch] = []
    for ver in versions_to_process:
        latest_match = finder.find_latest_for_version(ver, family, line)
        if latest_match:
            matches_to_download.append(latest_match)
        else:
            logger.info("No GeoLocationUpdates_Pulse found for version %s", ver.version)

    if not matches_to_download:
        logger.warning("No matching GeoLocationUpdates_Pulse files found.")
        return []

    logger.info(
        "Identified %d GeoLocationUpdates_Pulse file(s) to process:",
        len(matches_to_download),
    )
    for idx, m in enumerate(matches_to_download, 1):
        date_str = m.parsed_date.strftime("%Y-%m-%d %H:%M:%S") if m.parsed_date != m.parsed_date.min else "Unknown date"
        size_str = format_bytes(m.bytes)
        logger.info(
            "  [%d] Product Version %s -> %s (Date: %s, Size: %s)",
            idx,
            m.product_version,
            m.filename,
            date_str,
            size_str,
        )

    downloaded_files: list[Path] = []
    base_out = Path(output_dir)

    for idx, match in enumerate(matches_to_download, 1):
        print(f"\n[{idx}/{len(matches_to_download)}] Version {match.product_version}: {match.filename}")
        if dry_run:
            print(f"  [DRY RUN] Would fetch file links from href: {match.href}")
            print(f"  [DRY RUN] Would save to: {base_out / (match.product_version if organize_by_version else '') / match.filename}")
            continue

        # Fetch download links and checksum metadata
        if not match.href:
            logger.error("No href provided for file %s, skipping", match.filename)
            continue

        print(f"  Resolving pre-signed download link for {match.filename}...")
        file_links = client.get_file_links(match.href)

        target_dir = base_out / match.product_version if organize_by_version else base_out

        saved_path = downloader.download(
            links_response=file_links,
            dest_dir=target_dir,
            filename=match.filename,
            preferred_location=preferred_location,
            skip_existing=skip_existing,
            overwrite=overwrite,
            verify_checksum=verify_checksum,
            show_progress=True,
        )
        downloaded_files.append(saved_path)
        print(f"  Saved to: {saved_path}")

    return downloaded_files


def run_list(
    client: MyF5Client,
    finder: GeoDBFinder,
    category: str,
    family: str,
    line: Optional[str] = None,
) -> None:
    """Handle the 'list' subcommand."""
    if category == "families":
        metadata = client.get_metadata()
        print("\nAvailable Product Families:")
        for f in metadata:
            print(f"  • {f.name} ({len(f.product_lines)} product lines)")
        print()

    elif category == "lines":
        metadata = client.get_metadata()
        fam = next((f for f in metadata if f.name.lower() == family.lower()), None)
        if not fam:
            print(f"\nProduct family '{family}' not found.\n")
            return
        print(f"\nProduct Lines for {fam.name}:")
        for pl in fam.product_lines:
            print(f"  • {pl.name} (Display: '{pl.display_name}')")
        print()

    elif category in ("versions", "pulse"):
        lines = resolve_product_lines(client, family, line)
        for l in lines:
            print(f"\n=== Product Line: {family} / {l} ===")
            versions = client.get_all_product_versions(family, l)
            sorted_v = finder.sort_versions(versions, reverse=True)

            if category == "versions":
                print(f"Found {len(sorted_v)} version(s):")
                for v in sorted_v:
                    rel = f"(Released: {v.release_date})" if v.release_date else ""
                    containers = ", ".join(c.container for c in v.containers)
                    print(f"  • {v.version:<10} {rel} [Containers: {containers}]")
            else:  # pulse
                print(f"Searching for GeoLocationUpdates_Pulse in {len(sorted_v)} versions...")
                pulse_matches = finder.find_latest_per_version(sorted_v, family, l)
                if not pulse_matches:
                    print("  No GeoLocationUpdates_Pulse files found.")
                else:
                    for ver_str, match in pulse_matches.items():
                        d_str = (
                            match.parsed_date.strftime("%Y-%m-%d")
                            if match.parsed_date != match.parsed_date.min
                            else "Unknown date"
                        )
                        size_str = format_bytes(match.bytes)
                        print(f"  • Version {ver_str:<10} -> {match.filename} ({size_str}, {d_str})")
        print()


def build_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="geodb-download",
        description=(
            "Download the latest GeoLocationUpdates_Pulse from MyF5 API.\n"
            "Navigates: Product Family -> Product Line -> Product Version -> "
            "GeoLocationUpdates Container -> GeoLocationUpdates_Pulse file."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Global options
    parser.add_argument("--client-id", help="MyF5 Client ID (default: env MYF5_CLIENT_ID)")
    parser.add_argument("--client-secret", help="MyF5 Client Secret (default: env MYF5_CLIENT_SECRET)")
    parser.add_argument("--env-file", help="Path to .env file for loading credentials")
    parser.add_argument("--stage", action="store_true", help="Use MyF5 staging authentication URL")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose debug logging")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress non-error logging output")

    subparsers = parser.add_subparsers(dest="command")

    # Download command
    dl_parser = subparsers.add_parser("download", help="Download latest GeoLocationUpdates_Pulse")
    _add_download_arguments(dl_parser)

    # List command
    list_parser = subparsers.add_parser("list", help="List families, lines, versions, or pulse updates")
    list_parser.add_argument(
        "category",
        choices=["families", "lines", "versions", "pulse"],
        help="What to list (families, lines, versions, pulse)",
    )
    list_parser.add_argument("--family", default="BIG-IP", help="Product Family (default: BIG-IP)")
    list_parser.add_argument("--product-line", "-l", help="Product Line (e.g. big-ip_v17.x)")

    # Also add download arguments to root parser so running without 'download' subcommand works directly
    _add_download_arguments(parser)

    return parser


def _add_download_arguments(p: argparse.ArgumentParser) -> None:
    p.add_argument("--family", default="BIG-IP", help="Product Family (default: BIG-IP)")
    p.add_argument(
        "--product-line",
        "-l",
        help="Product Line (e.g., big-ip_v17.x, big-ip_v16.x). If omitted, searches all BIG-IP lines.",
    )
    p.add_argument(
        "--version",
        help="Specific product version (e.g., 17.1.1, 16.1.4). Default is the latest version.",
    )
    p.add_argument(
        "--all-versions",
        action="store_true",
        help="Download the last GeoLocationUpdates_Pulse for EVERY product version found.",
    )
    p.add_argument(
        "--output-dir",
        "-o",
        default="./downloads",
        help="Directory to save downloaded files (default: ./downloads)",
    )
    p.add_argument(
        "--organize-by-version",
        action="store_true",
        help="Organize files in subdirectories by product version (e.g., ./downloads/17.1.1/...)",
    )
    p.add_argument(
        "--location",
        help="Preferred hosting location (e.g., 'USA - WEST COAST', 'USA - EAST COAST', 'IRELAND')",
    )
    p.add_argument(
        "--container-pattern",
        default=DEFAULT_CONTAINER_PATTERN,
        help=f"Regex pattern for container name (default: '{DEFAULT_CONTAINER_PATTERN}')",
    )
    p.add_argument(
        "--file-pattern",
        default=DEFAULT_FILE_PATTERN,
        help=f"Regex pattern for pulse file name (default: '{DEFAULT_FILE_PATTERN}')",
    )
    p.add_argument(
        "--overwrite",
        action="store_true",
        help="Always redownload and overwrite existing files",
    )
    p.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip checksum verification",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Locate latest files and show download details without downloading",
    )


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry point."""
    parser = build_parser()
    args = parser.parse_args(argv)

    configure_logging(verbose=args.verbose, quiet=args.quiet)

    cmd = args.command or "download"

    try:
        client = get_client(
            client_id=args.client_id,
            client_secret=args.client_secret,
            stage=args.stage,
            env_file=args.env_file,
        )

        finder = GeoDBFinder(
            container_pattern=getattr(args, "container_pattern", DEFAULT_CONTAINER_PATTERN),
            file_pattern=getattr(args, "file_pattern", DEFAULT_FILE_PATTERN),
        )

        if cmd == "list":
            run_list(
                client=client,
                finder=finder,
                category=args.category,
                family=args.family,
                line=args.product_line,
            )
            return 0

        elif cmd == "download":
            downloader = FileDownloader()

            product_lines = resolve_product_lines(
                client=client,
                product_family=args.family,
                product_line=args.product_line,
            )

            all_downloaded = []
            for pl in product_lines:
                logger.info("Processing product line: %s / %s", args.family, pl)
                downloaded = execute_download(
                    client=client,
                    finder=finder,
                    downloader=downloader,
                    family=args.family,
                    line=pl,
                    target_version=args.version,
                    all_versions=args.all_versions,
                    latest_version_only=not args.all_versions and not args.version,
                    output_dir=args.output_dir,
                    organize_by_version=args.organize_by_version,
                    dry_run=args.dry_run,
                    preferred_location=args.location,
                    skip_existing=not args.overwrite,
                    overwrite=args.overwrite,
                    verify_checksum=not args.no_verify,
                )
                all_downloaded.extend(downloaded)

            if not args.dry_run:
                print(f"\nDone! Successfully processed {len(all_downloaded)} file(s).")
            return 0

    except KeyboardInterrupt:
        sys.stderr.write("\nOperation cancelled by user.\n")
        return 130
    except (MyF5Error, Exception) as e:
        logger.error("%s", e)
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
