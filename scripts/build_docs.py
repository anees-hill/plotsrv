"""Build documentation, preserve moved URLs, and check local links.

Run from any directory: uv run --locked --group docs python scripts/build_docs.py
"""
from __future__ import annotations

import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"


class Page(HTMLParser):
    def __init__(self, source: str):
        super().__init__()
        self.ids: set[str] = set()
        self.links: list[str] = []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("id"):
            self.ids.add(attrs["id"])
        if tag == "a" and attrs.get("href"):
            self.links.append(attrs["href"])
        if tag in {"img", "script", "iframe"} and attrs.get("src"):
            self.links.append(attrs["src"])


def output_path(markdown: str) -> Path:
    path = Path(markdown)
    if path.suffix != ".md" or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"Invalid redirect source: {markdown}")
    return SITE / (path.with_suffix(".html") if path.name == "index.md"
                   else path.with_suffix("") / "index.html")


def redirects() -> None:
    mapping = json.loads((ROOT / "scripts/docs_redirects.json").read_text())
    for source, destination in mapping.items():
        target, _, anchor = destination.partition("#")
        dest = output_path(target)
        if not dest.is_file():
            raise ValueError(f"Missing redirect destination: {destination}")
        old = output_path(source)
        if (ROOT / "docs" / source).exists():
            raise ValueError(f"Redirect shadows a source page: {source}")
        relative = Path(os.path.relpath(dest.parent, old.parent)).as_posix() + "/"
        ids = Page(dest.read_text()).ids
        if anchor and anchor not in ids:
            raise ValueError(f"Missing redirect anchor: {destination}")
        fallback = relative + ("#" + anchor if anchor else "")
        old.parent.mkdir(parents=True, exist_ok=True)
        # Preserve fragments only when they still exist on the destination.
        # A split page's explicit destination anchor takes precedence.
        old.write_text(
            '<!doctype html><html lang="en"><meta charset="utf-8">'
            '<title>Page moved · plotsrv</title>'
            f'<link rel="canonical" href="{html.escape(fallback, quote=True)}">'
            '<script>const base=' + json.dumps(relative) + ';const anchor='
            + json.dumps(anchor) + ';const ids=' + json.dumps(sorted(ids)) + ';'
            'const requested=decodeURIComponent(location.hash.slice(1));'
            'const fragment=anchor||(ids.includes(requested)?requested:"");'
            'location.replace(base+location.search+(fragment?"#"+encodeURIComponent(fragment):""));'
            '</script><p>This page has moved. '
            f'<a href="{html.escape(fallback, quote=True)}">Open the current documentation</a>.</p></html>'
        )


def check_links() -> None:
    pages = {p.resolve(): Page(p.read_text()) for p in SITE.rglob("*.html")}
    errors = []
    edges: dict[Path, set[Path]] = {}
    for path, page in pages.items():
        edges[path] = set()
        for link in page.links:
            # Zensical's generated 404 template has no article skip target.
            if path.name == "404.html" and link == "#__skip":
                continue
            parsed = urlsplit(link)
            if parsed.scheme or parsed.netloc:
                continue
            target = ((SITE / unquote(parsed.path).lstrip("/")) if parsed.path.startswith("/")
                      else path.parent / unquote(parsed.path)) if parsed.path else path
            if target.is_dir():
                target /= "index.html"
            target = target.resolve()
            if not target.is_file():
                errors.append(f"{path.relative_to(SITE)}: missing {link}")
            elif target in pages:
                edges[path].add(target)
                if parsed.fragment and unquote(parsed.fragment) not in pages[target].ids:
                    errors.append(f"{path.relative_to(SITE)}: missing anchor {link}")
    seen, todo = set(), [(SITE / "index.html").resolve()]
    while todo:
        path = todo.pop()
        if path not in seen:
            seen.add(path)
            todo.extend(edges.get(path, ()))
    for source in (ROOT / "docs").rglob("*.md"):
        page = output_path(str(source.relative_to(ROOT / "docs"))).resolve()
        if page not in seen:
            errors.append(f"Unreachable article: {source.relative_to(ROOT)}")
    if errors:
        raise SystemExit("\n".join(sorted(set(errors))))
    print(f"Checked links, anchors and reachability in {len(pages)} HTML pages.")


def main():
    subprocess.run([sys.executable, "-m", "zensical", "build", "--clean", "--strict"],
                   cwd=ROOT, check=True)
    redirects()
    check_links()


if __name__ == "__main__":
    main()
