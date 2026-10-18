#!/usr/bin/env python3
"""Landing media pipeline (P33-A, D43.4/D43.5): modern formats with known sizes.

The landing serves pre-generated AVIF/WebP files from `public/media/` instead of
`next/image` runtime optimisation: the VPS release artifact then needs no native
`sharp` build, and every file has a fixed, cacheable URL. Files in
`public/media/` are served `immutable` for a year (next.config.ts), so NEVER
overwrite one — write a new name (`-v2`, `-v3`, …) and update the reference.

Usage (Pillow >= 11.2 with AVIF + WebP; the repo venv has it):

    # one image -> <out>-<width>.avif / .webp per width, prints width/height
    python apps/landing/scripts/media.py optimize screenshot.png \
        --out apps/landing/public/media/phan-tich-shop-overview-v1 --widths 640,1280

    # regenerate the brand assets this script owns (OG image, logo, favicon, poster)
    python apps/landing/scripts/media.py brand

    # P34-A: the bird glyph for the header/footer/hero (AVIF + WebP, 64/96 wide)
    python apps/landing/scripts/media.py glyph

    # P34-A: taller, narrower mobile crops of the cap-* screenshots (MOBILE_CROPS)
    python apps/landing/scripts/media.py mobile-crops

    # P48-H: a blog hero rendered by juli-content-engine (BlogHero still) ->
    # public/media/blog-hero-<slug>-v1-{600,1200}.avif/.webp + -og.png
    python apps/landing/scripts/media.py blog-hero <slug>-hero.png <slug>-og.png \
        --name hero-<slug>-v1

Hex colours are allowed here (a build script, not `src/`); they mirror
`@juli/theme` tokens.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

LANDING = Path(__file__).resolve().parents[1]
REPO = LANDING.parents[1]
BRAND_ASSETS = REPO / "packages" / "brand" / "assets"
PUBLIC = LANDING / "public"

FONT_BOLD = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
FONT_REGULAR = "/System/Library/Fonts/Supplemental/Arial.ttf"

PRIMARY = (248, 107, 165)
PINK_LIGHT = (250, 165, 196)
PRIMARY_SOFT = (254, 245, 246)
FOREGROUND = (10, 10, 10)
MUTED = (98, 98, 107)
PRIMARY_TEXT = (176, 56, 106)


def save_modern(image: Image.Image, out_stem: Path, width: int) -> tuple[int, int]:
    """Resize to `width` (never upscale) and write `<stem>-<width>.avif` + `.webp`."""
    if image.width > width:
        height = round(image.height * width / image.width)
        image = image.resize((width, height), Image.Resampling.LANCZOS)
    out_stem.parent.mkdir(parents=True, exist_ok=True)
    base = f"{out_stem}-{image.width}"
    image.save(f"{base}.avif", quality=60)
    image.save(f"{base}.webp", quality=80, method=6)
    return image.size


def optimize(src: Path, out_stem: Path, widths: list[int]) -> None:
    image = Image.open(src)
    image = image.convert("RGBA" if image.mode in ("RGBA", "LA", "P") else "RGB")
    for width in widths:
        w, h = save_modern(image, out_stem, width)
        print(f"{out_stem.name}-{w}.avif/.webp  width={w} height={h}")


HERO_SIZE = (2400, 1350)
OG_SIZE = (1200, 630)


def blog_hero(hero: Path, og: Path, name: str) -> None:
    """Blog cover from a BlogHero render: 600/1200 AVIF + WebP (16:9) and the OG PNG.

    Refuses wrong sizes and never overwrites (files in public/media are immutable).
    """
    for src, size in ((hero, HERO_SIZE), (og, OG_SIZE)):
        with Image.open(src) as image:
            if image.size != size:
                raise SystemExit(
                    f"{src}: expected {size[0]}x{size[1]}, got {image.width}x{image.height}"
                )
    stem = PUBLIC / "media" / f"blog-{name}"
    existing = sorted(stem.parent.glob(f"{stem.name}-*"))
    if existing:
        raise SystemExit(f"{stem.name}: already exists ({existing[0].name}); bump -vN")
    optimize(hero, stem, [600, 1200])
    with Image.open(og) as image:
        image.convert("RGB").save(f"{stem}-og.png", optimize=True)
    print(f"{stem.name}-og.png  width={OG_SIZE[0]} height={OG_SIZE[1]}")


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


def og_image(dest: Path) -> None:
    """The default 1200x630 Open Graph / Twitter card image."""
    width, height = 1200, 630
    canvas = Image.new("RGB", (width, height), PRIMARY_SOFT)
    draw = ImageDraw.Draw(canvas)
    # Brand gradient band on the right (135deg primary -> pink-light).
    band = Image.new("RGB", (420, height))
    band_draw = ImageDraw.Draw(band)
    for y in range(height):
        t = y / (height - 1)
        colour = tuple(round(PRIMARY[i] + (PINK_LIGHT[i] - PRIMARY[i]) * t) for i in range(3))
        band_draw.line([(0, y), (420, y)], fill=colour)
    canvas.paste(band, (width - 420, 0))

    glyph = Image.open(BRAND_ASSETS / "bird-glyph.png").convert("RGBA")
    glyph_h = 300
    glyph = glyph.resize(
        (round(glyph.width * glyph_h / glyph.height), glyph_h), Image.Resampling.LANCZOS
    )
    # White silhouette of the bird: readable on the pink band.
    white = Image.new("RGBA", glyph.size, (255, 255, 255, 255))
    white.putalpha(glyph.getchannel("A"))
    glyph = white
    canvas.paste(glyph, (width - 210 - glyph.width // 2, (height - glyph_h) // 2), glyph)

    logo = Image.open(BRAND_ASSETS / "logo-wordmark.png").convert("RGBA")
    logo_h = 84
    logo = logo.resize((round(logo.width * logo_h / logo.height), logo_h), Image.Resampling.LANCZOS)
    canvas.paste(logo, (72, 72), logo)

    # D46 (P35): positioning is e-commerce (TMĐT); only TikTok Shop is connected today.
    draw.text((72, 210), "Trợ lý AI vận hành", font=_font(FONT_BOLD, 52), fill=FOREGROUND)
    draw.text((72, 276), "cho nhà bán TMĐT", font=_font(FONT_BOLD, 52), fill=FOREGROUND)
    draw.text(
        (72, 382),
        "Phân tích shop · Đề xuất hành động · Đo GMV",
        font=_font(FONT_REGULAR, 30),
        fill=MUTED,
    )
    draw.text(
        (72, 430),
        "Hiện kết nối TikTok Shop · Shopee đang tích hợp",
        font=_font(FONT_REGULAR, 26),
        fill=MUTED,
    )
    draw.text((72, 520), "app-juli.com", font=_font(FONT_BOLD, 34), fill=PRIMARY_TEXT)
    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest, optimize=True)
    print(f"{dest.relative_to(LANDING)}  1200x630")


def brand() -> None:
    # New name, never an overwrite (cached); v1 kept for old shares.
    og_image(PUBLIC / "og" / "juli-ai-default-v2.png")

    # Header/footer logo: 2x of the 30px header height, WebP only (tiny file).
    logo = Image.open(BRAND_ASSETS / "logo-wordmark.png").convert("RGBA")
    logo_h = 60
    logo = logo.resize((round(logo.width * logo_h / logo.height), logo_h), Image.Resampling.LANCZOS)
    logo_path = PUBLIC / "media" / "juli-logo-wordmark-v1.webp"
    logo_path.parent.mkdir(parents=True, exist_ok=True)
    logo.save(logo_path, quality=90, method=6)
    print(f"{logo_path.relative_to(LANDING)}  {logo.width}x{logo.height}")

    # Favicon + app icons (Next file conventions in src/app).
    glyph = Image.open(BRAND_ASSETS / "bird-glyph.png").convert("RGBA")
    side = max(glyph.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(glyph, ((side - glyph.width) // 2, (side - glyph.height) // 2), glyph)
    square.save(LANDING / "src" / "app" / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    square.resize((192, 192), Image.Resampling.LANCZOS).save(
        LANDING / "src" / "app" / "icon.png", optimize=True
    )
    apple = Image.new("RGBA", (180, 180), (255, 255, 255, 255))
    small = square.resize((150, 150), Image.Resampling.LANCZOS)
    apple.paste(small, (15, 15), small)
    apple.convert("RGB").save(LANDING / "src" / "app" / "apple-icon.png", optimize=True)
    print("src/app/favicon.ico, icon.png (192), apple-icon.png (180)")
    # Organization logo for JSON-LD: square, >= 112px, stable URL.
    square.resize((512, 512), Image.Resampling.LANCZOS).save(
        PUBLIC / "media" / "juli-ai-logo-512-v1.png", optimize=True
    )
    print("public/media/juli-ai-logo-512-v1.png  512x512")

    # Hero video poster (D43.6: the poster is the LCP candidate once P33-B ships it).
    optimize(
        PUBLIC / "videos" / "juli-demo-poster.jpg",
        PUBLIC / "media" / "juli-demo-poster-v1",
        [640, 1280],
    )


def glyph() -> None:
    """Bird glyph (D44.3, the site's single flourish + logo mark): 64 / 96 px wide.

    Rendered at 30x26 (header), 28x25 (footer) and 44x39 (hero flourish); the
    two widths cover those at 2x. Alpha is kept (AVIF + WebP both support it).
    """
    optimize(BRAND_ASSETS / "bird-glyph.png", PUBLIC / "media" / "bird-glyph-v1", [64, 96])


# Mobile crops (D44.3 "mobile gets its own crops"): the 1280-wide cap-* shots
# shrink to ~28 % at a 390 px viewport, where their UI text is unreadable. Each
# entry crops a narrower, taller region (fractions of the source: left, top,
# right, bottom) around the point of the shot. The originals are not in the
# repo, so the crops come from the largest published WebP (DEBT, P34-A).
# Shots whose text is already large (dialogs and cards captured at 2x:
# dx-hang-cho, dx-hoan-tac, dx-tu-choi, dx-seller-center, dx-the, kn-ghi) need
# no crop and are not listed.
MOBILE_CROPS: dict[str, tuple[float, float, float, float]] = {
    "cap-dl-tin-cay-v1-1280": (0.0, 0.0, 0.5, 1.0),
    "cap-dx-xac-nhan-v1-1280": (0.0, 0.0, 0.5, 0.55),
    "cap-kn-dang-nhap-v1-1280": (0.06, 0.0, 0.52, 0.8),
    "cap-kn-ket-noi-v1-1280": (0.06, 0.0, 0.55, 0.95),
    "cap-kn-quet-nhanh-v1-1280": (0.07, 0.05, 0.55, 1.0),
    "cap-pt-khuyen-mai-v1-1280": (0.0, 0.0, 0.55, 1.0),
    "cap-pt-lich-sale-v1-1280": (0.0, 0.0, 0.6, 1.0),
    "cap-pt-pheu-v1-1280": (0.0, 0.0, 0.6, 1.0),
    # P49-S (D59 additions 5): fresh sample-shop shots for the Juli guide posts. The v2 crops
    # come from the v2 file's own largest WebP; the v1 crops above are untouched.
    "cap-kn-quet-nhanh-v2-1280": (0.07, 0.08, 0.6, 1.0),
    "cap-pt-nghen-v2-1280": (0.0, 0.38, 0.7, 1.0),
    # P49-F: recaptures after the demo copy fixes replace the v2 sign-in and day-14 entries (files
    # removed, never referenced by a page). cap-kn-dang-nhap-m-v3 is not listed: it was cut
    # from the 2x raw capture (box 0.08, 0.13, 0.44, 0.80), since the 1280 WebP is 1x for that shot.
    # P51-A (D60.1): the sample's title run now targets CTR on Thẻ sản phẩm, CTOR cards read
    # "CTOR" (all channels), the Kéo xuống rows + Còn lại add up to Tổng; one capture clock, so
    # every dated shot reads 10/10 -> 17/10 -> 24/10. Same framing as the shots they replace, whose
    # files and entries are removed. cap-dx-the-v4 is still the P35 home hero on phones: the card
    # header only (SKU, CTOR before → after, GMV dự kiến), so the H1 remains the mobile LCP element.
    "cap-dl-hoc-v2-1280": (0.0, 0.0, 0.5, 1.0),
    "cap-dl-muc-tieu-v2-1280": (0.0, 0.0, 0.62, 1.0),
    "cap-dl-ngay-14-v5-1280": (0.0, 0.0, 0.62, 1.0),
    "cap-dl-ngay-7-v4-1280": (0.0, 0.35, 0.62, 1.0),
    "cap-dl-tang-them-v2-1280": (0.0, 0.0, 0.82, 1.0),
    "cap-dx-luot-chay-v2-1280": (0.0, 0.0, 0.5, 0.75),
    "cap-dx-the-v4-1184": (0.0, 0.0, 1.0, 0.285),
    "cap-pt-nghen-v3-1280": (0.3, 0.0, 0.98, 1.0),
    "cap-pt-xep-hang-v2-1280": (0.0, 0.0, 0.72, 1.0),
    "cap-dl-ngay-7-v3-1280": (0.0, 0.66, 0.95, 0.93),
    "cap-dl-ngay-14-v4-1280": (0.0, 0.8, 0.75, 0.94),
    "cap-pt-luong-v2-1280": (0.07, 0.25, 0.6, 1.0),
    "cap-dx-quy-tac-v2-1280": (0.0, 0.0, 0.5, 0.64),
}

#: Mobile crops are written at most this wide: ~2x of a 358 px column.
MOBILE_CROP_MAX_WIDTH = 720


def mobile_crops() -> None:
    """Write `<stem>-m-vN-<width>.avif/.webp` for every MOBILE_CROPS entry (`<stem>-vN-<w>`)."""
    media = PUBLIC / "media"
    for name, (left, top, right, bottom) in MOBILE_CROPS.items():
        source = Image.open(media / f"{name}.webp").convert("RGB")
        box = (
            round(source.width * left),
            round(source.height * top),
            round(source.width * right),
            round(source.height * bottom),
        )
        crop = source.crop(box)
        match = re.fullmatch(r"(.+)-(v\d+)-\d+", name)
        if match is None:
            raise ValueError(f"MOBILE_CROPS key must look like <stem>-vN-<width>: {name}")
        stem, version = match.groups()
        if any(media.glob(f"{stem}-m-{version}-*")):
            continue  # published crops are cached immutable: never overwrite one
        w, h = save_modern(crop, media / f"{stem}-m-{version}", MOBILE_CROP_MAX_WIDTH)
        print(f"{stem}-m-{version}-{w}.avif/.webp  width={w} height={h}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    opt = sub.add_parser("optimize", help="write AVIF + WebP variants of one image")
    opt.add_argument("src", type=Path)
    opt.add_argument(
        "--out", type=Path, required=True, help="output path stem, e.g. public/media/foo-v1"
    )
    opt.add_argument("--widths", default="640,1280", help="comma-separated target widths")
    sub.add_parser("brand", help="regenerate OG image, logo, favicon and poster")
    sub.add_parser("glyph", help="write the bird glyph (AVIF + WebP, 64/96 px)")
    sub.add_parser("mobile-crops", help="write the cap-* mobile crops (MOBILE_CROPS)")
    hero = sub.add_parser("blog-hero", help="blog cover variants + OG from a BlogHero render")
    hero.add_argument("hero", type=Path, help="<slug>-hero.png, 2400x1350")
    hero.add_argument("og", type=Path, help="<slug>-og.png, 1200x630")
    hero.add_argument("--name", required=True, help="cover name, e.g. hero-<slug>-v1")
    args = parser.parse_args()
    if args.command == "optimize":
        optimize(args.src, args.out, [int(w) for w in args.widths.split(",")])
    elif args.command == "glyph":
        glyph()
    elif args.command == "mobile-crops":
        mobile_crops()
    elif args.command == "blog-hero":
        blog_hero(args.hero, args.og, args.name)
    else:
        brand()


if __name__ == "__main__":
    main()
