"""What the outline_variability score sees of one mite in one recording, for the
result pages to draw over the mite: a dot in each of the score's directions,
just outside the body's edge, saying how much the outline varies there, and the
arrow of the vector sum, toward the side the variance lies on.

Nothing here is used for scoring; it reads the same outline as the score does
(Analyzer.outline_variability_profile()).
"""

import numpy as np

from classes.analyzer import Analyzer


class OutlineView:
    CLEAR = 3.0  # pixels outside the body's edge at which the dots are drawn

    @staticmethod
    def describe(roi, x0=0.0, y0=0.0, width=1.5, pad=16):
        """The outline of the mite in `roi` (frames, height, width, 3), a patch
        cut `pad` pixels around its box with its corner at (`x0`, `y0`) of the
        image; `width` is the score's. In image pixels:

            x, y    the mite's centre
            dots    [x, y, share] per direction: where the dot is, and the
                    variance there as a share of the outline's largest
            arrow   [x, y]: where the arrow from the centre ends; it is as long
                    as the dots are far when all the variance is on one side
            share   the share of the variance on one side, 0 to 1

        None for a patch without a mite."""
        rays = Analyzer._outline_rays(roi, pad)
        if rays is None:
            return None
        _variance, edge, ray_step, (centre_x, centre_y) = rays
        profile = Analyzer.outline_variability_profile(roi, width, pad)
        angle = np.arange(len(profile)) * (2 * np.pi / len(profile))
        radius = edge * ray_step + OutlineView.CLEAR
        most, mean = float(profile.max()), float(profile.mean())
        pull = (profile * np.exp(1j * angle)).mean()
        share = float(abs(pull) / mean) if mean >= 1e-6 else 0.0
        reach = float(np.median(radius)) * min(share, 1.0)
        toward = float(np.angle(pull))
        x, y = x0 + centre_x, y0 + centre_y
        return {
            "x": round(x, 2),
            "y": round(y, 2),
            "dots": [[round(float(x + r * np.cos(a)), 2), round(float(y + r * np.sin(a)), 2), round(value / most, 3) if most > 0 else 0.0]
                     for r, a, value in zip(radius.tolist(), angle.tolist(), profile.tolist())],
            "arrow": [round(float(x + reach * np.cos(toward)), 2), round(float(y + reach * np.sin(toward)), 2)],
            "share": round(share, 3),
        }
