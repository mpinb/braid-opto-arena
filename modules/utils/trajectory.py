import numpy as np
from collections import deque


class RealTimeHeadingCalculator:
    def __init__(self, window_size=10):
        self.window_size = window_size
        self.xvel_buffer = deque(maxlen=window_size)
        self.yvel_buffer = deque(maxlen=window_size)
        self.zvel_buffer = deque(maxlen=window_size)

    def add_data_point(self, xvel, yvel, zvel):
        self.xvel_buffer.append(xvel)
        self.yvel_buffer.append(yvel)
        self.zvel_buffer.append(zvel)

    def calculate_smoothed_velocities(self):
        smoothed_xvel = np.mean(self.xvel_buffer)
        smoothed_yvel = np.mean(self.yvel_buffer)
        smoothed_zvel = np.mean(self.zvel_buffer)
        return smoothed_xvel, smoothed_yvel, smoothed_zvel

    def calculate_heading(self):
        smoothed_xvel, smoothed_yvel, smoothed_zvel = (
            self.calculate_smoothed_velocities()
        )
        heading = np.arctan2(smoothed_yvel, smoothed_xvel)
        return heading
