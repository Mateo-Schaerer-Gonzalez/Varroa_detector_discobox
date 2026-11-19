"""Saves made at the same moment: of one file (files.write_json, as the label page's
saves of labels.json), and of the live settings (each a change of a few names in
settings.txt). Found on 2026-11-17: on Windows two writers of one file failed on
their shared partial file, and two settings saved at once lost one."""

import json
import threading

import pipeline
from classes.live.settings import Settings
from classes.storage.files import write_json


def _at_once(jobs):
    start = threading.Barrier(len(jobs))
    errors = []

    def run(job):
        start.wait()
        try:
            job()
        except Exception as error:  # noqa: BLE001 - every failure is the test's
            errors.append(error)

    threads = [threading.Thread(target=run, args=(job,)) for job in jobs]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return errors


def test_one_file_written_by_several_threads_at_once(tmp_path):
    path = tmp_path / "labels.json"
    jobs = [lambda n=n: [write_json(path, {"4": f"group {n}", "i": i}) for i in range(30)] for n in range(8)]
    assert _at_once(jobs) == []
    assert json.loads(path.read_text())["4"].startswith("group ")
    assert not list(tmp_path.glob("*.part"))


def test_settings_saved_at_once_all_stay(tmp_path):
    path = tmp_path / "settings.txt"
    Settings().save(path)
    changes = {"death_minutes": 10, "run_minutes": 25, "recording_timeout": 5, "vent_time": 20, "led1_time": 20, "led2_time": 20}
    jobs = [lambda name=name, value=value: pipeline.save_live_settings({name: value}, settings_path=path)
            for name, value in changes.items()]
    assert _at_once(jobs) == []
    saved = Settings.from_file(path)
    assert {name: getattr(saved, name) for name in changes} == changes
