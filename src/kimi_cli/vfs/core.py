from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Iterable


class VFS:
    """Virtual file system that overlays a virtual_root on top of a work_dir."""

    def __init__(self, virtual_root: Path, work_dir: Path) -> None:
        self.virtual_root = Path(virtual_root).resolve()
        self.work_dir = Path(work_dir).resolve()
        self._dirty_files: set[Path] = set()

    def _rel(self, path: Path) -> Path:
        """Return relative path from work_dir, raising if outside."""
        p = Path(path)
        if p.is_symlink():
            p = p.parent.resolve() / p.name
        else:
            p = p.resolve()
        try:
            rel = p.relative_to(self.work_dir)
        except ValueError:
            raise ValueError(f"Path {p} is not under work_dir {self.work_dir}")
        return rel

    def translate_path(self, path: Path) -> Path:
        """Return the current effective path for *path* (virtual if dirty, else original)."""
        rel = self._rel(path)
        if rel in self._dirty_files:
            return self.virtual_root / rel
        return self.work_dir / rel

    def get(self, path: Path, mark_dirty: bool = True) -> Path:
        """Retrieve *path* and optionally copy it into the virtual layer."""
        original = Path(path)
        p = original.resolve()
        rel = self._rel(original)

        if rel in self._dirty_files:
            return self.virtual_root / rel

        if not mark_dirty or not p.is_file():
            return original

        dest = self.virtual_root / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        data = p.read_bytes()
        dest.write_bytes(data)

        self._dirty_files.add(rel)

        return dest

    def is_dirty(self, path: Path) -> bool:
        """Check whether *path* is currently tracked as dirty."""
        return self._rel(path) in self._dirty_files


def merge(*vfs_instances: VFS) -> dict[Path, list[tuple[int, bytes]]]:
    """Detect conflicts across multiple VFS instances.

    Returns a mapping from relative path to a list of (vfs_index, content)
    for every path that appears in more than one VFS with differing content.
    """
    # Collect all dirty paths and their content per VFS
    all_paths: set[Path] = set()
    contents: dict[Path, dict[int, bytes]] = {}
    hashes: dict[Path, dict[int, str]] = {}

    for idx, vfs in enumerate(vfs_instances):
        for rel in vfs._dirty_files:
            all_paths.add(rel)
            src = vfs.virtual_root / rel
            data = src.read_bytes()
            h = hashlib.sha256(data).hexdigest()
            contents.setdefault(rel, {})[idx] = data
            hashes.setdefault(rel, {})[idx] = h

    conflicts: dict[Path, list[tuple[int, bytes]]] = {}
    for rel in all_paths:
        # Only consider paths present in >1 VFS
        idxs = list(contents[rel].keys())
        if len(idxs) < 2:
            continue
        # Check if all hashes are identical
        hs = list(hashes[rel].values())
        if len(set(hs)) == 1:
            continue
        conflicts[rel] = [(i, contents[rel][i]) for i in idxs]

    return conflicts
