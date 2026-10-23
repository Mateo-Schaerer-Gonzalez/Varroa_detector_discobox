"""What the list of recordings says about how one was recorded: whether its test
run is still going or ended early, how many recordings were planned, and the fan
and LEDs of its Discobox settings.

Works on what pipeline.describe_recording() reads: a live run's run.json (as a
dict, or None for a folder dropped into the page) and the .settings.txt values.
"""

# The fan and the two LEDs: their duration and intensity settings, and their names.
DEVICES = (("vent_time", "vent", "Fan"), ("led1_time", "led1", "LED 1"), ("led2_time", "led2", "LED 2"))


class RecordingInfo:
    @staticmethod
    def state(run, recording_now):
        """"recording" while the live run is being recorded, "interrupted" when the
        app stopped during it, "stopped" when it ended before every recording
        planned; None for a run that went through, or a folder without a run."""
        if recording_now:
            return "recording"
        if not run:
            return None
        if not run.get("ended_at"):
            return "interrupted"
        if run.get("recordings_analysed", 0) < run.get("recordings_planned", 0):
            return "stopped"
        return None

    @staticmethod
    def planned(run, settings):
        """The recordings planned: the live run's, else the Discobox settings'
        recording_count; None when neither says."""
        if run:
            return run.get("recordings_planned")
        return (settings or {}).get("recording_count")

    @staticmethod
    def lights(settings):
        """The fan and LEDs of `settings`: {all_alike ({seconds, level} when all
        three are on alike), level (the one intensity of every device that is on,
        else None), devices ([{name, seconds, level}] for those in the settings)}."""
        settings = settings or {}
        devices = [(time, level, name) for time, level, name in DEVICES if settings.get(time) is not None]
        on = [(time, level) for time, level, _name in devices if settings[time]]
        levels = {settings.get(level) for _time, level in on}
        one_level = next(iter(levels)) if len(levels) == 1 and None not in levels else None
        alike = len(devices) == 3 and len(on) == 3 and len({settings[time] for time, _level in on}) == 1 and one_level is not None
        return {
            "all_alike": {"seconds": settings["vent_time"], "level": one_level} if alike else None,
            "level": one_level,
            "devices": [{"name": name, "seconds": settings[time], "level": settings.get(level)} for time, level, name in devices],
        }
