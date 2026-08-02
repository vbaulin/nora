#!/usr/bin/env python3
"""Build the proactive-agent GitHub Pages site from chapter Markdown."""

from __future__ import annotations

import argparse
import html
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import markdown


REPO_URL = "https://github.com/vbaulin/nora"


@dataclass(frozen=True)
class Page:
    source: Path
    title: str
    summary: str
    eyebrow: str
    order: int
    body: str

    @property
    def output_name(self) -> str:
        return "index.html" if self.order == 0 else f"{self.source.stem}.html"


def parse_frontmatter(path: Path) -> Page:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"missing front matter: {path}")
    _, frontmatter, body = text.split("---\n", 2)
    metadata: dict[str, str] = {}
    for line in frontmatter.splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, value = line.split(":", 1)
        metadata[key.strip()] = value.strip().strip('"')
    required = {"title", "summary", "order"}
    missing = sorted(required - metadata.keys())
    if missing:
        raise ValueError(f"missing {', '.join(missing)} in {path}")
    return Page(
        source=path,
        title=metadata["title"],
        summary=metadata["summary"],
        eyebrow=metadata.get("eyebrow", "Tutorial"),
        order=int(metadata["order"]),
        body=body.strip(),
    )


def strip_first_heading(body: str) -> str:
    return re.sub(r"\A#\s+[^\n]+\n+", "", body, count=1)


def rewrite_links(body: str) -> str:
    body = body.replace("../../assets/readme/", "assets/readme/")
    body = body.replace(
        "../tutorial-proactive-field-companion.md",
        f"{REPO_URL}/blob/main/docs/tutorial-proactive-field-companion.md",
    )
    body = body.replace(
        "../applications/vineyard-disease-risk-models.md",
        f"{REPO_URL}/blob/main/docs/applications/vineyard-disease-risk-models.md",
    )
    return re.sub(r"\((\d{2}-[a-z0-9-]+)\.md([#)])", r"(\1.html\2", body)


def render_markdown(body: str) -> str:
    return markdown.markdown(
        rewrite_links(strip_first_heading(body)),
        extensions=["extra", "sane_lists", "toc"],
        extension_configs={"toc": {"permalink": False}},
        output_format="html5",
    )


def reading_minutes(body: str) -> int:
    words = len(re.findall(r"\b[\w'-]+\b", body))
    return max(1, round(words / 210))


def nav_items(pages: list[Page], current: Page, mobile: bool = False) -> str:
    links = []
    for page in pages:
        active = page.order == current.order
        label = "Overview" if page.order == 0 else f"{page.order}. {page.title}"
        attrs = ' aria-current="page"' if active else ""
        class_name = "active" if active else ""
        links.append(
            f'<a class="{class_name}" href="{page.output_name}"{attrs}>'
            f"{html.escape(label)}</a>"
        )
    wrapper = "mobile-chapter-links" if mobile else "chapter-links"
    return f'<nav class="{wrapper}" aria-label="Tutorial chapters">' + "".join(links) + "</nav>"


def chapter_footer(pages: list[Page], current: Page) -> str:
    index = pages.index(current)
    previous = pages[index - 1] if index > 0 else None
    following = pages[index + 1] if index + 1 < len(pages) else None
    parts = ['<nav class="chapter-footer" aria-label="Previous and next chapter">']
    if previous:
        parts.append(
            f'<a class="chapter-direction previous" href="{previous.output_name}">'
            f'<span>Previous</span><strong>{html.escape(previous.title)}</strong></a>'
        )
    else:
        parts.append('<span class="chapter-direction spacer"></span>')
    if following:
        parts.append(
            f'<a class="chapter-direction next" href="{following.output_name}">'
            f'<span>Next</span><strong>{html.escape(following.title)}</strong></a>'
        )
    else:
        parts.append(
            f'<a class="chapter-direction next" href="{REPO_URL}">'
            '<span>Continue</span><strong>Explore the repository</strong></a>'
        )
    parts.append("</nav>")
    return "".join(parts)


