"""Command-line entry point.

Analyse a folder of recordings:

    python main.py                       # sample_data, labels from its labels.json
    python main.py my_recordings out/run1
    python main.py my_recordings out/run1 --pool-size 10

Live, from the Discobox camera -- a test run with the settings of settings.txt
(the ones the web page saves), analysed as each recording is captured:

    python main.py --list-cameras
    python main.py --live [--camera-id ID] [--fps 30] [--run-name NAME] [--no-save-frames]
    python main.py --replay sample_data  # a recorded folder, played as if from the camera

The results go to results/<folder name>/ unless another folder is given. The
recordings of a live run are saved to recordings/<run name>/, a folder the first
form reads back with the same results. Ctrl+C stops a live run cleanly: the
recording being captured ends with the frames already in, is analysed, and the
results are written.

This calls exactly the same functions the web app calls. If the CLI ever stops
working, analysis logic has leaked into the user interface.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import pipeline

LIVE_ID = "cli"


def parse_args(argv):
    parser = argparse.ArgumentParser(
        description="Detect varroa mites and score how much they move, from a folder of recordings or live.")
    parser.add_argument("data_dir", nargs="?", default="sample_data", help="the folder holding the ..._fps-30 folders")
    parser.add_argument("out_dir", nargs="?", default=None, help="where the results go (default results/<folder name>)")
    parser.add_argument("--pool-size", type=int, default=None, metavar="N",
                        help="frames scored together (default: a whole recording, one burst)")

    live = parser.add_argument_group("live runs")
    live.add_argument("--list-cameras", action="store_true", help="list the cameras Vimba X sees and exit")
    live.add_argument("--live", action="store_true", help="run a Discobox test run from the camera")
    live.add_argument("--camera-id", help="the camera to use (default: the only one connected)")
    live.add_argument("--fps", type=int, help="frames per second (default: settings.txt; for --replay, the recordings' own)")
    live.add_argument("--replay", metavar="DIR", help="replay a recorded folder as if it came from the camera")
    live.add_argument("--replay-gap", type=float, default=2.0, metavar="S", help="seconds between replayed recordings")
    live.add_argument("--run-name", help="the test run's name (default test_run_<date>)")
    live.add_argument("--settings", default=str(pipeline.LIVE_SETTINGS_FILE), metavar="FILE",
                      help="the test-run settings, in the Discobox format (default settings.txt)")
    live.add_argument("--serial-port", default="auto",
                      help="the fan/LED Arduino's port, 'auto' (the only Arduino) or 'none'")
    live.add_argument("--labels", metavar="FILE", help="plate labels for a live run (JSON: zone id -> group)")
    live.add_argument("--no-save-frames", action="store_true", help="analyse without saving the recordings (long runs)")
    live.add_argument("--out-dir", dest="live_out_dir", metavar="DIR",
                      help="where a live run's results go (default results/<run name>)")

    args = parser.parse_args(argv)
    args.is_live = args.live or bool(args.camera_id) or bool(args.replay)
    if args.is_live and (args.out_dir is not None or args.data_dir != parser.get_default("data_dir")):
        parser.error("a live run takes no folder: --replay DIR replays one, --out-dir DIR says where the results go")
    return args


def print_summary(results, out_dir):
    print(f"\n{results['summary']['n_mites']} mites across {results['n_recordings']} recordings")
    print(f"{results['summary']['n_groups']} group(s):")
    for row in results["summary"]["groups"]:
        print(f"  {row['group']:<20} {row['n_mites']:>3} mites   mean {row['mean_score']:.1f}")

    print(f"\nWritten to {out_dir}:")
    for name in [results["excel"], results["detections"], *results["figures"]]:
        print(f"  {name}")


def analyse_folder(args):
    data_dir = args.data_dir
    out_dir = args.out_dir or pipeline.results_dir(data_dir, pipeline.RESULTS_ROOT)

    labels = pipeline.load_labels(data_dir)
    if not labels:
        print(f"No {pipeline.LABELS_FILENAME} in {data_dir}; every zone will be 'unlabeled'.")

    results = pipeline.run_analysis(data_dir, out_dir, labels, pool_size=args.pool_size)
    print_summary(results, out_dir)


def run_live(args):
    run_name = args.run_name or pipeline.default_run_name(pipeline.RECORDINGS_ROOT)
    labels = json.loads(Path(args.labels).read_text(encoding="utf-8")) if args.labels else None
    if args.replay:
        options = {"source": "replay", "replay_dir": args.replay, "replay_fps": args.fps, "replay_gap": args.replay_gap}
    else:
        options = {"source": "camera", "camera_id": args.camera_id, "serial_port": args.serial_port,
                   "settings_path": args.settings, "settings": {"fps": args.fps} if args.fps else None}

    status = pipeline.open_live(LIVE_ID, args.live_out_dir, run_name, save_frames=not args.no_save_frames,
                                pool_size=args.pool_size, recordings_root=pipeline.RECORDINGS_ROOT,
                                results_root=pipeline.RESULTS_ROOT, **options)
    out_dir = status["out_dir"]
    try:
        print(f"Test run {run_name}: {status['camera']}, pools of {status['pool_size_text']}")
        print(f"Recordings {'saved to ' + status['run_dir'] if status['save_frames'] else 'not saved'}; Ctrl+C stops the run.")
        pipeline.start_live(LIVE_ID, labels)
        follow(status["recordings"])
    except KeyboardInterrupt:
        print("\nStopping: the recording being captured ends with the frames already in, then the results are written...")
        pipeline.stop_live(LIVE_ID, wait=True)
    finally:
        status = pipeline.live_status(LIVE_ID)
        results = pipeline.live_results(LIVE_ID)["results"]
        pipeline.close_live(LIVE_ID)

    if status["error"]:
        print(f"\n{status['error']}")
    if status["dropped"] or status["incomplete"]:
        print(f"\n{status['dropped']} frame(s) dropped, {status['incomplete']} incomplete.")
    if results is None:
        print("\nNo recording was analysed.")
        return 1
    print_summary(results, out_dir)
    if status["save_frames"]:
        print(f"\nRecordings saved to {status['run_dir']}")
    return 0


def follow(total):
    """Print a line for each recording analysed, until the run ends."""
    shown = 0
    while True:
        status = pipeline.live_status(LIVE_ID)
        results = pipeline.live_results(LIVE_ID)["results"]
        if results is not None and len(results["times"]) > shown:
            shown = len(results["times"])
            summary = results["summary"]
            print(f"  {shown:>3}/{total}  {results['times'][-1]:6.1f} min  "
                  f"{summary['n_moving_last']}/{summary['n_mites']} mites moving")
        if status["state"] == "finished":
            return
        time.sleep(0.5)


def main(argv=None):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    if not (args.list_cameras or args.is_live):
        analyse_folder(args)  # errors surface exactly as they always have
        return 0
    try:
        if args.list_cameras:
            pipeline.print_cameras()
            return 0
        return run_live(args)
    except (pipeline.live_camera.CameraError, FileNotFoundError, ValueError) as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
