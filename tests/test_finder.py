"""Tests for GeoDBFinder logic."""

from datetime import datetime
import pytest

from geodb_download.finder import GeoDBFinder, parse_date, version_sort_key
from geodb_download.models import ContainerInfo, FileInfo, FileMeta, VersionInfo


def test_parse_date():
    assert parse_date("2026-08-17T09:04:52Z") == datetime(2026, 8, 17, 9, 4, 52)
    assert parse_date("2024-05-19") == datetime(2024, 5, 19)
    assert parse_date("GeoLocationUpdates_Pulse_20260211.zip") == datetime(2026, 2, 11)
    assert parse_date(None) == datetime.min
    assert parse_date("") == datetime.min


def test_version_sort_key():
    v1 = "17.1.1"
    v2 = "16.1.4"
    v3 = "17.0.0"
    v4 = "17.1.1.1"

    assert version_sort_key(v1) > version_sort_key(v2)
    assert version_sort_key(v1) > version_sort_key(v3)
    assert version_sort_key(v4) > version_sort_key(v1)


def test_finder_identifies_pulse_files():
    finder = GeoDBFinder()

    # Container with older and newer pulse files
    f_old = FileInfo(
        filename="GeoLocationUpdates_Pulse_20240101.zip",
        bytes=1000,
        href="/path/to/old",
        meta=FileMeta(upload_date="2024-01-01T00:00:00Z"),
    )
    f_new = FileInfo(
        filename="GeoLocationUpdates_Pulse_20240501.zip",
        bytes=1200,
        href="/path/to/new",
        meta=FileMeta(upload_date="2024-05-01T00:00:00Z"),
    )
    f_other = FileInfo(
        filename="ip-geolocation-standard.zip",
        bytes=800,
        href="/path/to/other",
    )

    container_geo = ContainerInfo(
        container="GeoLocationUpdates",
        release_date="2024-05-01",
        files=[f_old, f_other, f_new],
    )
    container_ve = ContainerInfo(
        container="Virtual Edition",
        files=[FileInfo(filename="BIGIP-17.1.1.iso")],
    )

    version_17 = VersionInfo(
        version="17.1.1",
        release_date="2024-02-11",
        containers=[container_geo, container_ve],
    )

    matches = finder.find_matches_in_version(version_17, "BIG-IP", "big-ip_v17.x")
    assert len(matches) == 2
    # Newest should be first
    assert matches[0].filename == "GeoLocationUpdates_Pulse_20240501.zip"
    assert matches[0].href == "/path/to/new"

    latest = finder.find_latest_for_version(version_17, "BIG-IP", "big-ip_v17.x")
    assert latest is not None
    assert latest.filename == "GeoLocationUpdates_Pulse_20240501.zip"


def test_finder_different_pulse_per_product_version():
    finder = GeoDBFinder()

    # Version 17.1.1
    v17 = VersionInfo(
        version="17.1.1",
        containers=[
            ContainerInfo(
                container="GeoLocationUpdates",
                files=[
                    FileInfo(
                        filename="GeoLocationUpdates_Pulse_v17_20260201.zip",
                        bytes=5000,
                        href="/v17/pulse",
                        meta=FileMeta(upload_date="2026-02-01T00:00:00Z"),
                    )
                ],
            )
        ],
    )

    # Version 16.1.4
    v16 = VersionInfo(
        version="16.1.4",
        containers=[
            ContainerInfo(
                container="GeoLocationUpdates",
                files=[
                    FileInfo(
                        filename="GeoLocationUpdates_Pulse_v16_20260115.zip",
                        bytes=4800,
                        href="/v16/pulse",
                        meta=FileMeta(upload_date="2026-01-15T00:00:00Z"),
                    )
                ],
            )
        ],
    )

    results = finder.find_latest_per_version([v17, v16], "BIG-IP", "big-ip_line")
    assert "17.1.1" in results
    assert "16.1.4" in results
    assert results["17.1.1"].filename == "GeoLocationUpdates_Pulse_v17_20260201.zip"
    assert results["16.1.4"].filename == "GeoLocationUpdates_Pulse_v16_20260115.zip"


def test_finder_pulse_container_and_edge_exclusion():
    finder = GeoDBFinder()

    # Live API structure: containers named GeoLocationUpdates_Pulse and GeoLocationUpdates_Edge
    pulse_container = ContainerInfo(
        container="GeoLocationUpdates_Pulse",
        release_date="2026-09-28",
        files=[
            FileInfo(filename="README.txt", bytes=500),
            FileInfo(filename="README.txt.md5", bytes=33),
            FileInfo(filename="ip-geolocation-v2-2.0.0-20260928.253.0.zip.md5", bytes=33),
            FileInfo(
                filename="ip-geolocation-v2-2.0.0-20260928.253.0.zip",
                bytes=253587407,
                href="/downloads/pulse.zip",
            ),
        ],
    )

    edge_container = ContainerInfo(
        container="GeoLocationUpdates_Edge",
        release_date="2026-09-28",
        files=[
            FileInfo(
                filename="ip-geolocation-v2-2.0.0-20260928.684.0.zip",
                bytes=250000000,
                href="/downloads/edge.zip",
            )
        ],
    )

    ver = VersionInfo(
        version="17.1.1",
        release_date="2024-02-11",
        containers=[pulse_container, edge_container],
    )

    matches = finder.find_matches_in_version(ver, "BIG-IP", "big-ip_v17.x")
    assert len(matches) == 1
    assert matches[0].container_name == "GeoLocationUpdates_Pulse"
    assert matches[0].filename == "ip-geolocation-v2-2.0.0-20260928.253.0.zip"
    assert matches[0].bytes == 253587407

