#!/usr/bin/env python3
"""Standalone executable script to download the latest GeoLocationUpdates_Pulse from MyF5 API.

Usage:
    python download_geodb.py --help
    python download_geodb.py --product-line big-ip_v17.x --version 17.1.1
    python download_geodb.py --product-line big-ip_v17.x --all-versions
    python download_geodb.py list versions --product-line big-ip_v17.x
    python download_geodb.py list pulse --product-line big-ip_v17.x
"""

import os
import sys

# Ensure src/ is in python path
src_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from geodb_download.cli import main

if __name__ == "__main__":
    sys.exit(main())
