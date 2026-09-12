"""Bounded raster staging and exclusive, scope-limited asset finalisation."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from io import BytesIO
import os
from pathlib import Path
import re
import secrets
import stat
import warnings
import zlib

from ..config_wizard.saving import SaveError

MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 4 * 1024 * 1024
MAX_UPLOADS = 16
MAX_SIDE = 2048
MAX_PIXELS = 2 * 1024 * 1024


def strip_png_metadata(raw):
    """Discard ancillary chunks before Pillow can inflate compressed metadata."""
    if not raw.startswith(b"\x89PNG\r\n\x1a\n"):
        return raw
    output = bytearray(raw[:8])
    offset = 8
    image_data = False
    for count in range(256):
        if offset + 12 > len(raw):
            break
        length = int.from_bytes(raw[offset : offset + 4], "big")
        end = offset + 12 + length
        if end > len(raw):
            break
        kind = raw[offset + 4 : offset + 8]
        if (count == 0 and (kind != b"IHDR" or length != 13)) or (
            count > 0 and kind == b"IHDR"
        ):
            raise SaveError("Invalid PNG header.")
        if kind == b"IDAT":
            image_data = True
        payload = raw[offset + 8 : end - 4]
        if zlib.crc32(kind + payload) != int.from_bytes(raw[end - 4 : end], "big"):
            break
        if kind in (b"acTL", b"fcTL", b"fdAT"):
            raise SaveError("Animated images are not accepted.")
        if kind in (b"IHDR", b"PLTE", b"IDAT", b"IEND", b"tRNS"):
            output.extend(raw[offset:end])
        elif not kind or not (kind[0] & 32):
            raise SaveError("Unsupported PNG structure.")
        if kind == b"IEND":
            if end != len(raw) or length != 0 or not image_data:
                raise SaveError("Unexpected data after PNG image.")
            return bytes(output)
        offset = end
    raise SaveError("Malformed PNG or too many image chunks.")


def raster(raw):
    from PIL import Image

    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise SaveError("Images must be at most 2 MiB.")

    raw = strip_png_metadata(raw)

    class Output(BytesIO):
        def write(self, data):
            if self.tell() + len(data) > MAX_IMAGE_BYTES:
                raise SaveError(
                    "Decoded image is too large to store; use a smaller image."
                )
            return super().write(data)

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(raw), formats=["PNG", "JPEG"]) as source:
                width, height = source.size
                if (
                    width > MAX_SIDE
                    or height > MAX_SIDE
                    or width * height > MAX_PIXELS
                    or getattr(source, "n_frames", 1) != 1
                ):
                    raise SaveError(
                        "Use a still PNG/JPEG, at most 2048 per side and 2 megapixels."
                    )
                source.load()
                with source.convert("RGBA") as decoded:
                    decoded.info.clear()
                    output = Output()
                    decoded.save(output, format="PNG")
                    return output.getvalue()
    except SaveError:
        raise
    except Exception:
        raise SaveError(
            "Use a valid still PNG or JPEG. SVG, HTML and animated images are not accepted."
        ) from None


def safe_directory(base, value):
    base = base.resolve()
    root = Path(value).expanduser()
    root = root if root.is_absolute() else base / root
    if ".." in root.parts or root == base or not root.is_relative_to(base):
        raise SaveError("Choose an asset directory inside the config folder.")
    current = base
    for part in root.relative_to(base).parts:
        current = current / part
        if current.is_symlink() or (current.exists() and not current.is_dir()):
            raise SaveError("Asset directories must not be symlinks or files.")
    if len(root.relative_to(base).as_posix()) > 512:
        raise SaveError("Asset directory path is too long.")
    if not root.parent.is_dir():
        raise SaveError("The asset directory parent must already exist.")
    return root


@dataclass
class Transaction:
    commit: bool = False


class Images:
    def __init__(self, base, directory):
        self.base = base.resolve()
        self.root = safe_directory(self.base, directory)
        self.staged = {}
        self.uploads = 0

    def stage(self, key, raw, filename):
        if self.uploads >= MAX_UPLOADS:
            raise SaveError(
                "Session upload limit reached. Cancel and reopen to continue."
            )
        if (
            not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9_. -]{0,99}\.(?:png|jpg|jpeg)",
                filename,
                flags=re.I,
            )
            or ".." in filename
        ):
            raise SaveError("Use a simple PNG/JPEG filename without directories.")
        image = raster(raw)
        if (
            sum(len(item[1]) for k, item in self.staged.items() if k != key)
            + len(image)
            > MAX_TOTAL_BYTES
        ):
            raise SaveError("Staged images exceed the 4 MiB session budget.")
        name = "plotsrv-" + secrets.token_hex(16) + ".png"
        self.staged[key] = (name, image)
        self.uploads += 1
        return (self.root.relative_to(self.base) / name).as_posix()

    @contextmanager
    def directory(self, *, create=False):
        """Walk every component with O_NOFOLLOW, retaining directory capabilities."""
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        current = os.open(self.base.anchor, flags)
        try:
            for part in self.base.parts[1:]:
                child = os.open(part, flags, dir_fd=current)
                os.close(current)
                current = child
        except BaseException:
            os.close(current)
            raise
        parent = None
        created = False
        parts = self.root.relative_to(self.base).parts
        try:
            for index, part in enumerate(parts):
                if index == len(parts) - 1 and create:
                    try:
                        os.mkdir(part, mode=0o700, dir_fd=current)
                        created = True
                    except FileExistsError:
                        pass
                child = os.open(part, flags, dir_fd=current)
                if index == len(parts) - 1:
                    parent = current
                else:
                    os.close(current)
                current = child
            yield current, parent, parts[-1], created
        finally:
            os.close(current)
            if parent is not None:
                os.close(parent)

    def existing(self, value):
        # Preview only configured images already inside the operator-approved root.
        if (
            not isinstance(value, str)
            or not value
            or value.startswith(("/static/", "/assets/", "http:", "https:"))
        ):
            return None
        path = Path(value)
        path = path if path.is_absolute() else self.base / path
        safe_directory(self.base, str(self.root))
        if path.parent != self.root or path.is_symlink():
            return None
        try:
            with self.directory() as (root_fd, _, _, _):
                fd = os.open(
                    path.name,
                    os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW,
                    dir_fd=root_fd,
                )
                with os.fdopen(fd, "rb") as stream:
                    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                        return None
                    raw = stream.read(MAX_IMAGE_BYTES + 1)
            return raster(raw)
        except (OSError, SaveError):
            return None

    @contextmanager
    def finalise(self):
        transaction = Transaction()
        if not self.staged:
            yield transaction
            return
        safe_directory(self.base, str(self.root))
        with self.directory(create=True) as (fd, parent, basename, created_dir):
            written = []
            try:
                for name, raw in self.staged.values():
                    file_fd = os.open(
                        name,
                        os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW,
                        0o600,
                        dir_fd=fd,
                    )
                    identity = os.fstat(file_fd)
                    written.append((name, identity.st_ino))
                    with os.fdopen(file_fd, "wb") as stream:
                        stream.write(raw)
                        stream.flush()
                        os.fsync(stream.fileno())
                if (
                    os.stat(basename, dir_fd=parent, follow_symlinks=False).st_ino
                    != os.fstat(fd).st_ino
                ):
                    raise SaveError("Asset directory changed while saving.")
                yield transaction
            finally:
                if not transaction.commit:
                    for name, inode in written:
                        try:
                            if (
                                os.stat(name, dir_fd=fd, follow_symlinks=False).st_ino
                                == inode
                            ):
                                os.unlink(name, dir_fd=fd)
                        except OSError:
                            pass
                    if created_dir:
                        try:
                            if (
                                os.stat(
                                    basename, dir_fd=parent, follow_symlinks=False
                                ).st_ino
                                == os.fstat(fd).st_ino
                            ):
                                os.rmdir(basename, dir_fd=parent)
                        except OSError:
                            pass

    def clear(self):
        self.staged.clear()
