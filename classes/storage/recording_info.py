"""What the list of recordings says about how one was recorded: whether its test
run is still going or ended early, how many recordings were planned, and the fan
and LEDs of its Discobox settings.

Works on what pipeline.describe_recording() reads: a live run's run.json (as a
dict, or None for a folder dropped into the page) and the .settings.txt values.
"""

# The fan and the two LEDs: their duration and intensity settings, and their names.
DEVICES = (("vent_time", "vent", "Fan"), ("led1_time", "led1", "LED 1"), ("led2_time", "led2", "LED 2"))
# The settings that make a recording what it is, so that a threshold calibrated on one fits it:
# compared with the live settings now by differences().
COMPARED = ("recording_timeout", "vent_time", "led1_time", "led2_time", "vent", "led1", "led2")


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
    def differences(described, current):
        """The names of the recording settings `described` (as
        pipeline.describe_recording() describes a recording) was made with that
        differ from `current` (the live Settings now): "recording_length" and "fps"
        from its frames, the others (COMPARED) from its .settings.txt when it has one.
        The list of recordings shows these in red: a threshold calibrated with the
        settings now may not fit it."""
        differ = []
        frames, fps = described.get("frames"), described.get("fps")
        if frames and fps:
            if round(frames / fps, 1) != round(current.frame_count / current.fps, 1):
                differ.append("recording_length")
            if round(fps) != current.fps:
                differ.append("fps")
        settings = described.get("settings") or {}
        for name in COMPARED:
            value = settings.get(name)
            if value is not None and int(value) != getattr(current, name):
                differ.append(name)
        return differ

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
