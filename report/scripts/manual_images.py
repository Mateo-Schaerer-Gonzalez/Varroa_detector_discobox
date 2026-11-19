"""The user manual's screenshots, from what report/scripts/manual_screenshots.mjs
took: each that the manual shows written to report/images/man_<name>.png, cut to 256 colours as
scripts/readme_images.py does (small, and looks the same), and the plate shake of a
calm and of a shaky run side by side.

    python report/scripts/manual_images.py <the screenshots' folder>
"""
import argparse
import re
from pathlib import Path

from matplotlib import font_manager
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
IMAGES = ROOT / "report" / "images"
# the two plate shake charts, with the titles the manual gives them
SHAKE = (("results_shake", "Low plate shake: sample_data, under 0.1 px throughout"),
         ("real_shake_high", "High plate shake: a 49-hour run, 0.15 to 0.24 px from about 1,230 min on"))


def save(image, path):
    image.convert("RGB").quantize(256, method=Image.Quantize.MEDIANCUT).save(path, optimize=True)
    print("  wrote", path.relative_to(ROOT))


def stacked(shots, pairs):
    """Pictures one above the other, each under its title."""
    pictures = [Image.open(shots / f"{name}.png").convert("RGB") for name, _title in pairs]
    font = ImageFont.truetype(font_manager.findfont("DejaVu Sans:bold"), 17)   # matplotlib's own font
    title_height, gap = 30, 16
    width = max(p.width for p in pictures)
    out = Image.new("RGB", (width, sum(p.height + title_height + gap for p in pictures)), "#ffffff")
    draw = ImageDraw.Draw(out)
    y = 0
    for picture, (_name, title) in zip(pictures, pairs):
        draw.text((12, y + 6), title, fill="#111", font=font)
        out.paste(picture, (0, y + title_height))
        y += picture.height + title_height + gap
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("shots", type=Path, help="the folder report/scripts/manual_screenshots.mjs wrote")
    args = parser.parse_args()
    # only those the manual shows
    shown = set(re.findall(r"images/(man_[a-z0-9_]+)\.png", (ROOT / "report" / "1_user_manual.md").read_text(encoding="utf-8")))
    for path in sorted(args.shots.glob("*.png")):
        if f"man_{path.stem}" in shown:
            save(Image.open(path), IMAGES / f"man_{path.stem}.png")
    if all((args.shots / f"{name}.png").is_file() for name, _title in SHAKE):
        save(stacked(args.shots, SHAKE), IMAGES / "man_shake_low_high.png")


if __name__ == "__main__":
    main()
