from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).parents[1]
DOCS = ROOT / "docs"
LOCAL_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")

EXPECTED_TECHNICAL_DOCS = {
    "README.md",
    "development/testing.md",
    "guides/authentication.md",
    "guides/codex.md",
    "guides/configuration.md",
    "guides/getting-started.md",
    "guides/google-sheets.md",
    "oura-data-contract-v2.md",
    "oura-v2-migration.md",
    "operations/migration-v2.md",
    "reference/architecture.md",
    "reference/data-contract-v2.md",
    "reference/mcp-tools.md",
}


def _markdown_files() -> list[Path]:
    root_documents = [
        ROOT / "README.md",
        ROOT / "PRIVACY.md",
        ROOT / "SECURITY.md",
        ROOT / "TERMS.md",
    ]
    return sorted(
        root_documents
        + _public_docs()
        + list((ROOT / "integrations").rglob("*.md"))
    )


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
    assert "## Connect it to Codex" in readme
    assert "## Use your real Oura data" in readme
    assert "## Research basis" not in readme
