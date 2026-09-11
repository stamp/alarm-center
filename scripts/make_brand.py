"""Generate brand assets for Alarm Center.

Drawn at 4x and downsampled - the cheapest way to get clean edges out of
PIL without vector tooling.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

OUT = Path("/home/claude/alarm-center/custom_components/alarm_center/brand")
OUT.mkdir(parents=True, exist_ok=True)

S = 4

RED = (229, 57, 53, 255)
RED_DARK = (198, 40, 40, 255)
AMBER = (255, 179, 0, 255)
SLATE = (55, 71, 79, 255)
SLATE_DARK = (38, 50, 56, 255)
WHITE = (255, 255, 255, 255)


def draw_icon(px: int) -> Image.Image:
    """A beacon light with an acknowledgement check inside the dome.

    A beacon rather than the bell every notification integration already
    uses, and the check is what makes it an alarm *centre*: somebody signs
    off on it.
    """
    size = px * S
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = size / 256.0

    cx = 128 * u
    dome_cy = 158 * u
    dome_r = 74 * u

    # --- light rays, behind everything, radiating up and outward -------
    for angle in (22, 51, 80, 100, 129, 158):
        a = math.radians(angle)
        r0, r1 = 86 * u, 116 * u
        x1, y1 = cx + math.cos(a) * r0, dome_cy - math.sin(a) * r0
        x2, y2 = cx + math.cos(a) * r1, dome_cy - math.sin(a) * r1
        d.line([(x1, y1), (x2, y2)], fill=AMBER, width=int(12 * u))
        r = 6 * u
        for (rx, ry) in ((x1, y1), (x2, y2)):
            d.ellipse([rx - r, ry - r, rx + r, ry + r], fill=AMBER)

    # --- dome ----------------------------------------------------------
    box = [cx - dome_r, dome_cy - dome_r, cx + dome_r, dome_cy + dome_r]
    # Flat fill: a shading wedge reads as a stray diagonal once the check
    # sits on top of it, and flat matches Home Assistant's own brand icons.
    d.pieslice(box, start=180, end=360, fill=RED)

    # --- acknowledgement check, inside the dome ------------------------
    check = [
        (cx - 34 * u, dome_cy - 36 * u),
        (cx - 11 * u, dome_cy - 14 * u),
        (cx + 36 * u, dome_cy - 62 * u),
    ]
    d.line(check, fill=WHITE, width=int(15 * u), joint="curve")
    r = 7.5 * u
    for (rx, ry) in (check[0], check[2]):
        d.ellipse([rx - r, ry - r, rx + r, ry + r], fill=WHITE)

    # --- housing and base ----------------------------------------------
    d.rounded_rectangle(
        [cx - 80 * u, 156 * u, cx + 80 * u, 186 * u], radius=9 * u, fill=SLATE
    )
    d.rounded_rectangle(
        [cx - 96 * u, 191 * u, cx + 96 * u, 221 * u], radius=12 * u, fill=SLATE_DARK
    )

    return img.resize((px, px), Image.LANCZOS)


def draw_logo(width: int, height: int) -> Image.Image:
    """Icon plus wordmark."""
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    icon = draw_icon(height)
    img.paste(icon, (0, 0), icon)

    d = ImageDraw.Draw(img)
    font = None
    for candidate in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ):
        if Path(candidate).exists():
            font = ImageFont.truetype(candidate, int(height * 0.32))
            break
    if font is None:
        font = ImageFont.load_default()

    text = "Alarm Center"
    bbox = d.textbbox((0, 0), text, font=font)
    ty = (height - (bbox[3] + bbox[1])) // 2
    d.text((int(height * 0.94), ty), text, font=font, fill=SLATE_DARK)
    return img


draw_icon(256).save(OUT / "icon.png")
draw_icon(512).save(OUT / "icon@2x.png")
draw_logo(512, 128).save(OUT / "logo.png")
draw_logo(1024, 256).save(OUT / "logo@2x.png")
print("done")
