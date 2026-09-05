"""news-radar: a self-hosted news radar.

Fetch -> filter -> rank -> store -> render -> notify. Layered one way; see
docs/memory-ai/architecture/module-layout.md for what may import what.
"""

from __future__ import annotations

from pathlib import Path

# The repository root in a checkout, /app in the image - both hold VERSION next
# to src/. Read rather than hardcoded: release.py owns that file, and a second
# copy of the number here would drift the first time someone forgets.
_VERSION_FILE = Path(__file__).resolve().parent.parent.parent / "VERSION"

try:
    __version__ = _VERSION_FILE.read_text(encoding="utf-8").strip() or "0.0.0"
except OSError:
    # Installed some other way, or VERSION left out of an image. The User-Agent
    # stays well-formed either way, which is what the version is for here.
    __version__ = "0.0.0"

__all__ = ["__version__"]
