"""List folders on the machine that will read them.

A browser file dialog names a folder on the machine running the browser.
Owlet may be opened from another machine, so the picker asks this process
which directories it can see.
"""

from __future__ import annotations

import os
import string
from dataclasses import dataclass
from pathlib import Path

from core.domain.errors import SourceNotFoundError


@dataclass(frozen=True, slots=True)
class FolderEntry:
    name: str
    path: str


@dataclass(frozen=True, slots=True)
class FolderListing:
    """`path` is empty on the Windows drive list, where nothing is chosen yet."""

    path: str
    parent: str | None
    entries: tuple[FolderEntry, ...]


def list_folders(path: str) -> FolderListing:
    """Child folders of `path`. An empty path is the drives, or `/`."""
    raw = path.strip()
    if not raw:
        if os.name == "nt":
            return _drives()
        return _children(Path("/"), parent=None)
    return _open(Path(raw).expanduser())


def _drives() -> FolderListing:
    entries = [
        FolderEntry(name=f"{letter}:\\", path=f"{letter}:\\")
        for letter in string.ascii_uppercase
        if Path(f"{letter}:\\").exists()
    ]
    return FolderListing(path="", parent=None, entries=tuple(entries))


def _open(folder: Path) -> FolderListing:
    try:
        resolved = folder.resolve()
        exists = resolved.exists()
        is_dir = resolved.is_dir()
    except OSError as exc:
        raise SourceNotFoundError(f"{folder} cannot be read") from exc
    if not exists:
        raise SourceNotFoundError(f"No folder at {folder}")
    if not is_dir:
        raise SourceNotFoundError(f"{folder} is a file, not a folder")
    return _children(resolved, parent=_parent(resolved))


def _parent(resolved: Path) -> str | None:
    parent = resolved.parent
    if parent != resolved:
        return str(parent)
    # A Windows drive root steps back to the drive list. `/` has nowhere above it.
    if os.name == "nt":
        return ""
    return None


def _children(folder: Path, *, parent: str | None) -> FolderListing:
    try:
        names = list(folder.iterdir())
    except OSError as exc:
        raise SourceNotFoundError(f"{folder} cannot be read") from exc
    entries: list[FolderEntry] = []
    for child in names:
        try:
            if not child.is_dir():
                continue
        except OSError:
            continue
        entries.append(FolderEntry(name=child.name or str(child), path=str(child)))
    entries.sort(key=lambda item: item.name.casefold())
    return FolderListing(path=str(folder), parent=parent, entries=tuple(entries))
