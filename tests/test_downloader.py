"""Tests for FileDownloader and checksum verification."""

import base64
import hashlib
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
import requests

from geodb_download.downloader import (
    ChecksumMismatchError,
    FileDownloader,
    verify_file_hashes,
)
from geodb_download.models import DownloadLinkInfo, FileLinksResponse, FileMeta


def test_verify_file_hashes(tmp_path: Path):
    test_file = tmp_path / "sample.bin"
    content = b"MyF5 GeoLocationUpdates Pulse test binary content"
    test_file.write_bytes(content)

    expected_sha256_hex = hashlib.sha256(content).hexdigest()
    expected_sha256_b64 = base64.b64encode(hashlib.sha256(content).digest()).decode("ascii")
    expected_md5 = hashlib.md5(content).hexdigest()

    # Matches hex
    assert verify_file_hashes(test_file, expected_sha256=expected_sha256_hex)
    # Matches base64
    assert verify_file_hashes(test_file, expected_sha256=expected_sha256_b64)
    # Matches md5
    assert verify_file_hashes(test_file, expected_md5=expected_md5)
    # Bad hash fails
    assert not verify_file_hashes(test_file, expected_sha256="badhash")


def test_download_success(tmp_path: Path):
    downloader = FileDownloader()

    content = b"Binary GeoLocation updates data chunk 1 2 3"
    sha256_hex = hashlib.sha256(content).hexdigest()
    md5_hex = hashlib.md5(content).hexdigest()

    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Length": str(len(content))}
    mock_resp.iter_content.return_value = [content]

    links_response = FileLinksResponse(
        download_links=[
            DownloadLinkInfo(
                href="https://signed.cloudfront.net/Pulse.zip",
                location="USA - WEST COAST",
            )
        ],
        filename="GeoLocationUpdates_Pulse.zip",
        bytes=len(content),
        md5=md5_hex,
        meta=FileMeta(sha256=sha256_hex),
    )

    with patch.object(downloader.session, "get", return_value=mock_resp):
        dest = downloader.download(
            links_response=links_response,
            dest_dir=tmp_path,
            show_progress=False,
        )

        assert dest.exists()
        assert dest.read_bytes() == content


def test_download_checksum_mismatch(tmp_path: Path):
    downloader = FileDownloader()

    content = b"Tampered data"

    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Length": str(len(content))}
    mock_resp.iter_content.return_value = [content]

    links_response = FileLinksResponse(
        download_links=[
            DownloadLinkInfo(
                href="https://signed.cloudfront.net/Pulse.zip",
                location="USA - WEST COAST",
            )
        ],
        filename="GeoLocationUpdates_Pulse.zip",
        bytes=len(content),
        meta=FileMeta(sha256="expected_different_sha256_hash"),
    )

    with patch.object(downloader.session, "get", return_value=mock_resp):
        with pytest.raises(ChecksumMismatchError):
            downloader.download(
                links_response=links_response,
                dest_dir=tmp_path,
                show_progress=False,
            )

        # Ensure corrupted or part file was removed
        assert not (tmp_path / "GeoLocationUpdates_Pulse.zip").exists()
        assert not (tmp_path / "GeoLocationUpdates_Pulse.zip.part").exists()
