"""Containment checks for filesystem paths that arrive from API clients.

Several outline-generation entry points accept a ``file_path`` that was produced
by an earlier upload step. Nothing stops a client from sending an arbitrary path
instead, so every such path must be confirmed to live under a directory this
application writes uploads to before it is opened or handed to a parser.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path
from typing import Iterable, List, Optional

logger = logging.getLogger(__name__)


class UnsafeFilePathError(ValueError):
    """Raised when a client-supplied path escapes the allowed upload roots."""


def _candidate_roots() -> Iterable[Path]:
    """Directories the app legitimately writes client-supplied files to."""
    from .config import app_config

    yield Path(tempfile.gettempdir())
    yield Path("temp").resolve()
    yield Path("uploads").resolve()

    upload_dir = getattr(app_config, "upload_dir", None)
    if upload_dir:
        yield Path(upload_dir).resolve()


def allowed_upload_roots() -> List[Path]:
    """Resolved, de-duplicated whitelist of upload roots."""
    roots: List[Path] = []
    for candidate in _candidate_roots():
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved not in roots:
            roots.append(resolved)
    return roots


def is_within_allowed_roots(file_path: str | os.PathLike[str]) -> bool:
    """True when ``file_path`` resolves inside one of the allowed roots."""
    try:
        resolved = Path(file_path).resolve()
    except (OSError, ValueError):
        return False

    for root in allowed_upload_roots():
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def validate_client_file_path(
    file_path: Optional[str],
    *,
    must_exist: bool = True,
) -> Path:
    """Validate a client-supplied path and return it resolved.

    Raises ``UnsafeFilePathError`` when the path is empty, escapes the allowed
    upload roots, is a symlink pointing outside them, or does not name a regular
    file. The message is deliberately generic so it cannot be used to probe the
    filesystem layout.
    """
    if not file_path or not str(file_path).strip():
        raise UnsafeFilePathError("File path is required")

    raw = str(file_path).strip()

    if "\x00" in raw:
        raise UnsafeFilePathError("Invalid file path")

    try:
        resolved = Path(raw).resolve()
    except (OSError, ValueError) as exc:
        raise UnsafeFilePathError("Invalid file path") from exc

    if not is_within_allowed_roots(resolved):
        logger.warning("Rejected out-of-tree file path from client: %r", raw)
        raise UnsafeFilePathError("File path is not an accessible upload location")

    if must_exist:
        if not resolved.exists():
            raise UnsafeFilePathError("File not found")
        if not resolved.is_file():
            raise UnsafeFilePathError("File path is not a regular file")

    return resolved


def sanitize_path_component(name: str, *, fallback: str = "file", max_length: int = 60) -> str:
    """Reduce arbitrary text to something safe to use as a single path segment.

    Used for names derived from user content (e.g. a presentation topic) that end
    up in filenames; ``C/C++`` or a Windows-reserved character would otherwise
    make ``open()`` fail.
    """
    if not name:
        return fallback

    reserved = '<>:"/\\|?*'
    cleaned_chars = []
    for char in str(name):
        if char in reserved or ord(char) < 32:
            cleaned_chars.append("_")
        else:
            cleaned_chars.append(char)

    cleaned = "".join(cleaned_chars).strip(" .")
    cleaned = cleaned[:max_length].strip(" .")
    return cleaned or fallback
