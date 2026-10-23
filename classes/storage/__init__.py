"""Where frames and files come from and go to: the recordings (whole frames or the
mites' ROIs), the app's own files, kept scores and uploads.

    frame_source.py    the frames as one stream, from a folder, saved ROIs or the camera
    data_loader.py     a folder of whole frames (BMP), as the Discobox app saves them
    roi_recordings.py  recordings kept as each mite's surroundings (FFV1 videos)
    roi_conversion.py  whole frames shrunk to the mites' surroundings
    files.py           reading and writing the app's own files, one way everywhere
    settings_file.py   a recording folder's .settings.txt
    kept_scores.py     a run's scores kept with its results, read back for the same code
    deferred_files.py  files written a moment later, off the request that changed them
    upload_plan.py     which files of a folder dropped into the page to copy
    recording_info.py  what the list of recordings says about how one was recorded
"""
