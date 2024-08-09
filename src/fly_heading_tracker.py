# ./src/fly_heading_tracker.py
from collections import deque

import numpy as np
from scipy.stats import circmean


class FlyHeadingTracker:
    def __init__(self, max_frames=10):
        self.max_frames = max_frames
        self.headings = deque(maxlen=max_frames)

    def update(self, xvel, yvel):
        # Calculate heading in degrees
        heading = np.arctan2(yvel, xvel)
        self.headings.append(heading)

    def get_average_heading(self):
        if not self.headings:
            return None

        return circmean(self.headings, high=np.pi, low=-np.pi)

    def reset(self):
        self.headings.clear()
