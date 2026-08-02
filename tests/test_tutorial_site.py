from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_tutorial_site.py"


def load_builder():
    spec = importlib.util.spec_from_file_location("build_tutorial_site", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_tutorial_site_builds_with_resolvable_local_links(tmp_path: Path) -> None:
    builder = load_builder()
    output = tmp_path / "site"
    pages = builder.build(ROOT, output)

    assert len(pages) == 9
    assert (output / "index.html").is_file()
    assert (output / "assets" / "readme" / "evidence-loop-mobile.svg").is_file()

    attribute_pattern = re.compile(r'(?:href|src|srcset)="([^"]+)"')
    for page in pages:
        html = page.read_text(encoding="utf-8")
        assert "docs/proactive-agent" not in html
        for raw_target in attribute_pattern.findall(html):
            target = raw_target.split()[0]
            parsed = urlparse(target)
            if parsed.scheme or parsed.netloc or target.startswith(("#", "mailto:")):
                continue
            local = (page.parent / unquote(parsed.path)).resolve()
            assert local.exists(), f"broken local target {target} in {page.name}"


def test_chapter_navigation_has_one_active_entry(tmp_path: Path) -> None:
    builder = load_builder()
    output = tmp_path / "site"
    builder.build(ROOT, output)

    chapter = (output / "05-proactive-dialogue.html").read_text(encoding="utf-8")
    desktop_nav = chapter.split('class="chapter-links"', 1)[1].split("</nav>", 1)[0]
    assert desktop_nav.count('class="active"') == 1
    assert 'href="04-evidence-release.html"' in chapter
    assert 'href="06-research-and-adaptation.html"' in chapter
