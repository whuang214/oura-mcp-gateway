from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).parents[1]
DOCS = ROOT / "docs"
LOCAL_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")

EXPECTED_TECHNICAL_DOCS = {
    "00 - Documentation Index.md",
    "01 - Getting Started.md",
    "02 - Authentication.md",
    "03 - Configuration.md",
    "04 - Architecture.md",
    "05 - Oura Upstream Map.md",
    "06 - API V1 Contract.md",
    "07 - Data Contract.md",
    "08 - Dedicated Oura Workbook Contract.md",
    "09 - Web Consumer Handoff.md",
    "10 - Development.md",
    "11 - Implementation Plan.md",
}


def _markdown_files() -> list[Path]:
    root_documents = [
        ROOT / "README.md",
        ROOT / "PRIVACY.md",
        ROOT / "TERMS.md",
    ]
    return sorted(root_documents + _public_docs())


def _public_docs() -> list[Path]:
    return [
        path
        for path in DOCS.rglob("*.md")
        if path.relative_to(DOCS).parts[0] != "private"
        and "verification" not in path.name.casefold()
    ]


def _link_destination(document: Path, raw_target: str) -> Path | None:
    target = raw_target.strip()
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    else:
        target = target.split(maxsplit=1)[0]
    if not target or target.startswith("#"):
        return None
    parsed = urlsplit(target)
    if parsed.scheme or parsed.netloc:
        return None
    relative_path = unquote(parsed.path)
    if not relative_path:
        return None
    return (document.parent / relative_path).resolve()


def test_technical_documentation_has_the_expected_structure() -> None:
    actual = {
        path.relative_to(DOCS).as_posix()
        for path in _public_docs()
    }
    assert actual == EXPECTED_TECHNICAL_DOCS


def test_relative_markdown_links_resolve_inside_the_repository() -> None:
    failures: list[str] = []
    for document in _markdown_files():
        text = document.read_text(encoding="utf-8")
        for match in LOCAL_LINK.finditer(text):
            destination = _link_destination(document, match.group(1))
            if destination is None:
                continue
            try:
                destination.relative_to(ROOT)
            except ValueError:
                failures.append(
                    f"{document.relative_to(ROOT)} links outside the repository: {match.group(1)}"
                )
                continue
            if not destination.exists():
                failures.append(
                    f"{document.relative_to(ROOT)} has a broken link: {match.group(1)}"
                )
    assert failures == []


def test_readme_stays_focused_on_the_user_path() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert len(readme.splitlines()) <= 150
    assert "## Quick start" in readme
    assert "## What you can query" in readme
    assert "## Documentation" in readme
    assert "## Research basis" not in readme
    assert "Connect an MCP client" not in readme
