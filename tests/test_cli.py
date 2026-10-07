"""Tests for CLI parsing and command execution."""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from geodb_download.cli import build_parser, main
from geodb_download.models import (
    ContainerInfo,
    DownloadLinkInfo,
    FileInfo,
    FileLinksResponse,
    FileMeta,
    ProductFamilyInfo,
    ProductLineInfo,
    VersionInfo,
)


def test_cli_parser_defaults():
    parser = build_parser()
    args = parser.parse_args(["--client-id", "id", "--client-secret", "sec"])
    assert args.family == "BIG-IP"
    assert args.command is None  # Defaults to download in main()
    assert args.output_dir == "./downloads"


def test_cli_dry_run(capsys):
    parser = build_parser()
    args = [
        "--client-id", "test_id",
        "--client-secret", "test_secret",
        "--dry-run",
        "--product-line", "big-ip_v17.x",
        "--version", "17.1.1",
    ]

    mock_metadata = [
        ProductFamilyInfo(
            name="BIG-IP",
            product_lines=[ProductLineInfo(name="big-ip_v17.x", product_family="BIG-IP")],
        )
    ]

    mock_version = VersionInfo(
        version="17.1.1",
        release_date="2024-02-11",
        containers=[
            ContainerInfo(
                container="GeoLocationUpdates",
                files=[
                    FileInfo(
                        filename="GeoLocationUpdates_Pulse_17.1.1_20260211.zip",
                        bytes=1234567,
                        href="/downloads-management/v1/downloads/product/BIG-IP/big-ip_v17.x/17.1.1/english/GeoLocationUpdates/GeoLocationUpdates_Pulse_17.1.1_20260211.zip",
                        meta=FileMeta(upload_date="2026-02-11T10:00:00Z"),
                    )
                ],
            )
        ],
    )

    with patch("geodb_download.cli.MyF5Client") as mock_client_cls:
        client_instance = mock_client_cls.return_value
        client_instance.get_metadata.return_value = mock_metadata
        client_instance.get_all_product_versions.return_value = [mock_version]

        ret = main(args)
        assert ret == 0

        captured = capsys.readouterr()
        assert "[DRY RUN] Would fetch file links" in captured.out
        assert "GeoLocationUpdates_Pulse_17.1.1_20260211.zip" in captured.out


def test_cli_list_lines(capsys):
    args = [
        "--client-id", "test_id",
        "--client-secret", "test_secret",
        "list", "lines",
        "--family", "BIG-IP",
    ]

    mock_metadata = [
        ProductFamilyInfo(
            name="BIG-IP",
            product_lines=[
                ProductLineInfo(name="big-ip_v17.x", display_name="BIG-IP 17.x"),
                ProductLineInfo(name="big-ip_v16.x", display_name="BIG-IP 16.x"),
            ],
        )
    ]

    with patch("geodb_download.cli.MyF5Client") as mock_client_cls:
        client_instance = mock_client_cls.return_value
        client_instance.get_metadata.return_value = mock_metadata

        ret = main(args)
        assert ret == 0

        captured = capsys.readouterr()
        assert "big-ip_v17.x" in captured.out
        assert "big-ip_v16.x" in captured.out
