"""Command-line entry point: run the analysis on a folder of recordings.

    python main.py                       # sample_data, labels from its labels.json
    python main.py my_recordings out/run1

This calls exactly the same two functions the web app calls. If the CLI ever stops
working, analysis logic has leaked into the user interface.
"""

import sys

import pipeline

data_dir = sys.argv[1] if len(sys.argv) > 1 else "sample_data"
out_dir = sys.argv[2] if len(sys.argv) > 2 else "outputs/cli"

labels = pipeline.load_labels(data_dir)
if not labels:
    print(f"No {pipeline.LABELS_FILENAME} in {data_dir}; every zone will be 'unlabeled'.")

results = pipeline.run_analysis(data_dir, out_dir, labels)

print(f"\n{results['summary']['n_mites']} mites across {results['n_recordings']} recordings")
print(f"{results['summary']['n_groups']} group(s):")
for row in results["summary"]["groups"]:
    print(f"  {row['group']:<20} {row['n_mites']:>3} mites   mean {row['mean_score']:.1f}")

print(f"\nWritten to {out_dir}:")
for name in [results["excel"], results["detections"], *results["figures"]]:
    print(f"  {name}")
