# The code behind the reports' figures

The reports in `report/` draw their figures with these scripts, kept as they were run
(23–30 October 2026), with only the repository's path made relative. They read copies of
the recordings in `%TEMP%\zzrc\perf\<dataset>` (hard links of the frames, see CLAUDE.md),
never `recordings/` itself. Each figure script runs on its own from any folder
(`python report/scripts/fig_mask.py`): it draws into `report/images` (or the folder given as
its argument), shows its figures, and first runs the data script for any data that is
missing (`figure_kit.py`). The figures draw with the app's constants as they are now.

| Figure (`report/images/`) | Report | Made by |
|---|---|---|
| `walk_*.png` | `2_how_it_works.md` (each section's example) | `scripts/visual_walkthrough.py --long-run %TEMP%\zzrc\perf\long_run` (the poke run from `%TEMP%\zzrc\gt`) |
| `app_*.png` (`app_calibration_*` too), `mite_outline_app.png` | `1_user_manual.md`, `2_how_it_works.md` | `scripts/readme_screenshots.mjs`, then `scripts/readme_images.py` (the 2025 test sessions only; the calibration pages calibrate on `ground_truth_60min` and test on `ground_truth_90min`). `readme_images.py` also writes `docs/images/`: check those out again (`git checkout -- docs/images`) to leave README.md's pictures as they are |
| `man_*.png` | `1_user_manual.md` | `manual_screenshots.mjs` (stage by stage, on a copy of the app holding only the 2025 test sessions and the demos made from them, its live run on the simulated Discobox of `live_demo.py`; the high plate shake and the fly-offs from real runs copied without their labels), then `manual_images.py`. The comments at the top of `manual_screenshots.mjs` say how to start the copy |
| `detector_steps.png` | `2_how_it_works.md` | `figures2.py` |
| `squares.png` | `2_how_it_works.md` (section 2, the four squares round a mite) | `fig_squares.py` (the poke run from `%TEMP%\zzrc\gt2`, or the folder given) |
| `ray_reach.png` | `2_how_it_works.md` (section 3.3, how far the rays reach: a valid and an invalid case) | `fig_ray_reach.py` (schematic, no data) |
| `threshold_pick.png` | `2_how_it_works.md` (section 6, how the threshold is picked, on five labelled scores) | `fig_threshold_pick.py` (the app's own `calibration` functions, no data) |
| `outline_unrolled.png`, `outline_vector_sum.png` | `2_how_it_works.md` | `outline_data.py` (the data), then `fig_outline.py` |
| `body_mask.png` | `2_how_it_works.md` | `stab_data.py` (the data), then `fig_mask.py` |
| `score_regions.png` | `2_how_it_works.md` | `stab_data.py`, then `fig_stab.py` |
| `still_noise_floor.png` | `2_how_it_works.md` | `scripts/noise_floor.py` (the table), then `still_floor_fig.py` |
| `benchmark_bars.png`, `benchmark_shake.png` | `3_performance.md` | `evaluate.py` (every labelled mite-recording, scored by the app and by the original software, to `eval/`), `bench_fixed.py` (the table, `bench_fixed.json`), then `fig_bench4.py`; the shake is from `scripts/shaky_recordings.py` |
| `speed_memory_storage.png` | `3_performance.md` | `speed.py app\|original shipped\|1` and `memory.py app\|original` (each adds a line to `speed.jsonl`), then `fig_speed.py` |

`bench_fixed.json` (30 October 2026, the app at its default threshold, judged by F0.25) and
`speed.jsonl` (26 October 2026) are the measurements the performance report quotes, both on
the dev laptop. `eval/` (not in git) holds the scored rows `evaluate.py` writes.

The figures in `README.md` (`docs/images/`) are the walkthrough's, the screenshots and the
performance report's, copied by `scripts/readme_images.py`. `scripts/benchmark_original.py`
redoes the benchmark with the code as it is and draws its charts into `docs/images/`.
