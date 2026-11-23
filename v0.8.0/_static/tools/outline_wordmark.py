"""Outline the "BattINFO" wordmark in the brand lockup SVGs.

The lockups are consumed via <img> tags (docs navbar, web navbar, README),
and SVGs inside <img> cannot load webfonts — a <text> wordmark therefore
always renders in whatever fallback font the viewer's OS provides. This tool
replaces each <text class="wm"> element with real glyph outlines from
Plus Jakarta Sans ExtraBold, so the wordmark renders identically everywhere.

Font: brand/assets/fonts/PlusJakartaSans[wght].ttf (variable; OFL-licensed,
see OFL.txt alongside). Re-run after editing wordmark text/position:

    uv run python brand/tools/outline_wordmark.py
"""
from __future__ import annotations

import re
from pathlib import Path

from fontTools import ttLib
from fontTools.misc.transform import Transform
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.varLib.instancer import instantiateVariableFont

BRAND = Path(__file__).resolve().parents[1]
FONT = BRAND / "assets" / "fonts" / "PlusJakartaSans[wght].ttf"
LOCKUPS = sorted((BRAND / "assets" / "logo").glob("*.svg"))
WEIGHT = 800

TEXT_RE = re.compile(r'<text class="wm"([^>]*)>(.*?)</text>', re.DOTALL)
TSPAN_RE = re.compile(r'<tspan fill="([^"]+)">([^<]+)</tspan>')


def _attr(attrs: str, name: str, default: float | None = None) -> float:
    m = re.search(rf'{name}="(-?[\d.]+)"', attrs)
    if m:
        return float(m.group(1))
    if default is None:
        raise ValueError(f"missing attribute {name}")
    return default


def outline(svg_text: str, font: ttLib.TTFont) -> str:
    cmap = font.getBestCmap()
    glyphs = font.getGlyphSet()
    hmtx = font["hmtx"]
    upm = font["head"].unitsPerEm

    def render(attrs: str, body: str) -> str:
        x = _attr(attrs, "x")
        y = _attr(attrs, "y")
        size = _attr(attrs, "font-size")
        spacing = _attr(attrs, "letter-spacing", 0.0)
        anchor_middle = 'text-anchor="middle"' in attrs
        scale = size / upm
        spans = TSPAN_RE.findall(body)

        def advance(ch: str) -> float:
            return hmtx[cmap[ord(ch)]][0] * scale + spacing

        total = sum(advance(ch) for _, text in spans for ch in text)
        cursor = x - total / 2 if anchor_middle else x

        parts = ['<g class="wm">']
        for fill, text in spans:
            d_parts: list[str] = []
            for ch in text:
                glyph_name = cmap[ord(ch)]
                pen = SVGPathPen(glyphs, ntos=lambda v: f"{v:.1f}")
                tpen = TransformPen(
                    pen, Transform().translate(cursor, y).scale(scale, -scale)
                )
                glyphs[glyph_name].draw(tpen)
                d = pen.getCommands()
                if d:
                    d_parts.append(d)
                cursor += advance(ch)
            parts.append(f'    <path fill="{fill}" d="{" ".join(d_parts)}"/>')
        parts.append("  </g>")
        return "\n  ".join(parts)

    def repl(m: re.Match) -> str:
        return render(m.group(1), m.group(2))

    out, n = TEXT_RE.subn(repl, svg_text)
    if n == 0:
        raise ValueError("no <text class=\"wm\"> element found")
    return out


def main() -> int:
    font = ttLib.TTFont(FONT)
    if "fvar" in font:
        instantiateVariableFont(font, {"wght": WEIGHT}, inplace=True)
    for path in LOCKUPS:
        text = path.read_text(encoding="utf-8")
        if '<text class="wm"' not in text:
            print(f"skip (already outlined): {path.name}")
            continue
        path.write_text(outline(text, font), encoding="utf-8")
        print(f"outlined: {path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
