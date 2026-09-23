"""Write the reference snapshots folder_regression_test.py compares against.

    python unit_tests/make_reference.py

They were made from the code as it was before live input was added (commit
b83b180), on sample_data. Run this again only to accept a deliberate change to
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
        empty_library = tmp / "empty_library"
        empty_library.mkdir()

        plain = reference.run_folder(reference.SAMPLE_DATA, tmp / "plain", empty_library)
        reference.save("folder_sample_data", {"versions": reference.versions(), **plain})

        mite = next(m for m in plain["results"]["mites"] if m["id"] == reference.REJECTED_MITE)
        library = reference.write_library(tmp / "library", reference.SAMPLE_DATA, mite)
        labelled = reference.run_folder(reference.SAMPLE_DATA, tmp / "labelled", library, reference.LABELS)
        reference.save("folder_sample_data_labelled", {"versions": reference.versions(), "rejected": mite, **labelled})

        small = reference.make_small_session(tmp / "small_session")
        stdout = reference.run_cli([small, tmp / "cli_out"], {small: "<DATA>", tmp / "cli_out": "<OUT>"})
        reference.save("cli_small_session", {"versions": reference.versions(), "stdout": stdout, **reference.outputs(tmp / "cli_out")})
    print(f"Reference written to {reference.REFERENCE_DIR}")


if __name__ == "__main__":
    main()
