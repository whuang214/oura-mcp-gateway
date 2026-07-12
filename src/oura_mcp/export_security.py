"""Path validation for sensitive local staging exports."""

from __future__ import annotations

import os
import stat
from pathlib import Path


def private_output_path(raw: Path, *, project_root: Path | None = None) -> Path:
    root = (project_root or Path.cwd()).resolve()
    private_root = Path(os.path.abspath(root / ".private"))
    lexical = Path(raw) if raw.is_absolute() else root / raw
    lexical = Path(os.path.abspath(lexical))
    try:
        relative = lexical.relative_to(private_root)
    except ValueError as exc:
        raise ValueError("--output must be inside the project's ignored .private directory") from exc
    if not relative.parts or lexical.suffix.casefold() != ".json":
        raise ValueError("--output must name a JSON file inside .private")

    current = private_root
    directories = [current]
    for part in relative.parts[:-1]:
        current = current / part
        directories.append(current)
    for current in directories:
        if not current.exists():
            continue
        details = current.lstat()
        is_reparse_point = bool(
            getattr(details, "st_file_attributes", 0)
            & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
        )
        if stat.S_ISLNK(details.st_mode) or is_reparse_point:
            raise ValueError("--output must not traverse a symlink or reparse point")
    return lexical
