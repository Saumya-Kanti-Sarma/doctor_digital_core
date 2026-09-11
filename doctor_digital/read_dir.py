"""
doctor_digital.read_dir
=======================
Recursively reads a directory and returns its complete folder/file structure
as a nested dictionary tree.

Public API
----------
    read_dir(path) -> dict
"""

import os
from pathlib import Path


def read_dir(path: str) -> dict:
    """
    Recursively walk *path* and return the full folder structure as a tree.

    Each node is a dict with:

        {
            "name"     : str,          # file or folder name
            "path"     : str,          # absolute path
            "type"     : "dir" | "file",
            "size"     : int | None,   # bytes for files, None for dirs
            "children" : list | None,  # list of child nodes (dirs only)
            "error"    : str | None,   # set if the entry could not be read
        }

    Parameters
    ----------
    path : str
        Root path to start the traversal from.

    Returns
    -------
    dict
        A single root node containing the full tree.

    Raises
    ------
    FileNotFoundError
        If *path* does not exist.
    NotADirectoryError
        If *path* is not a directory.

    Example
    -------
        from doctor_digital import read_dir

        tree = read_dir("E:\\")
        print(tree["name"])           # e.g. "E:\\"
        print(tree["children"][0])    # first child node
    """
    root = Path(path).resolve()

    if not root.exists():
        raise FileNotFoundError(f"Path does not exist: {root}")

    if not root.is_dir():
        raise NotADirectoryError(f"Path is not a directory: {root}")

    return _build_node(root)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_node(p: Path) -> dict:
    """Return a tree node for *p* (file or directory)."""
    node = {
        "name": p.name or str(p),   # drive root (e.g. "E:\") has no name component
        "path": str(p),
        "type": None,
        "size": None,
        "children": None,
        "error": None,
    }

    try:
        if p.is_dir():
            node["type"] = "dir"
            node["children"] = _read_children(p)
        else:
            node["type"] = "file"
            node["size"] = _safe_size(p)
    except PermissionError as exc:
        node["type"] = "dir" if p.is_dir() else "file"
        node["error"] = f"PermissionError: {exc}"

    return node


def _read_children(p: Path) -> list:
    """Return sorted child nodes for directory *p*."""
    children = []
    try:
        entries = sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
    except PermissionError as exc:
        return [{"name": "?", "path": str(p), "type": None,
                 "size": None, "children": None,
                 "error": f"PermissionError: {exc}"}]

    for entry in entries:
        children.append(_build_node(entry))

    return children


def _safe_size(p: Path) -> int | None:
    """Return file size in bytes, or None if it cannot be read."""
    try:
        return p.stat().st_size
    except OSError:
        return None
