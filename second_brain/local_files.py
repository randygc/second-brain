"""Owner-only local artifacts shared by authentication and reporting."""

import os
from pathlib import Path
import tempfile


def private_write(path: Path, content: str) -> None:
    """Replace a file atomically, without following a target symlink."""
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".second-brain-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(content)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
