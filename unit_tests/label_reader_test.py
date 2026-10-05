"""The names written beside the plates, read by Google Gemini: what is sent, what
is made of the answer, and which plates the label page gets a name for. Google is
never called here; a stand-in answers."""

import base64
import json

import cv2
import numpy as np
import pytest
import yaml

import pipeline
import reference
from classes import app_config, label_reader
from classes.app_config import LabelReaderConfig
from classes.label_reader import LabelReader, LabelReadError
from classes.rect import TextZone


def answer(names):
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(names)}]}}]}


class Gemini:
    """Stands in for Google: keeps what it was sent and answers `names`."""

    def __init__(self, names):
        self.names = names
        self.sent = []

    def __call__(self, url, headers, body, timeout):
        self.sent.append((url, headers, body))
        return answer(self.names) if isinstance(self.names, list) else self.names


FRAME = np.full((300, 400, 3), 200, dtype=np.uint8)
AREAS = [TextZone(10, 10, 110, 90), TextZone(10, 110, 110, 190)]


# --- the reader

def test_one_name_comes_back_for_each_area():
    gemini = Gemini(["Alive", ""])
    assert LabelReader(api_key="k", model="some-model", send=gemini).read(FRAME, AREAS) == ["Alive", ""]
    [(url, headers, body)] = gemini.sent
    assert url.endswith("/models/some-model:generateContent") and headers == {"x-goog-api-key": "k"}
    pictures = [part["inline_data"] for part in body["contents"][0]["parts"] if "inline_data" in part]
    assert len(pictures) == 2 and pictures[0]["mime_type"] == "image/jpeg"
    assert body["generationConfig"]["responseMimeType"] == "application/json"


def test_an_area_is_sent_with_its_margin_and_enlarged():
    reader = LabelReader(api_key="k", send=Gemini([""]))
    reader.read(FRAME, AREAS[:1])
    picture = reader._send.sent[0][2]["contents"][0]["parts"][1]["inline_data"]["data"]
    image = cv2.imdecode(np.frombuffer(base64.b64decode(picture), np.uint8), cv2.IMREAD_COLOR)
    # 100 x 80 with 15 % around it, cut at the picture's edge: 125 x 102, made 400 high.
    assert image.shape[0] == LabelReader.MIN_HEIGHT and image.shape[1] == pytest.approx(125 * 400 / 102, abs=2)


def test_the_names_of_the_other_plates_are_given_to_spell_alike():
    gemini = Gemini(["venom 2x"])
    LabelReader(api_key="k", send=gemini).read(FRAME, AREAS[:1], known=["venom 2x"])
    assert '["venom 2x"]' in gemini.sent[0][2]["contents"][0]["parts"][-1]["text"]


def test_spaces_around_and_within_a_name_are_tidied():
    assert LabelReader(api_key="k", send=Gemini(["  venom\n2x ", None])).read(FRAME, AREAS) == ["venom 2x", ""]


def test_nothing_is_asked_without_areas():
    gemini = Gemini([])
    assert LabelReader(api_key="k", send=gemini).read(FRAME, []) == []
    assert gemini.sent == []


