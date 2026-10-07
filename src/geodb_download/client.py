"""MyF5 API client for authentication and downloads management."""

from __future__ import annotations

import logging
import time
import urllib.parse
from typing import Any, Optional

import requests

from geodb_download.models import (
    FileLinksResponse,
    ProductFamilyInfo,
    VersionInfo,
)

logger = logging.getLogger(__name__)

DEFAULT_AUTH_URL = "https://idp.identity.f5.com/oauth/token"
STAGE_AUTH_URL = "https://identity.stage.f5networks.net/oauth/token"
DEFAULT_DOWNLOADS_API_URL = "https://api.software.downloads.f5.com"
DEFAULT_AUDIENCE = "api://ciam-api-myf5"
DEFAULT_SCOPE = "myf5_scope"


class MyF5Error(Exception):
    """Base exception for MyF5 API errors."""
    pass


class MyF5AuthError(MyF5Error):
    """Raised when authentication fails."""
    pass


class MyF5ApiError(MyF5Error):
    """Raised when an API request returns an error response."""
    def __init__(self, status_code: int, message: str, details: Any = None):
        super().__init__(f"API Error [{status_code}]: {message}")
        self.status_code = status_code
        self.details = details


class MyF5NotFoundError(MyF5ApiError):
    """Raised when a requested resource is not found (404)."""
    pass


class MyF5PayloadTooLargeError(MyF5ApiError):
    """Raised when the requested page or payload is too large (413)."""
    pass


class MyF5RateLimitError(MyF5ApiError):
    """Raised when rate limit is exceeded (429)."""
    pass


