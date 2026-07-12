from __future__ import annotations

from pathlib import Path

import pytest

from oura_mcp.export_security import private_output_path


def test_staging_export_requires_json_inside_private_directory(tmp_path: Path) -> None:
    assert private_output_path(
        Path(".private/staging.json"), project_root=tmp_path
    ) == tmp_path / ".private" / "staging.json"

    with pytest.raises(ValueError, match="inside"):
        private_output_path(Path("staging.json"), project_root=tmp_path)
    with pytest.raises(ValueError, match="JSON"):
        private_output_path(Path(".private/staging.txt"), project_root=tmp_path)


def test_staging_export_rejects_private_directory_symlink(
    tmp_path: Path,
) -> None:
    target = tmp_path / "elsewhere"
    target.mkdir()
    private = tmp_path / ".private"
    try:
        private.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("Creating a directory symlink is unavailable on this platform")
    with pytest.raises(ValueError, match="symlink|reparse"):
        private_output_path(Path(".private/staging.json"), project_root=tmp_path)
