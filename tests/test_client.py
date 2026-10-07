"""Tests for MyF5Client and OAuth2 authentication flow."""

from unittest.mock import MagicMock, patch
import pytest
import requests

from geodb_download.client import (
    MyF5AuthError,
    MyF5Client,
    MyF5NotFoundError,
)


def test_client_init_requires_credentials():
    with pytest.raises(ValueError):
        MyF5Client(client_id="", client_secret="secret")
    with pytest.raises(ValueError):
        MyF5Client(client_id="id", client_secret="")


def test_client_authenticate_success():
    client = MyF5Client(client_id="test_id", client_secret="test_secret")

    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "access_token": "mock_jwt_token_12345",
        "token_type": "Bearer",
        "expires_in": 1800,
        "scope": "myf5_scope",
    }

    with patch.object(client.session, "post", return_value=mock_resp) as mock_post:
        token = client.authenticate()
        assert token == "mock_jwt_token_12345"

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert args[0] == "https://idp.identity.f5.com/oauth/token"
        assert kwargs["auth"] == ("test_id", "test_secret")
        assert kwargs["data"] == {
            "grant_type": "client_credentials",
            "audience": "api://ciam-api-myf5",
            "scope": "myf5_scope",
        }

        # Second call within expiry should use cached token
        token2 = client.authenticate()
        assert token2 == "mock_jwt_token_12345"
        assert mock_post.call_count == 1


def test_client_authenticate_failure():
    client = MyF5Client(client_id="bad_id", client_secret="bad_secret")

    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 401
    mock_resp.text = '{"error": "invalid_client"}'

    with patch.object(client.session, "post", return_value=mock_resp):
        with pytest.raises(MyF5AuthError) as exc_info:
            client.authenticate()
        assert "401" in str(exc_info.value)


def test_get_metadata():
    client = MyF5Client(client_id="id", client_secret="secret")
    client._access_token = "token123"
    client._token_expires_at = 9999999999.0

    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "message": "Downloads metadata retrieved",
        "isError": False,
        "data": {
            "productFamilies": [
                {
                    "name": "BIG-IP",
                    "productLines": [
                        {
                            "name": "big-ip_v17.x",
                            "displayName": "BIG-IP v17.x",
                            "productFamily": "BIG-IP",
                        }
                    ],
                }
            ]
        },
    }

    with patch.object(client.session, "request", return_value=mock_resp) as mock_req:
        metadata = client.get_metadata()
        assert len(metadata) == 1
        assert metadata[0].name == "BIG-IP"
        assert len(metadata[0].product_lines) == 1
        assert metadata[0].product_lines[0].name == "big-ip_v17.x"

        # Verify Authorization header
        _, kwargs = mock_req.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer token123"


def test_get_product_versions_pagination():
    client = MyF5Client(client_id="id", client_secret="secret")
    client._access_token = "token123"
    client._token_expires_at = 9999999999.0

    # Page 1 returns version 17.1.1
    page1 = MagicMock(spec=requests.Response)
    page1.status_code = 200
    page1.json.return_value = {
        "family": "BIG-IP",
        "product": "big-ip_v17.x",
        "versions": [{"version": "17.1.1", "containers": []}],
    }

    # Page 2 returns version 17.1.0
    page2 = MagicMock(spec=requests.Response)
    page2.status_code = 200
    page2.json.return_value = {
        "family": "BIG-IP",
        "product": "big-ip_v17.x",
        "versions": [{"version": "17.1.0", "containers": []}],
    }

    # Page 3 returns empty list
    page3 = MagicMock(spec=requests.Response)
    page3.status_code = 200
    page3.json.return_value = {
        "family": "BIG-IP",
        "product": "big-ip_v17.x",
        "versions": [],
    }

    with patch.object(client.session, "request", side_effect=[page1, page2, page3]):
        # page_size=1 so it requests page 2 then page 3
        versions = client.get_all_product_versions("BIG-IP", "big-ip_v17.x", page_size=1)
        assert len(versions) == 2
        assert versions[0].version == "17.1.1"
        assert versions[1].version == "17.1.0"


def test_get_file_links():
    client = MyF5Client(client_id="id", client_secret="secret")
    client._access_token = "token123"
    client._token_expires_at = 9999999999.0

    mock_resp = MagicMock(spec=requests.Response)
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "downloadLinks": [
            {
                "etag": "e0932c11",
                "hosting": "AWS",
                "href": "https://d2dbiffnp4d388.cloudfront.net/Pulse.zip?signed=1",
                "location": "USA - WEST COAST",
            }
        ],
        "filename": "GeoLocationUpdates_Pulse.zip",
        "bytes": "12345678",
        "md5": "6caf3e193cab61de3386e02afe64b7b0",
        "meta": {
          "sha256": "99cea46bc5a2bc526beb53b2fcd983ed007dfbc93220201b62ad4b6f6ea152fa"
        }
    }

    with patch.object(client.session, "request", return_value=mock_resp):
        res = client.get_file_links("/downloads-management/v1/downloads/product/BIG-IP/big-ip_v17.x/17.1.1/english/GeoLocationUpdates/GeoLocationUpdates_Pulse.zip")
        assert res.filename == "GeoLocationUpdates_Pulse.zip"
        assert len(res.download_links) == 1
        assert "cloudfront.net" in res.download_links[0].href
        assert res.meta.sha256 == "99cea46bc5a2bc526beb53b2fcd983ed007dfbc93220201b62ad4b6f6ea152fa"


def test_get_product_versions_413_retry():
    client = MyF5Client(client_id="id", client_secret="secret")
    client._access_token = "token123"
    client._token_expires_at = 9999999999.0

    # 413 response on initial request
    resp_413 = MagicMock(spec=requests.Response)
    resp_413.status_code = 413
    resp_413.text = "Request Entity Too Large"

    # Success response on reduced page size
    resp_ok = MagicMock(spec=requests.Response)
    resp_ok.status_code = 200
    resp_ok.json.return_value = {
        "family": "BIG-IP",
        "product": "big-ip_v15.x",
        "versions": [{"version": "15.1.10", "containers": []}],
    }

    # Empty response terminating pagination
    resp_empty = MagicMock(spec=requests.Response)
    resp_empty.status_code = 200
    resp_empty.json.return_value = {
        "family": "BIG-IP",
        "product": "big-ip_v15.x",
        "versions": [],
    }

    with patch.object(client.session, "request", side_effect=[resp_413, resp_ok, resp_empty]):
        versions = client.get_all_product_versions("BIG-IP", "big-ip_v15.x", page_size=10)
        assert len(versions) == 1
        assert versions[0].version == "15.1.10"
