import matplotlib.pyplot as plt


class Plotter:
    def __init__(self, mite_data):
        self.mite_data = mite_data  # pd frame with mite motion time and zone assigned

    def plot_score_distribution(self):
        """Histogram of motion scores across all (mite, burst) observations."""
        scores = self.mite_data["motion_score"]

        plt.figure()
        plt.hist(scores, bins=30, edgecolor="black")
        plt.xlabel("Mite variability (mean per-pixel std over frames)")
        plt.ylabel("Count (mite x recording)")
        plt.title(f"Mite variability distribution (n={len(scores)})")
        plt.show()

    def plot_score_over_time(self):
        """Each mite's variability over time, with the mean across mites overlaid."""
        plt.figure()
        for _mite_id, group in self.mite_data.groupby("mite_ID"):
            group = group.sort_values("time")
            plt.plot(group["time"], group["motion_score"], color="tab:blue", alpha=0.25, linewidth=1)

        mean_over_time = self.mite_data.groupby("time")["motion_score"].mean().sort_index()
        plt.plot(mean_over_time.index, mean_over_time.values, color="black", linewidth=2.5, marker="o", label="mean over mites")

        n_mites = self.mite_data["mite_ID"].nunique()
        plt.xlabel("Time (min)")
        plt.ylabel("Mite variability (mean per-pixel std over frames)")
        plt.title(f"Mite variability over time (n={n_mites} mites)")
        plt.legend()
        plt.show()
    def plot_single_mite(self, mite_ID):
        """Motion score over time for a single mite."""
        mite = self.mite_data[self.mite_data["mite_ID"] == mite_ID].sort_values("time")
        if mite.empty:
            raise ValueError(f"No data found for mite_ID={mite_ID!r}")

        plt.figure()
        plt.plot(mite["time"], mite["motion_score"], color="tab:blue", marker="o")
        plt.xlabel("Time (min)")
        plt.ylabel("Mite variability (mean per-pixel std over frames)")
        plt.title(f"Mite variability over time ({mite_ID})")
        plt.show()
