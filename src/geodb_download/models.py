"""Data models representing MyF5 Downloads API schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
import re


@dataclass
class FileMeta:
    """Metadata for a downloadable file including checksums and upload timestamp."""
    upload_date: Optional[str] = None
    sha256: Optional[str] = None
    md5: Optional[str] = None
    sha1: Optional[str] = None
    sha384: Optional[str] = None
    sha512: Optional[str] = None
    etag_aws: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Optional[dict[str, Any]]) -> FileMeta:
        if not data:
            return cls()
        return cls(
            upload_date=data.get("uploadDate"),
            sha256=data.get("sha256"),
            md5=data.get("md5"),
            sha1=data.get("sha1"),
            sha384=data.get("sha384"),
            sha512=data.get("sha512"),
            etag_aws=data.get("etagAws"),
        )


@dataclass
class FileInfo:
    """Represents a downloadable file within a container."""
    filename: str
    description: str = ""
    bytes: Optional[int] = None
    href: str = ""
    meta: FileMeta = field(default_factory=FileMeta)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FileInfo:
        raw_bytes = data.get("bytes")
        bytes_val = None
        if raw_bytes is not None:
            try:
                bytes_val = int(raw_bytes)
            except (ValueError, TypeError):
                pass
        return cls(
            filename=data.get("filename", ""),
            description=data.get("description", ""),
            bytes=bytes_val,
            href=data.get("href", ""),
            meta=FileMeta.from_dict(data.get("meta")),
        )


@dataclass
class ContainerInfo:
    """Represents a container / category (e.g., GeoLocationUpdates, Virtual Edition, Hotfix)."""
    container: str
    version: str = ""
    release_date: Optional[str] = None
    container_type: str = ""
    description: str = ""
    files: list[FileInfo] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ContainerInfo:
        files = [FileInfo.from_dict(f) for f in data.get("files", []) if isinstance(f, dict)]
        return cls(
            container=data.get("container", ""),
            version=data.get("version", ""),
            release_date=data.get("releaseDate"),
            container_type=data.get("type", ""),
            description=data.get("description", ""),
            files=files,
        )


@dataclass
class VersionInfo:
    """Represents a product version (e.g., 17.1.1, 16.1.4) containing multiple containers."""
    version: str
    release_date: Optional[str] = None
    containers: list[ContainerInfo] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> VersionInfo:
        containers = [
            ContainerInfo.from_dict(c)
            for c in data.get("containers", [])
            if isinstance(c, dict)
        ]
        return cls(
            version=data.get("version", ""),
            release_date=data.get("releaseDate"),
            containers=containers,
        )


@dataclass
class ProductLineInfo:
    """Represents a product line (e.g., big-ip_v17.x, big-ip_v16.x)."""
    name: str
    display_name: str = ""
    product_family: str = ""
    help_text: str = ""
    instructions: str = ""
    get_file_download_path_pattern: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProductLineInfo:
        return cls(
            name=data.get("name", ""),
            display_name=data.get("displayName", ""),
            product_family=data.get("productFamily", ""),
            help_text=data.get("helpText", ""),
            instructions=data.get("instructions", ""),
            get_file_download_path_pattern=data.get("getFileDownloadPathPattern", ""),
        )


@dataclass
class ProductFamilyInfo:
    """Represents a product family (e.g., BIG-IP, NGINX, BIG-IQ)."""
    name: str
    product_lines: list[ProductLineInfo] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProductFamilyInfo:
        product_lines = [
            ProductLineInfo.from_dict(pl)
            for pl in data.get("productLines", [])
            if isinstance(pl, dict)
        ]
        return cls(
            name=data.get("name", ""),
            product_lines=product_lines,
        )


@dataclass
class DownloadLinkInfo:
    """Pre-signed download link details."""
    href: str
    etag: str = ""
    hosting: str = ""
    location: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DownloadLinkInfo:
        return cls(
            href=data.get("href", ""),
            etag=data.get("etag", ""),
            hosting=data.get("hosting", ""),
            location=data.get("location", ""),
        )


@dataclass
class FileLinksResponse:
    """Response from the file paths API containing download links and metadata."""
    download_links: list[DownloadLinkInfo] = field(default_factory=list)
    filename: str = ""
    description: str = ""
    bytes: Optional[int] = None
    container: str = ""
    container_type: str = ""
    family: str = ""
    product: str = ""
    version: str = ""
    language: str = ""
    md5: str = ""
    meta: FileMeta = field(default_factory=FileMeta)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FileLinksResponse:
        raw_bytes = data.get("bytes")
        bytes_val = None
        if raw_bytes is not None:
            try:
                bytes_val = int(raw_bytes)
            except (ValueError, TypeError):
                pass
        links = [
            DownloadLinkInfo.from_dict(dl)
            for dl in data.get("downloadLinks", [])
            if isinstance(dl, dict)
        ]
        return cls(
            download_links=links,
            filename=data.get("filename", ""),
            description=data.get("description", ""),
            bytes=bytes_val,
            container=data.get("container", ""),
            container_type=data.get("containerType", ""),
            family=data.get("family", ""),
            product=data.get("product", ""),
            version=data.get("version", ""),
            language=data.get("language", ""),
            md5=data.get("md5", ""),
            meta=FileMeta.from_dict(data.get("meta")),
        )


@dataclass
class PulseMatch:
    """Represents a matched GeoLocationUpdates_Pulse file for a product version."""
    product_family: str
    product_line: str
    product_version: str
    container_name: str
    file_info: FileInfo
    container_release_date: Optional[str] = None
    parsed_date: datetime = field(default_factory=lambda: datetime.min)

    @property
    def filename(self) -> str:
        return self.file_info.filename

    @property
    def href(self) -> str:
        return self.file_info.href

    @property
    def bytes(self) -> Optional[int]:
        return self.file_info.bytes

    @property
    def sha256(self) -> Optional[str]:
        return self.file_info.meta.sha256

    @property
    def md5(self) -> Optional[str]:
        return self.file_info.meta.md5
