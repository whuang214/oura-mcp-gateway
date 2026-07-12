"""Release archive privacy checks."""

from __future__ import annotations

import re
import sys
import tarfile
import zipfile
from collections.abc import Iterable
from pathlib import Path, PurePosixPath

FORBIDDEN_NAMES = {".env", "tokens.json", "local-config.md"}
FORBIDDEN_PARTS = {".private"}
TEXT_SUFFIXES = {".env", ".json", ".md", ".toml", ".txt", ".yaml", ".yml"}
SECRET_ASSIGNMENT = re.compile(
    rb"OURA_(?:CLIENT_SECRET|ACCESS_TOKEN)\s*=\s*[^\s#\r\n]"
)
TOKEN_JSON = re.compile(rb'"(?:access_token|refresh_token)"\s*:\s*"[^"\s]+"')
SHEET_LINK = re.compile(rb"docs\.google\.com/spreadsheets/d/[A-Za-z0-9_-]+")


def _members(path: Path) -> Iterable[tuple[str, bytes]]:
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for zip_member in archive.infolist():
                if not zip_member.is_dir():
                    yield zip_member.filename, archive.read(zip_member)
        return
    if tarfile.is_tarfile(path):
        with tarfile.open(path) as archive:
            for tar_member in archive.getmembers():
                if not tar_member.isfile():
                    continue
                handle = archive.extractfile(tar_member)
                if handle is not None:
                    yield tar_member.name, handle.read()
        return
    raise ValueError(f"Unsupported distribution archive: {path}")


def audit(paths: Iterable[Path]) -> list[str]:
    findings: list[str] = []
    for archive in paths:
        for raw_name, content in _members(archive):
            name = PurePosixPath(raw_name)
            lowered_parts = {part.casefold() for part in name.parts}
            basename = name.name.casefold()
            if basename in FORBIDDEN_NAMES or lowered_parts & FORBIDDEN_PARTS:
                findings.append(f"{archive.name}: forbidden private path {raw_name}")
            if "verification" in basename:
                findings.append(f"{archive.name}: verification artifact {raw_name}")
            if name.suffix.casefold() not in TEXT_SUFFIXES or len(content) > 2_000_000:
                continue
            if SECRET_ASSIGNMENT.search(content):
                findings.append(f"{archive.name}: populated Oura secret in {raw_name}")
            if TOKEN_JSON.search(content):
                findings.append(f"{archive.name}: serialized OAuth token in {raw_name}")
            if SHEET_LINK.search(content):
                findings.append(f"{archive.name}: live Google Sheet link in {raw_name}")
    return findings


def main() -> int:
    paths = [Path(value) for value in sys.argv[1:]]
    if not paths:
        print("usage: audit_distribution.py DIST_ARCHIVE [...]", file=sys.stderr)
        return 2
    findings = audit(paths)
    if findings:
        print("Distribution privacy audit failed:", file=sys.stderr)
        for finding in findings:
            print(f"- {finding}", file=sys.stderr)
        return 1
    print(f"Distribution privacy audit passed for {len(paths)} archive(s).")
    return 0
