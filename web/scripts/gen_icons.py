"""Generate Pathways PWA icons.

Renders icon-192.png, icon-512.png, and apple-touch-icon.png with the same
visual identity as favicon.svg: a deep forest-green rounded-square background,
a warm cream stem-plus-two-leaves sprout rising from a baseline, and a
marigold bud at the tip with a soft glow.

We draw at 4x resolution and downsample for clean edges without needing
an external SVG renderer.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

# Palette E: Forest Green + Marigold + warm cream
FOREST = (31, 74, 44, 255)
FOREST_DEEP = (19, 48, 24, 255)
CREAM = (250, 246, 232, 255)
CREAM_SOFT = (250, 246, 232, 115)  # opacity ~0.45 for soil line
MARIGOLD = (236, 177, 59, 255)
MARIGOLD_GLOW = (236, 177, 59, 48)  # opacity ~0.18 for halo


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


def draw_sprout(art: Image.Image, scale_fn) -> None:
    """Draw the sprout (soil + stem + two leaves + bud + glow) into `art`.

    `scale_fn` maps the 256-viewBox coordinate space to pixel coordinates
    for the target image. The caller controls the size of `art`.
    """
    s = scale_fn

    # Soft marigold halo behind the bud (separate gaussian-blurred layer for
    # an actual glow, then composited).
    glow_layer = Image.new("RGBA", art.size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_layer)
    glow_draw.ellipse(
        (s(128 - 38), s(84 - 38), s(128 + 38), s(84 + 38)),
        fill=MARIGOLD_GLOW,
    )
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(radius=s(6)))
    art.alpha_composite(glow_layer)

    d = ImageDraw.Draw(art)

    # Soil line: faint cream line across the bottom.
    soil_w = max(2, int(s(4)))
    d.line(
        [(s(56), s(206)), (s(200), s(206))],
        fill=CREAM_SOFT,
        width=soil_w,
    )

    # Stem: thick cream vertical line.
    stem_w = max(4, int(s(8)))
    d.line(
        [(s(128), s(206)), (s(128), s(92))],
        fill=CREAM,
        width=stem_w,
    )
    # Round the stem ends (PIL line ends are square by default).
    cap_r = stem_w / 2
    d.ellipse(
        (s(128) - cap_r, s(206) - cap_r, s(128) + cap_r, s(206) + cap_r),
        fill=CREAM,
    )
    d.ellipse(
        (s(128) - cap_r, s(92) - cap_r, s(128) + cap_r, s(92) + cap_r),
        fill=CREAM,
    )

    # Left leaf: closed cubic bezier outline filled cream.
    left_outer = cubic_bezier(
        (s(128), s(156)),
        (s(100), s(152)),
        (s(76), s(132)),
        (s(70), s(100)),
        steps=120,
    )
    left_inner = cubic_bezier(
        (s(70), s(100)),
        (s(100), s(110)),
        (s(124), s(128)),
        (s(128), s(156)),
        steps=120,
    )
    d.polygon(left_outer + left_inner, fill=CREAM)

    # Right leaf: mirror.
    right_outer = cubic_bezier(
        (s(128), s(140)),
        (s(156), s(136)),
        (s(180), s(116)),
        (s(186), s(84)),
        steps=120,
    )
    right_inner = cubic_bezier(
        (s(186), s(84)),
        (s(156), s(94)),
        (s(132), s(112)),
        (s(128), s(140)),
        steps=120,
    )
    d.polygon(right_outer + right_inner, fill=CREAM)

    # Bud: filled marigold circle at the tip of the stem.
    d.ellipse(
        (s(128 - 14), s(84 - 14), s(128 + 14), s(84 + 14)),
        fill=MARIGOLD,
    )


def make_icon(size: int, maskable: bool = False) -> Image.Image:
    """Render the Pathways icon at `size` pixels.

    If maskable=True, draw the artwork inside the safe inner 80% so Android
    can crop to circle/squircle without losing the mark.
    """
    scale = 4
    s = size * scale

    # Background: rounded square with a subtle vertical gradient (forest to
    # deeper forest at the bottom).
    bg = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    grad = Image.new("RGBA", (s, s), FOREST)
    grad_draw = ImageDraw.Draw(grad)
    for i in range(s):
        col = lerp(FOREST, FOREST_DEEP, i / max(1, s - 1))
        grad_draw.line([(0, i), (s, i)], fill=col)
    mask = Image.new("L", (s, s), 0)
    radius = int(s * (56 / 256))
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, s - 1, s - 1), radius=radius, fill=255
    )
    bg.paste(grad, (0, 0), mask)

    if maskable:
        art_size = int(s * 0.80)
        art_offset = (s - art_size) // 2
        art = Image.new("RGBA", (art_size, art_size), (0, 0, 0, 0))

        def sca(v: float) -> float:
            return v * (art_size / 256)

        draw_sprout(art, sca)
        bg.alpha_composite(art, dest=(art_offset, art_offset))
    else:
        def sc(v: float) -> float:
            return v * (s / 256)

        draw_sprout(bg, sc)

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
