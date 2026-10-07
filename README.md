# MyF5 GeoLocationUpdates_Pulse Downloader

A Python tool designed to automate the discovery and download of the latest **GeoLocationUpdates_Pulse** database packages from the MyF5 Downloads API based on the OpenAPI specification.

---

## Hierarchy & Navigation

The MyF5 Downloads API organizes software according to the following tree structure:

```
Product Family (e.g., BIG-IP, NGINX, BIG-IQ)
  └── Product Line (e.g., big-ip_v21.x, big-ip_v17.x, big-ip_v16.x)
        └── Product Version (e.g., 21.1.0, 21.0.0, 17.1.1, 16.1.4)
              └── Container / Category (e.g., GeoLocationUpdates, Virtual Edition, Hotfix)
                    └── Download File (e.g., GeoLocationUpdates_Pulse)
```

Because GeoLocation database formats vary between BIG-IP versions, there is a distinct `GeoLocationUpdates_Pulse` release per product version. This tool can target a specific version, pick the latest version automatically, or download the latest Pulse package for every version.

---

## Features

- **OAuth 2.0 Authentication**: Seamless token acquisition and auto-refresh using Okta client credentials with HTTP Basic Auth against `https://idp.identity.f5.com/oauth/token` (or stage).
- **Automated Hierarchy Discovery**:
  - `GET /v1/downloads-management/v1/downloads/metadata`: Discovers families and product lines.
  - `GET /v1/downloads-management/v1/downloads/product/{family}/{line}`: Queries all product versions and containers with automatic pagination.
  - `GET /v1/downloads-management/v1/downloads/product/.../{fileName}`: Fetches region-specific pre-signed AWS/CloudFront download links.
- **Intelligent "Last File" Resolution**:
  - Compares timestamps from `meta.uploadDate`, `releaseDate`, and embedded file dates (`YYYYMMDD`).
  - Supports semantic version sorting (`21.1.0` > `21.0.0` > `17.1.1` > `16.1.4`).
- **Flexible Product Line Shortcuts & Multi-Line Downloads**:
  - Shorthand line names like `21.x` or `17.x` automatically resolve to `big-ip_v21.x`, `big-ip_v17.x`.
  - Download across multiple product lines in a single command using comma separation (e.g., `--product-line 17.x,21.x`).
- **Reliable Download & Integrity Verification**:
  - Chunked streaming download with live progress bar (download speed, percentage, ETA).
  - Validates `SHA-256` (both hexadecimal and base64 encodings) and `MD5` checksums against API metadata before finalizing the file.
  - Atomic writing via `.part` files prevents corrupted or incomplete downloads.
  - Skips already-downloaded files if the checksum matches.

---

## Installation

### Prerequisites
- Python 3.12+
- Git
- `uv` (recommended) or standard `pip`

### 1. Clone the Repository
```bash
git clone git@github.com:SalesAmerSP/geodb-downloader.git
cd geodb-downloader
```

### 2. Set Up Environment & Install Dependencies

Choose either **`uv`** (recommended) or standard **Python `venv` + `pip`**:

#### Option A: Using `uv` (Recommended)
`uv` automatically manages the virtual environment and installs pinned dependencies:
```bash
# Automatically creates .venv and installs all dependencies
uv sync

# (Optional) Run commands directly through uv:
uv run python download_geodb.py --help
```

#### Option B: Using Standard Virtual Environment (`venv` + `pip`)
```bash
# 1. Create a virtual environment
python3 -m venv .venv

# 2. Activate the virtual environment
# On macOS / Linux:
source .venv/bin/activate
# On Windows (cmd.exe):
# .venv\Scripts\activate.bat
# On Windows (PowerShell):
# .venv\Scripts\Activate.ps1

# 3. Install dependencies
pip install -r requirements.txt

# (Optional) Install development dependencies for running tests:
pip install -r requirements-dev.txt

# (Optional) Install the package in editable mode for the 'geodb-download' CLI entry point:
pip install -e .
```

---

## Configuration

Obtain your API credentials (`client_id` and `client_secret`) by requesting an API key from the MyF5 portal.

You can provide credentials in three ways:

