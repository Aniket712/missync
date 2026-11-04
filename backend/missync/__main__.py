"""`python -m missync` (same as the `missync` command): serve the app, or run `analyze` from the command line."""
from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
