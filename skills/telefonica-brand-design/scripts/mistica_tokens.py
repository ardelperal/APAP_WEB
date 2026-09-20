#!/usr/bin/env python3
"""Fetch and inspect official Mística design tokens.

Examples:
  python scripts/mistica_tokens.py --skin telefonica --summary
  python scripts/mistica_tokens.py --skin telefonica --css --out tokens.css
  python scripts/mistica_tokens.py --skin telefonica --semantic --out semantic.css
  python scripts/mistica_tokens.py --skin movistar-new --json --out movistar-new.json
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

BASE = "https://raw.githubusercontent.com/Telefonica/mistica-design/production/tokens/{skin}.json"
SKINS = [
    "telefonica",
    "movistar",
    "movistar-new",
    "o2",
    "o2-new",
    "vivo",
    "vivo-new",
    "blau",
    "tu",
    "esimflag",
]


def fetch(skin: str) -> dict:
    url = BASE.format(skin=skin)
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def token_value(token):
    return token.get("value") if isinstance(token, dict) else token


def css_name(name: str) -> str:
    out = []
    for ch in name:
        if ch.isupper():
            out.append("-" + ch.lower())
        else:
            out.append(ch)
    return "".join(out).replace("_", "-").strip("-")


def print_summary(data: dict, skin: str) -> None:
    print(f"skin: {skin}")
    print("top_level:", ", ".join(data.keys()))
    print("palette_count:", len(data.get("global", {}).get("palette", {})))
    print("light_tokens:", len(data.get("light", {})))
    print("dark_tokens:", len(data.get("dark", {})))
    print("radius:")
    for k, v in data.get("radius", {}).items():
        print(f"  {k}: {token_value(v)}")
    print("text.size:")
    for k, v in data.get("text", {}).get("size", {}).items():
        print(f"  {k}: {token_value(v)}")
    print("spacing:")
    for k, v in data.get("spacing", {}).items():
        print(f"  {k}: {token_value(v)}")


def _radius_value(val) -> str:
    """Convert a radius token value to a CSS string."""
    raw = str(val)
    if raw == "circle":
        return "50%"
    try:
        n = float(raw)
        return f"{int(n)}px" if n == int(n) else f"{n}px"
    except ValueError:
        return raw


def to_css(data: dict, skin: str) -> str:
    """Export palette + radius as CSS custom properties."""
    lines = [f"/* Mística palette — {skin} skin */", ":root {"]
    palette = data.get("global", {}).get("palette", {})
    for k, v in palette.items():
        lines.append(f"  --mistica-{css_name(k)}: {token_value(v)};")
    lines.append("")
    lines.append("  /* Radius */")
    for k, v in data.get("radius", {}).items():
        lines.append(f"  --mistica-radius-{css_name(k)}: {_radius_value(token_value(v))};")
    lines.append("}")
    return "\n".join(lines) + "\n"


def _hex_to_rgb(hex_color: str) -> str | None:
    """Convert '#RRGGBB' to 'R, G, B'. Returns None if not a valid hex."""
    h = hex_color.strip().lstrip("#")
    if len(h) != 6:
        return None
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return f"{r}, {g}, {b}"
    except ValueError:
        return None


def _resolve_value(raw_val, palette: dict) -> str:
    """Replace {palette.tokenName} references with actual palette values.

    Handles:
    - Simple: ``{palette.telefonicaBlue}`` → ``#0066ff``
    - Embedded: ``rgba({palette.telefonicaBlue70}, 0.05)`` → ``rgba(3, 86, 201, 0.05)``
    """
    if not isinstance(raw_val, str):
        return str(raw_val)
    import re

    def _replace_ref(m: re.Match) -> str:
        key = m.group(1)
        resolved = str(token_value(palette.get(key, m.group(0))))
        # If the reference is inside rgba(), convert hex to RGB
        start = m.start()
        prefix = raw_val[max(0, start - 5):start].lower()
        if "rgba(" in prefix or "rgb(" in prefix:
            rgb = _hex_to_rgb(resolved)
            if rgb:
                return rgb
        return resolved

    return re.sub(r"\{palette\.([^}]+)\}", _replace_ref, raw_val)


def to_semantic_css(data: dict, skin: str) -> str:
    """Export semantic light/dark tokens as CSS custom properties.

    Produces a :root block for light mode and a @media (prefers-color-scheme: dark)
    block with :root overrides for dark mode.
    """
    palette = data.get("global", {}).get("palette", {})
    light = data.get("light", {})
    dark  = data.get("dark", {})

    def _gradient_to_css(grad: dict) -> str:
        """Convert a Mística gradient object to a CSS linear-gradient."""
        angle = grad.get("angle", 180)
        stops = grad.get("colors", [])
        parts = [f"{angle}deg"]
        for s in stops:
            color = _resolve_value(s.get("value", "transparent"), palette)
            pct = s.get("stop")
            if pct is not None:
                parts.append(f"{color} {round(pct * 100)}%")
            else:
                parts.append(color)
        return f"linear-gradient({', '.join(parts)})"

    def block(tokens: dict) -> list[str]:
        lines = []
        for k, v in tokens.items():
            raw = token_value(v)
            if isinstance(raw, str):
                resolved = _resolve_value(raw, palette)
            elif isinstance(raw, dict) and "angle" in raw and "colors" in raw:
                resolved = _gradient_to_css(raw)
            elif isinstance(raw, dict):
                # Skip unsupported complex objects
                resolved = f"/* complex: see token JSON for '{k}' */"
            else:
                resolved = str(raw)
            lines.append(f"  --{css_name(k)}: {resolved};")
        return lines

    parts = [f"/* Mística semantic tokens — {skin} skin — light mode */", ":root {"]
    parts.extend(block(light))
    parts.append("}")
    parts.append("")
    parts.append(f"/* Mística semantic tokens — {skin} skin — dark mode */")
    parts.append("@media (prefers-color-scheme: dark) {")
    parts.append("  :root {")
    for line in block(dark):
        parts.append("  " + line)  # extra indent inside @media
    parts.append("  }")
    parts.append("}")
    return "\n".join(parts) + "\n"


def _emit_responsive(prefix: str, val) -> list[str]:
    """Emit mobile/desktop CSS vars from a ``{"mobile": X, "desktop": Y}`` dict.

    If both values are the same, emit a single property without a suffix.
    """
    if isinstance(val, dict) and "mobile" in val and "desktop" in val:
        m, d = val["mobile"], val["desktop"]
        if m == d:
            return [f"  {prefix}: {m}px;"]
        return [
            f"  {prefix}-mobile: {m}px;",
            f"  {prefix}-desktop: {d}px;",
        ]
    # Scalar
    return [f"  {prefix}: {val}px;"]


def to_spacing_css(data: dict, skin: str) -> str:
    """Export spacing + typography size tokens as CSS custom properties."""
    parts = [f"/* Mistica spacing + typography -- {skin} skin */", ":root {"]

    # --- Spacing ---
    for k, v in data.get("spacing", {}).items():
        raw = token_value(v)
        if isinstance(raw, dict):
            # Could be {"left": {"mobile":20,"desktop":20}, "right": ...}
            # or directly {"mobile": X, "desktop": Y}
            if "mobile" in raw and "desktop" in raw:
                parts.extend(_emit_responsive(f"--spacing-{css_name(k)}", raw))
            else:
                for sub_k, sub_v in raw.items():
                    if isinstance(sub_v, dict) and "mobile" in sub_v:
                        parts.extend(
                            _emit_responsive(
                                f"--spacing-{css_name(k)}-{css_name(sub_k)}",
                                sub_v,
                            )
                        )
                    else:
                        parts.append(f"  --spacing-{css_name(k)}-{css_name(sub_k)}: {sub_v}px;")
        elif raw is not None:
            parts.append(f"  --spacing-{css_name(k)}: {raw}px;")

    # --- Text sizes ---
    text = data.get("text", {})
    for size_key, size_val in text.get("size", {}).items():
        inner = token_value(size_val)  # unwrap {"value": ..., "type": ...}
        if isinstance(inner, dict) and "mobile" in inner and "desktop" in inner:
            parts.extend(
                _emit_responsive(f"--text-size-{css_name(size_key)}", inner)
            )
        elif inner is not None:
            parts.append(f"  --text-size-{css_name(size_key)}: {inner}px;")

    # --- Text weights ---
    for weight_key, weight_val in text.get("weight", {}).items():
        inner = token_value(weight_val)
        if inner is not None:
            parts.append(f"  --text-weight-{css_name(weight_key)}: {inner};")

    parts.append("}")
    return "\n".join(parts) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Fetch and convert Mística design tokens to CSS or JSON."
    )
    ap.add_argument("--skin",     default="telefonica", choices=SKINS, help="Skin name")
    ap.add_argument("--summary",  action="store_true", help="Print a summary to stdout")
    ap.add_argument("--css",      action="store_true", help="Export palette + radius as CSS variables")
    ap.add_argument("--semantic", action="store_true", help="Export semantic light/dark tokens as CSS variables")
    ap.add_argument("--spacing",  action="store_true", help="Export spacing + typography tokens as CSS variables")
    ap.add_argument("--json",     action="store_true", help="Export raw token JSON")
    ap.add_argument("--out",      metavar="FILE",      help="Write output to FILE instead of stdout")
    args = ap.parse_args()

    data = fetch(args.skin)

    if args.summary:
        print_summary(data, args.skin)
        return 0

    if args.json:
        content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    elif args.semantic:
        content = to_semantic_css(data, args.skin)
    elif args.spacing:
        content = to_spacing_css(data, args.skin)
    elif args.css:
        content = to_css(data, args.skin)
    else:
        # Default: print summary
        print_summary(data, args.skin)
        return 0

    if args.out:
        Path(args.out).write_text(content, encoding="utf-8")
        print(f"Written to {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(content)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