1. **Environment Variables**:
   ```bash
   export MYF5_CLIENT_ID="your_client_id"
   export MYF5_CLIENT_SECRET="your_client_secret"
   ```

2. **`.env` File** (copy from `.env.example`):
   ```ini
   MYF5_CLIENT_ID=your_client_id
   MYF5_CLIENT_SECRET=your_client_secret
   ```

3. **CLI Arguments**:
   ```bash
   python download_geodb.py --client-id <ID> --client-secret <SECRET> ...
   ```

---

## CLI Usage

You can run the tool either via `python download_geodb.py` or `geodb-download`.

> **Note on Product Lines**: You can use convenient shorthand names such as `21.x` or `17.x` instead of typing `big-ip_v21.x` or `big-ip_v17.x`.

### 1. Download for Product Line 21.x
Download the latest `GeoLocationUpdates_Pulse` for product line `21.x` (defaults to the newest version, `21.1.0`):
```bash
python download_geodb.py --product-line 21.x
```

Or target a specific version like `21.0.0` or `21.1.0`:
```bash
python download_geodb.py --product-line 21.x --version 21.0.0
python download_geodb.py --product-line 21.x --version 21.1.0
```

### 2. Download for a Specific BIG-IP 17.x Version
Download the latest `GeoLocationUpdates_Pulse` for BIG-IP version `17.1.1`:
```bash
python download_geodb.py --product-line 17.x --version 17.1.1
```

### 3. Download the Last Pulse File for All Versions in a Product Line
Download the latest `GeoLocationUpdates_Pulse` for **every** product version in `21.x` (both `21.1.0` and `21.0.0`):
```bash
python download_geodb.py --product-line 21.x --all-versions --organize-by-version
```
Files will be saved cleanly into `./downloads/<version>/GeoLocationUpdates_Pulse_...`.

### 4. Download Across Multiple Product Lines (e.g. 17.x and 21.x)
Pass comma-separated product lines to download across families or major releases at once:
```bash
python download_geodb.py --product-line 17.x,21.x --all-versions --organize-by-version
```

### 5. Dry Run (Preview without downloading)
See what files match without downloading them:
```bash
python download_geodb.py --product-line 21.x --all-versions --dry-run
python download_geodb.py --product-line 17.x,21.x --all-versions --dry-run
```

### 6. Listing Available Metadata & Files
List available product lines:
```bash
python download_geodb.py list lines --family BIG-IP
```

List available versions for a line:
```bash
python download_geodb.py list versions --product-line 21.x
```

List all available `GeoLocationUpdates_Pulse` files across versions:
```bash
python download_geodb.py list pulse --product-line 21.x
```

### 7. Custom Directory and Preferences
```bash
python download_geodb.py \
  --product-line 21.x \
  --version 21.1.0 \
  --output-dir /var/shared/geodb \
  --location "USA - WEST COAST" \
  --overwrite
```

---

## Python API Usage

The package can also be imported into your own Python applications:

```python
from geodb_download.client import MyF5Client
from geodb_download.downloader import FileDownloader
from geodb_download.finder import GeoDBFinder

# 1. Initialize client
client = MyF5Client(
    client_id="YOUR_CLIENT_ID",
    client_secret="YOUR_CLIENT_SECRET",
)

# 2. Fetch versions and containers
versions = client.get_all_product_versions("BIG-IP", "big-ip_v17.x")

# 3. Find the latest Pulse file for version 17.1.1
finder = GeoDBFinder()
v17_1_1 = next(v for v in versions if v.version == "17.1.1")
match = finder.find_latest_for_version(v17_1_1, "BIG-IP", "big-ip_v17.x")

if match:
    print(f"Found Pulse file: {match.filename} (Date: {match.parsed_date})")

    # 4. Fetch pre-signed download link
    file_links = client.get_file_links(match.href)

    # 5. Download and verify checksum
    downloader = FileDownloader()
    saved_path = downloader.download(
        links_response=file_links,
        dest_dir="./downloads",
        verify_checksum=True,
    )
    print(f"Downloaded to {saved_path}")
```

---

## Running Unit Tests

Run the test suite using `pytest`:
```bash
uv run pytest -v
```