class MyF5Client:
    """Client for authenticating with Okta and accessing MyF5 Downloads API."""

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        auth_url: str = DEFAULT_AUTH_URL,
        api_base_url: str = DEFAULT_DOWNLOADS_API_URL,
        audience: str = DEFAULT_AUDIENCE,
        scope: str = DEFAULT_SCOPE,
        timeout: float = 30.0,
        session: Optional[requests.Session] = None,
    ):
        if not client_id or not client_secret:
            raise ValueError("Both client_id and client_secret are required for MyF5 authentication.")

        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self.auth_url = auth_url.rstrip("/")
        self.api_base_url = api_base_url.rstrip("/")
        self.audience = audience
        self.scope = scope
        self.timeout = timeout
        self.session = session or requests.Session()

        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

    def authenticate(self, force: bool = False) -> str:
        """Authenticate with Okta using OAuth2 client credentials grant.

        Uses HTTP Basic Authentication with client_id and client_secret in the
        Authorization header, as specified in the MyF5 OpenAPI definition.
        """
        now = time.time()
        if not force and self._access_token and now < self._token_expires_at:
            return self._access_token

        logger.debug("Requesting OAuth2 access token from %s", self.auth_url)
        data = {
            "grant_type": "client_credentials",
            "audience": self.audience,
            "scope": self.scope,
        }
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        try:
            resp = self.session.post(
                self.auth_url,
                data=data,
                headers=headers,
                auth=(self.client_id, self.client_secret),
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise MyF5AuthError(f"Network error during authentication: {e}") from e

        if resp.status_code != 200:
            err_msg = f"Authentication failed with HTTP {resp.status_code}: {resp.text}"
            logger.error(err_msg)
            raise MyF5AuthError(err_msg)

        try:
            token_data = resp.json()
        except ValueError as e:
            raise MyF5AuthError(f"Failed to parse authentication response as JSON: {resp.text}") from e

        access_token = token_data.get("access_token")
        if not access_token:
            raise MyF5AuthError(f"No access_token returned in auth response: {token_data}")

        expires_in = token_data.get("expires_in", 1800)
        try:
            expires_in_sec = int(expires_in)
        except (ValueError, TypeError):
            expires_in_sec = 1800

        # Safety margin of 60 seconds
        self._token_expires_at = now + max(60, expires_in_sec - 60)
        self._access_token = access_token
        logger.debug("Successfully obtained access token (expires in %d seconds)", expires_in_sec)
        return access_token

    def _get_auth_headers(self) -> dict[str, str]:
        token = self.authenticate()
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

    def _request(
        self,
        method: str,
        path_or_url: str,
        params: Optional[dict[str, Any]] = None,
        retry_on_401: bool = True,
    ) -> requests.Response:
        """Execute an authenticated API request with auto-refresh on 401."""
        if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
            url = path_or_url
        else:
            url = f"{self.api_base_url}/{path_or_url.lstrip('/')}"

        headers = self._get_auth_headers()
        logger.debug("%s %s (params: %s)", method, url, params)

        try:
            resp = self.session.request(
                method=method,
                url=url,
                params=params,
                headers=headers,
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            raise MyF5Error(f"Request failed to {url}: {e}") from e

        if resp.status_code == 401 and retry_on_401:
            logger.info("Access token expired or rejected (401). Refreshing token and retrying...")
            self.authenticate(force=True)
            return self._request(method, path_or_url, params=params, retry_on_401=False)

        if resp.status_code == 404:
            raise MyF5NotFoundError(404, f"Resource not found: {url}", resp.text)
        elif resp.status_code == 413:
            raise MyF5PayloadTooLargeError(413, f"Payload too large: {url}", resp.text)
        elif resp.status_code == 429:
            raise MyF5RateLimitError(429, "Rate limit exceeded (Too Many Requests)", resp.text)
        elif resp.status_code >= 400:
            raise MyF5ApiError(resp.status_code, f"API error: {resp.text}", resp.text)

        return resp

    def get_metadata(self) -> list[ProductFamilyInfo]:
        """Fetch Downloads metadata containing product families and lines.

        Endpoint: GET /v1/downloads-management/v1/downloads/metadata
        """
        path = "v1/downloads-management/v1/downloads/metadata"
        resp = self._request("GET", path)
        data = resp.json()

        # Schema structure: {"message": "...", "data": {"productFamilies": [...]}}
        root_data = data.get("data", {}) if isinstance(data, dict) else {}
        raw_families = root_data.get("productFamilies", [])
        if not raw_families and isinstance(data, dict) and "productFamilies" in data:
            raw_families = data.get("productFamilies", [])

        return [ProductFamilyInfo.from_dict(f) for f in raw_families if isinstance(f, dict)]

    def get_product_versions(
        self,
        product_family: str,
        product_line: str,
        page: int = 1,
        page_size: int = 10,
    ) -> list[VersionInfo]:
        """Fetch product versions, containers, and files for a product line.

        Endpoint: GET /v1/downloads-management/v1/downloads/product/{productFamily}/{productLine}
        """
        encoded_family = urllib.parse.quote(product_family, safe="")
        encoded_line = urllib.parse.quote(product_line, safe="")
        path = f"v1/downloads-management/v1/downloads/product/{encoded_family}/{encoded_line}"

        params = {
            "productFamily": product_family,
            "productLine": product_line,
            "page": page,
            "page_size": page_size,
        }

        resp = self._request("GET", path, params=params)
        data = resp.json()

        raw_versions = data.get("versions", []) if isinstance(data, dict) else []
        return [VersionInfo.from_dict(v) for v in raw_versions if isinstance(v, dict)]

    def get_all_product_versions(
        self,
        product_family: str,
        product_line: str,
        max_pages: int = 100,
        page_size: int = 10,
    ) -> list[VersionInfo]:
        """Fetch all product versions across all pages for a product line.

        Handles pagination and automatically reduces page_size if the server returns
        HTTP 413 (Payload Too Large).
        """
        all_versions: list[VersionInfo] = []
        seen_version_names: set[str] = set()
        current_page_size = page_size

        page = 1
        while page <= max_pages:
            logger.debug(
                "Fetching page %d of versions for %s/%s (page_size=%d)",
                page, product_family, product_line, current_page_size
            )
            try:
                versions = self.get_product_versions(
                    product_family=product_family,
                    product_line=product_line,
                    page=page,
                    page_size=current_page_size,
                )
            except MyF5PayloadTooLargeError:
                if current_page_size > 1:
                    new_size = max(1, current_page_size // 2)
                    logger.warning(
                        "Received 413 Payload Too Large for %s/%s at page_size=%d. Reducing page_size to %d and restarting from page 1...",
                        product_family, product_line, current_page_size, new_size
                    )
                    current_page_size = new_size
                    page = 1
                    all_versions.clear()
                    seen_version_names.clear()
                    continue
                raise

            if not versions:
                break

            # Check if all returned versions are already seen (to prevent infinite loop on static API pagination)
            new_found = False
            for v in versions:
                if v.version not in seen_version_names:
                    seen_version_names.add(v.version)
                    all_versions.append(v)
                    new_found = True

            if not new_found or len(versions) < current_page_size:
                break

            page += 1

        return all_versions

    def get_file_links(self, href_or_path: str) -> FileLinksResponse:
        """Fetch the pre-signed download URLs and checksums for a specific file.

        Endpoint: GET /v1/downloads-management/v1/downloads/product/{family}/{line}/{ver}/{lang}/{container}/{fileName}
        or relative href returned in the file metadata.
        """
        candidate_paths: list[str] = []

        clean_path = href_or_path.lstrip("/")

        # In openapi.json, the path is /v1/downloads-management/v1/...
        # But in file href examples it is /downloads-management/v1/...
        if clean_path.startswith("v1/"):
            candidate_paths.append(clean_path)
            candidate_paths.append(clean_path[3:])
        else:
            candidate_paths.append(f"v1/{clean_path}")
            candidate_paths.append(clean_path)

        last_error: Optional[Exception] = None
        for p in candidate_paths:
            try:
                resp = self._request("GET", p)
                return FileLinksResponse.from_dict(resp.json())
            except MyF5NotFoundError as e:
                last_error = e
                continue
            except Exception as e:
                last_error = e
                break

        if last_error:
            raise last_error

        raise MyF5NotFoundError(404, f"Failed to retrieve file links for {href_or_path}")