@pytest.mark.parametrize("reply", [answer(["only one"]), answer({"a": 1}), {"candidates": []},
                                   {"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}])
def test_an_answer_that_is_not_one_name_per_area_is_an_error(reply):
    with pytest.raises(LabelReadError):
        LabelReader(api_key="k", send=Gemini(reply)).read(FRAME, AREAS)


def test_a_busy_google_is_asked_again():
    replies = [LabelReadError("busy", 503), LabelReadError("busy", 503), answer(["Alive", ""])]
    waits = []

    def send(url, headers, body, timeout):
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    assert LabelReader(api_key="k", send=send, wait=waits.append).read(FRAME, AREAS) == ["Alive", ""]
    assert waits == [LabelReader.RETRY_WAIT] * 2


def test_a_refusal_that_is_not_busy_is_not_asked_again():
    calls = []

    def send(url, headers, body, timeout):
        calls.append(1)
        raise LabelReadError("API key not valid", 400)

    with pytest.raises(LabelReadError, match="not valid"):
        LabelReader(api_key="k", send=send, wait=lambda seconds: None).read(FRAME, AREAS)
    assert len(calls) == 1


def test_without_a_key_it_says_where_to_put_one(monkeypatch):
    monkeypatch.setattr(LabelReader, "saved_key", staticmethod(lambda: None))
    with pytest.raises(LabelReadError, match="GEMINI_API_KEY"):
        LabelReader(send=Gemini([""])).read(FRAME, AREAS)


def test_the_key_is_read_from_the_environment_or_the_env_file(tmp_path, monkeypatch):
    for name in label_reader.KEY_NAMES:
        monkeypatch.delenv(name, raising=False)
    env = tmp_path / ".env"
    assert LabelReader.saved_key(env) is None
    env.write_text('# the key\nOTHER=1\nGEMINI_API_KEY = "from-file"\n', encoding="utf-8")
    assert LabelReader.saved_key(env) == "from-file"
    monkeypatch.setenv("GEMINI_API_KEY", "from-environment")
    assert LabelReader.saved_key(env) == "from-environment"


# --- the label page

@pytest.fixture
def opened(tmp_path, monkeypatch):
    """A small session opened as the label page does, with Google answering
    "plate 1", "plate 2", ... for the areas it is sent."""
    data_dir = reference.make_small_session(tmp_path / "small_session")
    out_dir = tmp_path / "out"
    session = pipeline.open_session(data_dir, out_dir, library_dir=tmp_path / "library")
    asked = []

    class Reader:
        def __init__(self, model=None):
            pass

        def read(self, frame, areas, known=()):
            asked.append((list(areas), list(known)))
            return [f"plate {number}" for number, _area in enumerate(areas, start=1)]

    monkeypatch.setattr(pipeline, "LabelReader", Reader)
    return data_dir, out_dir, session, asked


def test_the_plates_with_mites_and_no_name_get_one(opened):
    data_dir, out_dir, session, asked = opened
    with_mites = sorted({mite["zone_id"] for mite in session["mites"]})
    assert len(with_mites) >= 2
    labels = pipeline.read_labels(data_dir, out_dir, session["mites"])
    assert sorted(labels, key=int) == [str(zone) for zone in with_mites]
    assert len(asked[0][0]) == len(with_mites) and asked[0][1] == []


def test_a_plate_named_already_is_not_read_again(opened):
    data_dir, out_dir, session, asked = opened
    first, *others = sorted({mite["zone_id"] for mite in session["mites"]})
    pipeline.save_labels(data_dir, {str(first): "control"})
    labels = pipeline.read_labels(data_dir, out_dir, session["mites"])
    assert str(first) not in labels and len(labels) == len(others)
    assert asked[0][1] == ["control"]  # given, to spell the same name alike


def test_nothing_is_asked_when_every_plate_has_a_name(opened):
    data_dir, out_dir, session, asked = opened
    pipeline.save_labels(data_dir, {str(mite["zone_id"]): "x" for mite in session["mites"]})
    assert pipeline.read_labels(data_dir, out_dir, session["mites"]) == {}
    assert asked == []


def test_the_label_page_is_told_whether_names_can_be_read(opened):
    _data_dir, _out_dir, session, _asked = opened
    assert set(session["label_reading"]) == {"available", "enabled"}
    assert isinstance(session["label_reading"]["enabled"], bool)


def test_reading_the_names_is_off_until_its_box_is_ticked():
    assert LabelReaderConfig().enabled is False


@pytest.mark.parametrize("before", [
    "mite:\n  radius: 8\n\n# the names\nlabel_reader:\n  enabled: false   # the box\n  model: \"m\"\n",
    "label_reader:\n  model: \"m\"\nmite:\n  radius: 8\n",
    "mite:\n  radius: 8\n  enabled: 1\n",  # a file made before the names were read
])
def test_the_tick_is_saved_in_the_config_file(tmp_path, before):
    path = tmp_path / "config.yaml"
    path.write_text(before, encoding="utf-8")
    for enabled in (True, False):
        assert app_config.save_label_reading(enabled, path) is enabled
        saved = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert saved["label_reader"]["enabled"] is enabled
        assert saved["mite"] == yaml.safe_load(before)["mite"]  # nothing else is touched
        assert saved["label_reader"].get("model") == (yaml.safe_load(before).get("label_reader") or {}).get("model")
    assert "# the box" in path.read_text(encoding="utf-8") or "# the box" not in before  # comments are kept
