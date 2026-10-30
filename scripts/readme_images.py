"""The pictures of README.md (docs/images/) and of the reports (report/images/)
that are not drawn by a script of their own: the app's screenshots, cut from
what scripts/readme_screenshots.mjs took, and the figures README.md shares with
the reports, copied and shrunk.

    node scripts/readme_screenshots.mjs <shots> <copy of recordings/sample_data>
    python scripts/visual_walkthrough.py            # report/images/walk_*.png
    python scripts/readme_images.py <shots>

The crops are at the places the pages had on 30 October 2026 (1440 px wide);
look at the pictures after a change to the pages. Screenshots are cut to 256
colours, which keeps them small and looks the same.

The other figures: scripts/benchmark_original.py (docs/images/benchmark_*.png)
and report/scripts/ (the reports' own).
"""
import argparse
from pathlib import Path

from matplotlib import font_manager
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
DOCS, REPORT = ROOT / "docs" / "images", ROOT / "report" / "images"
WIDTH = 1440
# (shot, top, bottom) of each picture: whole width, rows top to bottom
README_SHOTS = {
    "app_labels": ("labels", 0, 820),
    "app_results_top": ("results", 0, 1855),       # the counts, the close calls and the plate map
    "app_zone_top": ("zone", 0, 1060),
    "app_mite": ("mite", 0, 960),
    "app_playback": ("playback", 0, 1080),
    "app_calibration_open": ("cal_open", 0, 1380),
}
REPORT_SHOTS = {
    "app_labels": ("labels", 0, 820),
    "app_results_top": ("results", 0, 770),
    "app_results_platemap": ("results", 775, 1855),
    "app_results_survival": ("results", 1855, 3045),
    "app_results_shake": ("results", 4160, 4555),
    "app_zone_top": ("zone", 0, 1060),
    "app_playback": ("playback", 0, 1080),
    "app_calibration_open": ("cal_open", 0, 1380),
    "app_calibration_truth": ("cal_truth", 0, 980),
    "app_calibration_report": ("cal_report", 0, 1050),
    "app_calibration_test_top": ("cal_test", 0, 1140),
    "app_calibration_test_errors": ("cal_test", 1140, 1985),
}
# the close-up on a mite's page (left, top, right, bottom), and what it shows
CLOSE_UPS = (("mite", (124, 380, 504, 762), "mite 7.1 at 25 min: moving (score 4.3)"),
             ("mite_still", (124, 545, 504, 926), "mite 4.1 at 25 min: still (score 0.008)"))
SHARED = ["walk_1_detection", "walk_2_frames", "walk_3_stabilizer_effect", "walk_5_rays", "walk_6_profile",
          "walk_7_vector_sum", "walk_8_threshold", "walk_9_calibration", "walk_10_survival", "speed_memory_storage"]


def screenshot(image, path):
    image.convert("RGB").quantize(256, method=Image.Quantize.MEDIANCUT).save(path, optimize=True)
    print("  wrote", path.relative_to(ROOT))


def outline_view(shots):
    """Two mites' close-ups side by side: the app's outline view, moving and still."""
    pictures = [Image.open(shots / f"{name}.png").convert("RGB").crop(box) for name, box, _title in CLOSE_UPS]
    title_height, gap = 34, 20
    out = Image.new("RGB", (sum(p.width for p in pictures) + gap * (len(pictures) + 1), pictures[0].height + title_height + gap),
                    "#fcfcfb")
    draw = ImageDraw.Draw(out)
    font = ImageFont.truetype(font_manager.findfont("DejaVu Sans:bold"), 17)   # matplotlib's own font
    x = gap
    for picture, (_name, _box, title) in zip(pictures, CLOSE_UPS):
        draw.text((x, 6), title, fill="#111", font=font)
        out.paste(picture, (x, title_height))
        x += picture.width + gap
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("shots", type=Path, help="the folder scripts/readme_screenshots.mjs wrote")
    args = parser.parse_args()
    shots = {name: Image.open(args.shots / f"{name}.png") for name in {s for s, _a, _b in [*README_SHOTS.values(), *REPORT_SHOTS.values()]}}
    for folder, table in ((DOCS, README_SHOTS), (REPORT, REPORT_SHOTS)):
        for name, (shot, top, bottom) in table.items():
            screenshot(shots[shot].crop((0, top, WIDTH, bottom)), folder / f"{name}.png")
    view = outline_view(args.shots)
    for folder in (DOCS, REPORT):
        screenshot(view, folder / "mite_outline_app.png")
    for name in SHARED:
        Image.open(REPORT / f"{name}.png").save(DOCS / f"{name}.png", optimize=True)
        print("  copied", name)


if __name__ == "__main__":
    main()
