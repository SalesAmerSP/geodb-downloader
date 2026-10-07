"""Allow running the package directly via `python -m geodb_download`."""

import sys
from geodb_download.cli import main

if __name__ == "__main__":
    sys.exit(main())
