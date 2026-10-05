"""Reads the names written beside the plates.

Each plate has an area beside it where its name is written by hand. LabelReader
cuts these areas out of a frame and asks Google Gemini, a model that takes
pictures and text, what is written in each. It needs the internet and a free API
key (aistudio.google.com/apikey), as GEMINI_API_KEY in the environment or in the
file .env beside config.yaml. Only the standard library talks to Google, so
nothing has to be installed for it.
"""

import base64
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

import cv2

API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-flash-lite-latest"
KEY_NAMES = ("GEMINI_API_KEY", "GOOGLE_API_KEY")
# This machine's own, like config.yaml, and never in git.
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


class LabelReadError(Exception):
    """The names could not be read: no key, no internet, or an answer that makes no sense."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status  # Google's HTTP status, when it answered with an error


def _post_json(url, headers, body, timeout):
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                     headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as reply:
            return json.loads(reply.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        # Google says why in the body, e.g. a wrong key or the free quota used up.
        try:
            reason = json.loads(error.read().decode("utf-8"))["error"]["message"]
        except (ValueError, KeyError, TypeError):
            reason = error.reason
        raise LabelReadError(f"Google Gemini refused to read the names ({error.code}): {reason}", error.code)
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise LabelReadError(f"Google Gemini could not be reached: {getattr(error, 'reason', error)}")
    except ValueError:
        raise LabelReadError("Google Gemini's answer could not be read.")


class LabelReader:
    # Writing often runs over the edge of its area: this much of the area's
    # width and height is read around it too.
    MARGIN = 0.15
    # A small crop is enlarged to this height, which the model reads better.
    MIN_HEIGHT = 400
    # Google is often too busy for a moment (503) or asks to slow down (429):
    # asked again this many times, this many seconds apart.
    RETRIES = 4
    RETRY_WAIT = 4
    BUSY = (429, 500, 503)

    def __init__(self, api_key=None, model=None, timeout=45, send=_post_json, wait=time.sleep):
        self.api_key = api_key or self.saved_key()
        self.model = model or DEFAULT_MODEL
        self.timeout = timeout
        self._send = send  # (url, headers, body, timeout) -> the reply's JSON
        self._wait = wait

    @staticmethod
    def saved_key(env_file=ENV_FILE):
        """The API key of this machine: from the environment, or else from .env
        (lines like GEMINI_API_KEY=...); None without one."""
        for name in KEY_NAMES:
            if os.environ.get(name, "").strip():
                return os.environ[name].strip()
        try:
            lines = Path(env_file).read_text(encoding="utf-8").splitlines()
        except OSError:
            return None
        for line in lines:
            name, _, value = line.partition("=")
            value = value.strip().strip("\"'")
            if name.strip().removeprefix("export ").strip() in KEY_NAMES and value:
                return value
        return None

    def crop(self, frame, area):
        """The label `area` of `frame`, with its margin, as JPEG bytes."""
        height, width = frame.shape[:2]
        dx, dy = (area.x2 - area.x1) * self.MARGIN, (area.y2 - area.y1) * self.MARGIN
        x1, x2 = max(0, int(area.x1 - dx)), min(width, int(area.x2 + dx))
        y1, y2 = max(0, int(area.y1 - dy)), min(height, int(area.y2 + dy))
        if x2 <= x1 or y2 <= y1:
            raise LabelReadError("A label area lies outside the picture.")
        image = frame[y1:y2, x1:x2]
        if image.shape[0] < self.MIN_HEIGHT:
            scale = self.MIN_HEIGHT / image.shape[0]
            image = cv2.resize(image, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 90])
        if not ok:
            raise LabelReadError("A label area could not be made into a picture.")
        return encoded.tobytes()

    @staticmethod
    def prompt(count, known=()):
        text = (
            f"Each of the {count} images is the area beside a laboratory plate where the plate's name is "
            "written by hand with a marker. Read what is written in each image. Answer with a JSON array of "
            f"{count} strings, in the order of the images: the writing as it is written, or an empty string "
            "when nothing is written or it cannot be read. Dots, scratches, shadows and the edges of the "
            "plate are not writing; do not guess a name where there is none."
        )
        if known:
            text += (f" Other plates of this experiment are named {json.dumps(list(known))}: when the "
                     "writing is one of these names, spell it the same way.")
        return text

    def read(self, frame, areas, known=()):
        """What is written in each of `areas` (rectangles with x1, y1, x2, y2) of
        `frame`: one string per area, empty where nothing is written. `known` are
        names already given to other plates, to spell the same name the same way."""
        areas = list(areas)
        if not areas:
            return []
        if not self.api_key:
            raise LabelReadError("No Google Gemini API key: put GEMINI_API_KEY=... in the file .env "
                                 "in the app's folder and start the app again.")
        parts = []
        for number, area in enumerate(areas, start=1):
            picture = base64.b64encode(self.crop(frame, area)).decode("ascii")
            parts += [{"text": f"Image {number}:"}, {"inline_data": {"mime_type": "image/jpeg", "data": picture}}]
        parts.append({"text": self.prompt(len(areas), known)})
        body = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "temperature": 0,
                "responseMimeType": "application/json",
                "responseSchema": {"type": "ARRAY", "items": {"type": "STRING"}},
            },
        }
        for attempt in range(self.RETRIES + 1):
            try:
                reply = self._send(API_URL.format(model=self.model), {"x-goog-api-key": self.api_key}, body, self.timeout)
                return self._names(reply, len(areas))
            except LabelReadError as error:
                if error.status not in self.BUSY or attempt == self.RETRIES:
                    raise
                self._wait(self.RETRY_WAIT)

    @staticmethod
    def _names(reply, count):
        try:
            text = "".join(part.get("text", "") for part in reply["candidates"][0]["content"]["parts"])
            names = json.loads(text)
        except (KeyError, IndexError, TypeError, ValueError, AttributeError):
            raise LabelReadError("Google Gemini gave no names for the plates.")
        if not isinstance(names, list) or len(names) != count:
            raise LabelReadError(f"Google Gemini did not give one name for each of the {count} plates.")
        return [" ".join(str(name).split()) if name is not None else "" for name in names]
