from __future__ import annotations

import tarfile
from io import BytesIO
from pathlib import Path

from oura_data_api.distribution_audit import audit


def _archive(path: Path, files: dict[str, bytes]) -> None:
    with tarfile.open(path, "w:gz") as archive:
        for name, content in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(content)
            archive.addfile(info, BytesIO(content))


def test_distribution_audit_rejects_private_and_live_sheet_artifacts(
    tmp_path: Path,
) -> None:
    unsafe = tmp_path / "unsafe.tar.gz"
    _archive(
        unsafe,
        {
            "pkg/.env": b"OURA_CLIENT_SECRET=secret\n",
            "pkg/docs/report.md": b"https://docs.google.com/spreadsheets/d/live-id/edit",
        },
    )
    findings = audit([unsafe])
    assert any("private path" in item for item in findings)
    assert any("Google Sheet" in item for item in findings)


def test_distribution_audit_allows_blank_template(tmp_path: Path) -> None:
    safe = tmp_path / "safe.tar.gz"
    _archive(
        safe,
        {
            "pkg/.env.example": b"OURA_CLIENT_SECRET=\nOURA_ACCESS_TOKEN=\n",
            "pkg/README.md": (
                b"OURA_CLIENT_SECRET=\n"
                b"OURA_REDIRECT_URI=http://localhost:8765/callback\n"
            ),
        },
    )
    assert audit([safe]) == []
