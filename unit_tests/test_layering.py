"""Guards the boundary between the user interface and the analysis code.

Dependencies must point one way:  web/ -> pipeline.py -> classes/

These tests read the imports rather than the behaviour, so they fail the moment
someone reaches across the boundary -- which is the point.
"""

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# The analysis libraries. If the web layer imports one of these, it has started
# doing analysis itself instead of calling pipeline.
ANALYSIS_MODULES = {"cv2", "numpy", "pandas", "matplotlib", "classes", "reporting"}

# The web libraries. If the analysis imports one of these, it has grown an
# opinion about HTTP and can no longer run from the command line.
WEB_MODULES = {"fastapi", "uvicorn", "starlette", "pydantic"}


def imported_roots(path):
    """Top-level names of every module imported by a Python file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


def test_web_layer_does_no_analysis():
    """web/ may import pipeline, and nothing else from the project."""
    for path in (ROOT / "web").rglob("*.py"):
        offenders = imported_roots(path) & ANALYSIS_MODULES
        assert not offenders, (
            f"{path.name} imports {sorted(offenders)}. The web layer must go through "
            f"pipeline.py instead of touching the analysis directly."
        )


@pytest.mark.parametrize(
    "path",
    [ROOT / "pipeline.py", ROOT / "reporting.py", ROOT / "main.py", *(ROOT / "classes").glob("*.py")],
    ids=lambda p: p.name,
)
def test_analysis_knows_nothing_about_http(path):
    """The analysis must stay runnable with no server involved."""
    offenders = imported_roots(path) & WEB_MODULES
    assert not offenders, (
        f"{path.name} imports {sorted(offenders)}. Analysis code must not depend on "
        f"the web layer, or the command line stops working."
    )


def test_pipeline_is_the_only_entry_point():
    """The two functions the interface is allowed to call both exist."""
    import pipeline

    assert callable(pipeline.open_session)
    assert callable(pipeline.run_analysis)


def test_no_remote_resources_in_the_page():
    """Every asset is local, so the app works with no network."""
    for path in (ROOT / "web" / "static").rglob("*"):
        if path.suffix in {".html", ".css", ".js"}:
            # XML namespace names look like URLs but are never fetched.
            text = path.read_text(encoding="utf-8").replace("http://www.w3.org/2000/svg", "")
            assert "https://" not in text and "http://" not in text, (
                f"{path.name} refers to a remote resource; it would break offline."
            )
