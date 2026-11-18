"""Static page checks: no external URLs, landmarks, and WCAG contrast of the tokens."""

import re
from html.parser import HTMLParser
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "agent_memory" / "demo" / "static"
FILES = ("index.html", "style.css", "app.js")


def test_no_external_urls():
    for name in FILES:
        text = (STATIC / name).read_text()
        for bad in ("http://", "https://", "//cdn"):
            assert bad not in text, f"{name} contains {bad}"


class _Ids(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.attrs = [], []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.attrs.append(dict(attrs))


def test_html_has_landmarks_and_two_columns():
    p = _Ids()
    p.feed((STATIC / "index.html").read_text())
    for tag in ("header", "main", "footer"):
        assert tag in p.tags
    cols = [a["data-column"] for a in p.attrs if "data-column" in a]
    assert cols == ["none", "full"]
    ids = {a["id"] for a in p.attrs if "id" in a}
    for need in ("input", "send", "advance", "reflect", "reset", "chips", "todo-none", "todo-full"):
        assert need in ids
    for col in ("none", "full"):
        for tab in ("rules", "facts", "log"):
            assert f"tab-{col}-{tab}" in ids
    assert "/static/style.css" in (STATIC / "index.html").read_text()
    assert "/static/app.js" in (STATIC / "index.html").read_text()


def _tokens(selector: str) -> dict[str, str]:
    css = (STATIC / "style.css").read_text()
    block = re.search(re.escape(selector) + r"\s*\{(.*?)\}", css, re.S).group(1)
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9A-Fa-f]{6})", block))


def _lum(hex_: str) -> float:
    ch = [int(hex_[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in ch]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _ratio(a: str, b: str) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_contrast_tokens():
    base = _tokens(":root")
    for name, t in (("dark", base), ("light", {**base, **_tokens(':root[data-theme="light"]')})):
        text_pairs = [
            ("fg", "bg"), ("fg", "card"), ("fg", "muted"),
            ("muted-fg", "bg"), ("muted-fg", "card"), ("muted-fg", "muted"),
            ("accent", "bg"), ("accent", "card"), ("accent", "accent-soft"),
            ("on-accent", "accent"), ("danger", "bg"), ("danger", "card"),
        ]
        for fg, bg in text_pairs:
            assert _ratio(t[fg], t[bg]) >= 4.5, (name, fg, bg, _ratio(t[fg], t[bg]))
        for bg in ("bg", "card"):
            assert _ratio(t["outline"], t[bg]) >= 3.0, (name, "outline", bg)
            assert _ratio(t["ring"], t[bg]) >= 3.0, (name, "ring", bg)
        assert _ratio(t["hairline"], t["bg"]) < _ratio(t["outline"], t["bg"])
