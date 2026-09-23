"""Folder mode must produce exactly what it produced before live input was added.

The reference in unit_tests/reference/ was made by make_reference.py from the code
before that change. Each run here is compared with it in full: the dict
run_analysis() returns, every sheet of results.xlsx, what each figure draws (its
lines, points, bars, texts and limits), the file names, and what the command line
prints. Numbers must be equal to the last digit.

The pixels of the images are compared too, but only with the matplotlib and
OpenCV versions the reference was made with: another version may draw or encode
the same figure a few pixels differently.
"""

from pathlib import Path

import pytest

import reference

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module", autouse=True)
def untouched_sample_data():
    written = [name for name in ("labels.json", "ground_truth.json") if (reference.SAMPLE_DATA / name).exists()]
    if written:
        pytest.skip(f"sample_data now holds {', '.join(written)} (written by the app), which the reference was made without.")


@pytest.fixture(scope="module")
def plain_run(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("plain")
    (tmp / "library").mkdir()
    return reference.run_folder(reference.SAMPLE_DATA, tmp / "out", tmp / "library")


@pytest.fixture(scope="module")
def labelled_run(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("labelled")
    library = reference.write_library(tmp / "library", reference.SAMPLE_DATA, reference.load("folder_sample_data_labelled")["rejected"])
    return reference.run_folder(reference.SAMPLE_DATA, tmp / "out", library, reference.LABELS)


@pytest.fixture(scope="module")
def cli_run(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("cli")
    small = reference.make_small_session(tmp / "small_session")
    stdout = reference.run_cli([small, tmp / "out"], {small: "<DATA>", tmp / "out": "<OUT>"})
    return {"stdout": stdout, **reference.outputs(tmp / "out")}


RUNS = {"folder_sample_data": "plain_run", "folder_sample_data_labelled": "labelled_run"}


def assert_same(expected, actual, what):
    found = reference.differences(expected, actual)
    assert not found, f"{what} differs from the reference:\n  " + "\n  ".join(found)


@pytest.mark.parametrize("name", RUNS)
def test_results_are_unchanged(name, request):
    run = request.getfixturevalue(RUNS[name])
    assert_same(reference.load(name)["results"], run["results"], "The dict run_analysis() returns")


@pytest.mark.parametrize("name", RUNS)
def test_workbook_is_unchanged(name, request):
    run = request.getfixturevalue(RUNS[name])
    expected = reference.load(name)
    assert run["files"] == expected["files"]
    assert_same(expected["excel"], run["excel"], "results.xlsx")


@pytest.mark.parametrize("name", RUNS)
def test_figures_draw_the_same(name, request):
    run = request.getfixturevalue(RUNS[name])
    assert_same(reference.load(name)["figures"], run["figures"], "The figures")


def same_image_libraries(expected):
    current = reference.versions()
    return all(expected["versions"][key] == current[key] for key in ("matplotlib", "opencv"))


@pytest.mark.parametrize("name", RUNS)
def test_images_have_the_same_pixels(name, request):
    expected = reference.load(name)
    if not same_image_libraries(expected):
        pytest.skip(f"reference made with {expected['versions']}, running {reference.versions()}")
    assert_same(expected["pixels"], request.getfixturevalue(RUNS[name])["pixels"], "The image pixels")


def test_command_line_is_unchanged(cli_run):
    expected = reference.load("cli_small_session")
    assert cli_run["stdout"] == expected["stdout"]
    assert cli_run["files"] == expected["files"]
    assert_same(expected["excel"], cli_run["excel"], "The command line's results.xlsx")
    if same_image_libraries(expected):
        assert_same(expected["pixels"], cli_run["pixels"], "The command line's image pixels")
