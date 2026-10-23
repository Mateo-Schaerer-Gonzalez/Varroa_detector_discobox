"""The analysis, as functions the user interface calls.

This package is the only part of the analysis the user interface may import, and
it knows nothing about HTTP, sessions or browsers. Everything crossing this
boundary is a plain dict, list, string or number -- never a Zone, Mite, DataFrame
or image array -- so the UI can never reach into the analysis internals. The
logic itself lives in classes/; these modules turn it into what the pages need.

Each module below says in its docstring what it holds. Within the package a
module uses another as `module.name`, so every call says where it is defined.
The functions re-exported here are the ones the server, main.py and the tests
call; scripts may also import a module for its helpers.

    pipeline/paths.py                                where everything is kept, and the names of the files
    pipeline/refusals.py                             the refusals every part makes alike
    pipeline/plate_zones.py                          the plates, their zones, and the mites as the pages know them
    pipeline/plate_labels.py                         group names of the plates (typed or read by Gemini), negative controls
    pipeline/ground_truth.py                         a folder's ground_truth.json, its "not a mite" marks
    pipeline/detections.py                           marking a detection "not a mite" from the label page
    pipeline/preview_images.py                       the pictures of the plate the pages draw on
    pipeline/scoring.py                              detect and score: from frames to a run and its table
    pipeline/output_files.py                         the workbook and figures, written in the background
    pipeline/run_results.py                          a run's results for the pages; corrections, mites to check, death time
    pipeline/folder_analysis.py                      a folder from the pages: open, run, correct
    pipeline/clips.py                                everything cut from the frames for the pages
    pipeline/playback.py                             the playback page
    pipeline/uploads.py                              folders dropped into the page
    pipeline/recording_list.py                       the list of recordings in recordings/
    pipeline/calibration/session_file.py             what a calibration session is, and its file
    pipeline/calibration/calibration_sessions.py     opening a calibration session, its clips
    pipeline/calibration/truth_entry.py              the ground truth entered on its page, with the unsaved draft
    pipeline/calibration/poke_test.py                the poke test
    pipeline/calibration/dataset_library.py          the recordings with ground truth; copying a folder in
    pipeline/calibration/score_cache.py              the scores (and other measures) cached in a dataset's scores/
    pipeline/calibration/report_rows.py              the rows a calibration report is made of
    pipeline/calibration/movement_score.py           the metric, parameters and threshold in use
    pipeline/calibration/calibration_report.py       the calibration report
    pipeline/calibration/suggested_band.py           the band of calls to check by eye a report suggests
    pipeline/live/live_runs.py                       the live runs open, and what their parts share
    pipeline/live/live_settings.py                   a test run's settings, and what the live page offers
    pipeline/live/live_setup.py                      opening a live run: camera, name, labels, lights; closing it
    pipeline/live/live_capture.py                    a live run going on: start, stop, results after every recording
    pipeline/live/add_mites.py                       adding mites during a live run
    pipeline/live/live_calibration.py                entering ground truth on a live run as it goes
"""

# raised by read_labels() without a key or the internet, which the server answers apart
from classes.plate.label_reader import LabelReadError
from pipeline.paths import (
    LABELS_FILENAME, CONTROLS_FILENAME, GROUND_TRUTH_FILENAME, POKE_FILENAME, SETTINGS_FILENAME, PREVIEW_NAME,
    CALIBRATION_SESSION_NAME, RECORDINGS_ROOT, RESULTS_ROOT, SCRIPTS_OUTPUT, CALIBRATION_REPORT_NAME,
    SCORES_DIRNAME, ADDED_FRAMES_DIRNAME, results_dir, calibration_dir, new_pooled_report_dir,
    remove_empty_pooled_reports, dataset_id,
)
from pipeline.plate_zones import DEFAULT_COORDS_FILE, zones_per_plate
from pipeline.plate_labels import (
    load_labels, save_labels, save_label_reading, read_labels, load_controls, save_controls,
)
from pipeline.detections import set_rejected, mark_detection
from pipeline.scoring import STABILIZE_MARGIN
from pipeline.output_files import finish_files, results_file
from pipeline.run_results import (
    review_mites, save_review_mites, death_minutes, death_minutes_range, save_death_minutes, describe_movement,
    describe_survival,
)
from pipeline.folder_analysis import open_session, save_zones_per_plate, run_analysis, correct_call, review_again
from pipeline.clips import CLIP_MARGIN, MITE_CLIP_REACH, analysis_outlines, analysis_clip, analysis_mite_clip
from pipeline.playback import playback_reach, playback_timeline, playback_sheet
from pipeline.uploads import plan_upload, finish_upload
from pipeline.recording_list import list_recordings, describe_recording, recording_results_file
from pipeline.calibration.calibration_sessions import (
    open_calibration, calibration_clip, calibration_mite_clip, open_saved_calibration,
)
from pipeline.calibration.truth_entry import (
    save_ground_truth, update_ground_truth, truth_view, edit_truth, save_truth, load_calibration_truth,
)
from pipeline.calibration.poke_test import poke_view, edit_poke
from pipeline.calibration.dataset_library import (
    dataset_folder, list_calibration_datasets, dataset_preview, delete_calibration_dataset, dataset_clip,
    calibration_folder,
)
from pipeline.calibration.score_cache import mite_boxes
from pipeline.calibration.movement_score import movement_scores, save_threshold, save_movement_score
from pipeline.calibration.calibration_report import evaluate_calibration
from pipeline.calibration.suggested_band import REVIEW_CHECKS
from pipeline.live.live_runs import CameraError, LiveRunNotOpen, live_status, live_results, live_running
from pipeline.live.live_settings import (
    LIVE_SETTINGS_FILE, live_options, print_cameras, default_run_name, save_live_settings, live_plan,
)
from pipeline.live.live_setup import (
    open_live, set_live_options, live_preview, live_read_labels, set_live_light, live_frame, close_live,
    close_all_live,
)
from pipeline.live.live_capture import (
    start_live, live_correct_call, live_refresh, pause_live, resume_live, stop_live,
)
from pipeline.live.add_mites import live_find_mites, live_add_mites
from pipeline.live.live_calibration import open_live_calibration, grow_live_calibration
