"""Generate Pathways PWA icons.

Renders icon-192.png and icon-512.png with the same visual identity as
favicon.svg: a deep teal rounded-square background, a coral sun, and a
warm cream pathway curving up toward the sun.

We draw at 4x resolution and downsample for clean edges without needing
an external SVG renderer.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

# Palette
TEAL = (13, 92, 79, 255)
TEAL_DEEP = (10, 74, 64, 255)
CREAM = (250, 247, 242, 255)
CORAL = (224, 133, 102, 255)
CORAL_GLOW = (224, 133, 102, 64)


def lerp(a: tuple[int, ...], b: tuple[int, ...], t: float) -> tuple[int, ...]:
    return tuple(int(round(a[i] + (b[i] - a[i]) * t)) for i in range(len(a)))


def cubic_bezier(
    p0: tuple[float, float],
    p1: tuple[float, float],
    p2: tuple[float, float],
    p3: tuple[float, float],
    steps: int = 200,
) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for i in range(steps + 1):
        t = i / steps
        u = 1 - t
        x = (u**3) * p0[0] + 3 * (u**2) * t * p1[0] + 3 * u * (t**2) * p2[0] + (t**3) * p3[0]
        y = (u**3) * p0[1] + 3 * (u**2) * t * p1[1] + 3 * u * (t**2) * p2[1] + (t**3) * p3[1]
        pts.append((x, y))
    return pts


def make_icon(size: int, maskable: bool = False) -> Image.Image:
    """Render the Pathways icon at `size` pixels.

    If maskable=True, draw the artwork inside the safe inner 80% so Android
    can crop to circle/squircle without losing the mark. The PWA manifest
    declares the file as "any maskable" so a single asset serves both.
    """
    scale = 4
    s = size * scale

    # Background: rounded square with subtle diagonal gradient
    bg = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    grad = Image.new("RGBA", (s, s), TEAL)
    for y in range(s):
        for x in range(s):
            pass  # full-image lerp is too slow; do a simple two-stop overlay instead
    # Cheap diagonal gradient via paste with alpha
    for i in range(s):
        col = lerp(TEAL, TEAL_DEEP, i / max(1, s - 1))
        ImageDraw.Draw(grad).line([(0, i), (s, i)], fill=col)
    # Mask: rounded square
    mask = Image.new("L", (s, s), 0)
    radius = int(s * (56 / 256))
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, s - 1, s - 1), radius=radius, fill=255)
    bg.paste(grad, (0, 0), mask)

    # Coordinate system for the foreground art uses the 256 viewBox scaled to s
    def sc(v: float) -> float:
        return v * (s / 256)

    # Maskable: shrink artwork into the safe zone (80%)
    if maskable:
        art_size = int(s * 0.80)
        art_offset = (s - art_size) // 2
        art = Image.new("RGBA", (art_size, art_size), (0, 0, 0, 0))
        a_draw = ImageDraw.Draw(art)

        def sca(v: float) -> float:
            return v * (art_size / 256)

        # Sun glow (soft)
        glow = Image.new("RGBA", (art_size, art_size), (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse(
            (sca(200 - 48), sca(76 - 48), sca(200 + 48), sca(76 + 48)),
            fill=CORAL_GLOW,
        )
        glow = glow.filter(ImageFilter.GaussianBlur(radius=sca(6)))
        art = Image.alpha_composite(art, glow)
        a_draw = ImageDraw.Draw(art)

        # Pathway: cream cubic bezier rendered as a thick rounded polyline
        path_pts = cubic_bezier(
            (sca(44), sca(196)),
            (sca(108), sca(196)),
            (sca(118), sca(132)),
            (sca(200), sca(76)),
            steps=240,
        )
        stroke_w = sca(22)
        for x, y in path_pts:
            a_draw.ellipse(
                (x - stroke_w / 2, y - stroke_w / 2, x + stroke_w / 2, y + stroke_w / 2),
                fill=CREAM,
            )

        # Sun
        a_draw.ellipse(
            (sca(200 - 26), sca(76 - 26), sca(200 + 26), sca(76 + 26)),
            fill=CORAL,
        )

        bg.paste(art, (art_offset, art_offset), art)
    else:
        d = ImageDraw.Draw(bg)

        # Sun glow
        glow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        ImageDraw.Draw(glow).ellipse(
            (sc(200 - 48), sc(76 - 48), sc(200 + 48), sc(76 + 48)),
            fill=CORAL_GLOW,
        )
        glow = glow.filter(ImageFilter.GaussianBlur(radius=sc(6)))
        bg = Image.alpha_composite(bg, glow)
        d = ImageDraw.Draw(bg)

        # Pathway
        path_pts = cubic_bezier(
            (sc(44), sc(196)),
            (sc(108), sc(196)),
            (sc(118), sc(132)),
            (sc(200), sc(76)),
            steps=240,
        )
        stroke_w = sc(22)
        for x, y in path_pts:
            d.ellipse(
                (x - stroke_w / 2, y - stroke_w / 2, x + stroke_w / 2, y + stroke_w / 2),
                fill=CREAM,
            )

        # Sun
        d.ellipse(
            (sc(200 - 26), sc(76 - 26), sc(200 + 26), sc(76 + 26)),
            fill=CORAL,
        )

    return bg.resize((size, size), Image.LANCZOS)


def main() -> None:
    out = Path(__file__).resolve().parent.parent / "public" / "icons"
    out.mkdir(parents=True, exist_ok=True)

    make_icon(192, maskable=True).save(out / "icon-192.png", optimize=True)
    make_icon(512, maskable=True).save(out / "icon-512.png", optimize=True)
    # Apple touch icon prefers full-bleed (no maskable padding)
    make_icon(180, maskable=False).save(out / "apple-touch-icon.png", optimize=True)

    print(f"wrote: {out / 'icon-192.png'}")
    print(f"wrote: {out / 'icon-512.png'}")
    print(f"wrote: {out / 'apple-touch-icon.png'}")


if __name__ == "__main__":
    main()
