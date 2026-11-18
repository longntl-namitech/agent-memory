"""Static page checks: no external URLs, landmarks, and WCAG contrast of the tokens."""

import re
from html.parser import HTMLParser
from pathlib import Path

STATIC = Path(__file__).resolve().parents[2] / "src" / "agent_memory" / "demo" / "static"
FILES = ("index.html", "style.css", "app.js", "theme.js")


def test_no_external_urls():
    for name in FILES:
        text = (STATIC / name).read_text()
        for bad in ("http://", "https://", "//cdn", "@import", "url(//", "//fonts"):
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
            ("on-accent", "accent"), ("danger", "bg"), ("danger", "card"), ("danger", "muted"),
        ]
        for fg, bg in text_pairs:
            assert _ratio(t[fg], t[bg]) >= 4.5, (name, fg, bg, _ratio(t[fg], t[bg]))
        # Disabled controls (.btn:disabled, opacity .5) are exempt from WCAG 1.4.3 and 1.4.11.
        for bg in ("bg", "card", "muted"):
            assert _ratio(t["outline"], t[bg]) >= 3.0, (name, "outline", bg)
            assert _ratio(t["ring"], t[bg]) >= 3.0, (name, "ring", bg)
        assert _ratio(t["hairline"], t["bg"]) < _ratio(t["outline"], t["bg"])


def test_hook_ids_exist():
    p = _Ids()
    p.feed((STATIC / "index.html").read_text())
    ids = {a["id"] for a in p.attrs if "id" in a}
    need = {"mode-live", "mode-replay", "tokens-none", "tokens-full", "tokens-cap", "sim-date",
            "notice", "notice-text", "notice-close", "mode-status", "mode-text", "wipe", "wipe-status", "error-none", "error-full",
            "advance", "reflect", "theme", "chips", "send", "input", "send-btn", "reset"}
    for c in ("none", "full"):
        need |= {f"transcript-{c}", f"seen-toggle-{c}", f"seen-{c}", f"todo-{c}", f"col-{c}"}
        need |= {f"{k}-{c}-{n}" for k in ("tab", "pane") for n in ("rules", "facts", "log")}
    assert need <= ids, need - ids


def test_static_has_flash_and_reduced_motion_css():
    css = (STATIC / "style.css").read_text()
    assert "@keyframes flash" in css and ".entry.flash" in css
    block = re.search(r"@media \(prefers-reduced-motion: reduce\)\s*\{(.*?)\n\}", css, re.S).group(1)
    assert "animation: none" in block
    rule = re.search(r"\.entry\.new \{(.*?)\}", css, re.S).group(1)  # the static cue stays under reduced motion
    assert "border-left-color: var(--accent)" in rule and "animation" not in rule


def test_app_js_has_no_browser_dialogs_or_innerhtml():
    js = (STATIC / "app.js").read_text()
    for bad in ("alert(", "confirm(", "prompt(", "innerHTML", "outerHTML", "insertAdjacentHTML"):
        assert bad not in js, bad
    for need in ("/api/mode", "/api/advance", "/api/reflect", "/api/reset", "/api/wipe", "Confirm wipe", "Escape"):
        assert need in js, need


def test_icon_buttons_have_accessible_names():
    html = (STATIC / "index.html").read_text()
    for svg in re.findall(r"<svg\b[^>]*>", html):
        assert 'aria-hidden="true"' in svg and "xmlns" not in svg
    btn = re.search(r'<button[^>]*id="theme"[^>]*>(.*?)</button>', html, re.S).group(1)
    assert re.search(r'<span id="theme-label">[^<]+</span>', btn)  # the visible text is the accessible name
    for b in re.findall(r"<button\b[^>]*>(.*?)</button>", html, re.S):
        assert re.sub(r"<svg.*?</svg>|<[^>]+>|\s", "", b, flags=re.S), "button without text"


def test_theme_tokens_defined_for_both_themes():
    dark, light = _tokens(":root"), _tokens(':root[data-theme="light"]')
    for token in ("bg", "card", "fg", "muted-fg", "outline", "accent", "on-accent", "danger", "ring"):
        assert token in dark
    assert set(light) <= set(dark) and {"bg", "fg", "accent", "outline", "ring"} <= set(light)


def test_font_sizes_meet_minimums():
    css = (STATIC / "style.css").read_text()
    assert re.search(r"body \{[^}]*font: 15px", css)
    for sel in (r"\.mono", r"\.pane"):
        px = re.search(sel + r" \{[^}]*?(\d+)px", css).group(1)
        assert int(px) >= 14, sel
    sizes = [int(n) for n in re.findall(r"font(?:-size)?:\s*(\d+)px", css)]
    assert min(sizes) >= 12