def render_page(pages: list[Page], page: Page) -> str:
    content = render_markdown(page.body)
    progress = round((page.order + 1) / len(pages) * 100)
    home_class = " home" if page.order == 0 else ""
    if page.order == 0:
        heading = f"""
        <header class="home-hero">
          <div class="hero-content">
            <p class="eyebrow">{html.escape(page.eyebrow)}</p>
            <h1>{html.escape(page.title)}</h1>
            <p>{html.escape(page.summary)}</p>
            <div class="hero-links">
              <a class="primary-link" href="01-reasoning-and-execution.html">Start chapter 1</a>
              <a class="secondary-link" href="{REPO_URL}">View source</a>
            </div>
          </div>
        </header>
        """
    else:
        heading = f"""
        <header class="chapter-heading">
          <p class="eyebrow">{html.escape(page.eyebrow)}</p>
          <h1>{html.escape(page.title)}</h1>
          <p>{html.escape(page.summary)}</p>
          <div class="chapter-meta">Chapter {page.order} of {len(pages) - 1} / {reading_minutes(page.body)} min read</div>
        </header>
        """

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="description" content="{html.escape(page.summary)}">
  <meta name="theme-color" content="#0b1410">
  <title>{html.escape(page.title)} / nano-os-agent</title>
  <link rel="stylesheet" href="assets/site.css">
</head>
<body class="{home_class.strip()}">
  <a class="skip-link" href="#content">Skip to content</a>
  <div class="reading-progress" aria-hidden="true"><span style="width:{progress}%"></span></div>
  <header class="topbar">
    <a class="brand" href="index.html"><span class="brand-mark">N</span><span>nano-os-agent</span></a>
    <nav class="top-links" aria-label="Project links">
      <a href="{REPO_URL}/blob/main/README.md">README</a>
      <a href="{REPO_URL}">GitHub</a>
    </nav>
  </header>
  {heading}
  <details class="mobile-nav">
    <summary>Browse chapters</summary>
    {nav_items(pages, page, mobile=True)}
  </details>
  <div class="docs-shell">
    <aside class="sidebar">
      <p class="sidebar-label">Tutorial chapters</p>
      {nav_items(pages, page)}
      <div class="sidebar-note">
        <strong>Evidence rule</strong>
        <span>Observed, confirmed, sourced, and proposed are different states.</span>
      </div>
    </aside>
    <main id="content" class="content">
      {content}
      {chapter_footer(pages, page)}
    </main>
  </div>
  <footer class="site-footer">
    <p>Built from repository-verified contracts and code. Chapter structure adapted from PocketFlow Tutorial Codebase Knowledge.</p>
  </footer>
  <script type="module" src="assets/site.js"></script>
</body>
</html>
"""


def copy_assets(root: Path, output: Path) -> None:
    assets = output / "assets"
    readme_assets = assets / "readme"
    readme_assets.mkdir(parents=True, exist_ok=True)
    shutil.copy2(root / "docs" / "proactive-agent" / "assets" / "site.css", assets / "site.css")
    shutil.copy2(root / "docs" / "proactive-agent" / "assets" / "site.js", assets / "site.js")
    shutil.copy2(root / "images" / "LicheeRV Nano.jpg", assets / "licheerv-nano.jpg")
    shutil.copy2(root / "assets" / "readme" / "evidence-loop.svg", readme_assets / "evidence-loop.svg")
    shutil.copy2(
        root / "assets" / "readme" / "evidence-loop-mobile.svg",
        readme_assets / "evidence-loop-mobile.svg",
    )


def build(root: Path, output: Path) -> list[Path]:
    source_dir = root / "docs" / "proactive-agent"
    pages = sorted(
        (parse_frontmatter(path) for path in source_dir.glob("*.md")),
        key=lambda item: item.order,
    )
    if not pages or pages[0].order != 0:
        raise ValueError("tutorial requires an order=0 index page")
    if [page.order for page in pages] != list(range(len(pages))):
        raise ValueError("tutorial page order must be contiguous from zero")

    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    copy_assets(root, output)

    written: list[Path] = []
    for page in pages:
        destination = output / page.output_name
        destination.write_text(render_page(pages, page), encoding="utf-8")
        written.append(destination)
    (output / ".nojekyll").write_text("", encoding="utf-8")
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="_site", help="output directory")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = Path(args.output)
    if not output.is_absolute():
        output = root / output
    written = build(root, output)
    print(f"built {len(written)} pages in {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
