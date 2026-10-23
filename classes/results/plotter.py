import matplotlib.pyplot as plt
import numpy as np

SCORE_LABEL = "Mite variability (mean per-pixel std over frames)"


class Plotter:
    """Builds figures from the mite score table.

    Every plot method returns its Matplotlib figure instead of showing it, so the
    same code works for the CLI (call `show()` afterwards) and for the web app
    (save the figure to a PNG).
    """

    def __init__(self, mite_data):
        self.mite_data = mite_data  # pd frame with mite motion time and zone assigned

    def plot_distribution_by_group(self):
        """Score distribution per user-defined group, as a box plot with the raw points."""
        groups = sorted(self.mite_data["group"].unique())
        scores = [self.mite_data.loc[self.mite_data["group"] == g, "motion_score"].values for g in groups]

        fig, ax = plt.subplots(figsize=(1.6 * len(groups) + 4, 6))
        ax.boxplot(scores, tick_labels=groups, showfliers=False)

        # Overlay the individual observations, jittered so overlapping points stay visible.
        rng = np.random.default_rng(0)
        for position, values in enumerate(scores, start=1):
            jitter = (rng.random(len(values)) - 0.5) * 0.25
            ax.scatter(position + jitter, values, alpha=0.35, s=12, color="tab:blue", zorder=3)

        ax.set_xlabel("Group")
        ax.set_ylabel(SCORE_LABEL)
        ax.set_title(f"Mite variability by group (n={len(self.mite_data)} observations)")
        ax.tick_params(axis="x", rotation=20)
        fig.tight_layout()
        return fig

    def plot_score_distribution(self):
        """Histogram of motion scores across all (mite, burst) observations."""
        scores = self.mite_data["motion_score"]

        fig, ax = plt.subplots()
        ax.hist(scores, bins=30, edgecolor="black")
        ax.set_xlabel(SCORE_LABEL)
        ax.set_ylabel("Count (mite x recording)")
        ax.set_title(f"Mite variability distribution (n={len(scores)})")
        fig.tight_layout()
        return fig

    def plot_score_over_time(self):
        """Each mite's variability over time, with the mean across mites overlaid."""
        fig, ax = plt.subplots()
        for _mite_id, group in self.mite_data.groupby("mite_ID"):
            group = group.sort_values("time")
            ax.plot(group["time"], group["motion_score"], color="tab:blue", alpha=0.25, linewidth=1)

        mean_over_time = self.mite_data.groupby("time")["motion_score"].mean().sort_index()
        ax.plot(mean_over_time.index, mean_over_time.values, color="black", linewidth=2.5, marker="o", label="mean over mites")

        n_mites = self.mite_data["mite_ID"].nunique()
        ax.set_xlabel("Time (min)")
        ax.set_ylabel(SCORE_LABEL)
        ax.set_title(f"Mite variability over time (n={n_mites} mites)")
        ax.legend()
        fig.tight_layout()
        return fig

    def plot_moving_by_group(self):
        """Fraction of each group's mites moving in each recording."""
        moving = self.mite_data.groupby(["group", "time"])["moving"].mean().unstack("group")

        fig, ax = plt.subplots()
        for group in sorted(moving.columns):
            ax.plot(moving.index, moving[group] * 100, marker="o", markersize=4, label=group)

        ax.set_ylim(-3, 103)
        ax.set_xlabel("Time (min)")
        ax.set_ylabel("Mites moving (%)")
        ax.set_title("Mites moving by group")
        ax.legend()
        fig.tight_layout()
        return fig

    def plot_single_mite(self, mite_ID):
        """Motion score over time for a single mite."""
        mite = self.mite_data[self.mite_data["mite_ID"] == mite_ID].sort_values("time")
        if mite.empty:
            raise ValueError(f"No data found for mite_ID={mite_ID!r}")

        fig, ax = plt.subplots()
        ax.plot(mite["time"], mite["motion_score"], color="tab:blue", marker="o")
        ax.set_xlabel("Time (min)")
        ax.set_ylabel(SCORE_LABEL)
        ax.set_title(f"Mite variability over time ({mite_ID})")
        fig.tight_layout()
        return fig

    @staticmethod
    def show():
        """Display every figure built so far. For interactive/CLI use only."""
        plt.show()
