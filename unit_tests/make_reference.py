"""Write the reference snapshots folder_regression_test.py compares against.

    python unit_tests/make_reference.py

They were made from the code as it was before live input was added (commit
b83b180), on sample_data, and made again when the frames became grey
(2026-10-15): the brightness changed in its 7th digit, as float32 averages one
channel instead of three, and preview.jpg became a grey JPEG; every call,
count and figure stayed. Made again when the stabilizer began to follow each
mite's own centre (2026-10-16): scores moved by 0.005 in the median and 0.99
at most, no call changed, and the plate drift (activity movers) moved by
hundredths of a pixel. It writes the reference of the OpenCV it runs with
(reference.py: one for OpenCV 4, one for 5), so run it in both Pythons; the
OpenCV 5 one was first made from commit 76dba5e. Run this again only to accept a deliberate change to
what folder mode produces, and say why in the commit.
"""

import sys
import tempfile
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parent.parent), str(Path(__file__).resolve().parent)]

import reference  # noqa: E402


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        plain = reference.run_folder(reference.SAMPLE_DATA, tmp / "plain")
        reference.save("folder_sample_data", {"versions": reference.versions(), **plain})

        mite = next(m for m in plain["results"]["mites"] if m["id"] == reference.REJECTED_MITE)
        marked = reference.marked_copy(tmp / "sample_data", reference.SAMPLE_DATA, mite)
        labelled = reference.run_folder(marked, tmp / "labelled", reference.LABELS)
        reference.save("folder_sample_data_labelled", {"versions": reference.versions(), "rejected": mite, **labelled})

        small = reference.make_small_session(tmp / "small_session")
        stdout = reference.run_cli([small, tmp / "cli_out"], {small: "<DATA>", tmp / "cli_out": "<OUT>"})
        reference.save("cli_small_session", {"versions": reference.versions(), "stdout": stdout, **reference.outputs(tmp / "cli_out")})
    print(f"Reference written to {reference.REFERENCE_DIR}")


if __name__ == "__main__":
    main()
