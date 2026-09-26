"""Open an already selected, canonical source without following replacements."""
from __future__ import annotations

import os
from pathlib import Path
import stat
from typing import BinaryIO


def open_regular_file(path: str | Path) -> BinaryIO:
    # Do not resolve here: doing so would approve a symlink substituted after
    # registration. Registration resolves the developer-selected path once.
    path = Path(path).expanduser().absolute()
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    fd = None
    if os.open in os.supports_dir_fd and hasattr(os, "O_NOFOLLOW"):
        directory = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
        try:
            for part in path.parts[1:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                os.close(directory)
                directory = child
            fd = os.open(path.name, flags | os.O_NOFOLLOW, dir_fd=directory)
        finally:
            os.close(directory)
    else:
        # Portable fallback rejects existing links and checks the opened file's
        # identity. Ancestor replacement races need OS isolation on platforms
        # without descriptor-relative, no-follow opens.
        for component in (*reversed(path.parents), path):
            if component.is_symlink():
                raise OSError("Selected source contains a symbolic link")
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode):
            raise OSError("Selected source is not a regular file")
        fd = os.open(path, flags)
        after = os.fstat(fd)
        if (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino):
            os.close(fd)
            raise OSError("Selected source changed while opening")
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("Selected source is not a regular file")
        return os.fdopen(fd, "rb")
    except BaseException:
        os.close(fd)
        raise
