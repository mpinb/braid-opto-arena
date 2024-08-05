import math
from collections import deque


class FlyHeadingTracker:
    def __init__(self, max_frames=10):
        self.max_frames = max_frames
        self.headings = deque(maxlen=max_frames)

    def update(self, xvel, yvel):
        # Calculate heading in degrees
        heading = math.degrees(math.atan2(yvel, xvel))
        # Ensure heading is between 0 and 360 degrees
        heading = (heading + 360) % 360
        self.headings.append(heading)

    def get_average_heading(self):
        if not self.headings:
            return None

        # Convert headings to complex numbers for proper circular averaging
        complex_headings = [
            math.cos(math.radians(h)) + 1j * math.sin(math.radians(h))
            for h in self.headings
        ]
        avg_complex = sum(complex_headings) / len(complex_headings)

        # Convert average complex number back to degrees
        avg_heading = math.degrees(math.atan2(avg_complex.imag, avg_complex.real))
        return (avg_heading + 360) % 360

    def reset(self):
        self.headings.clear()
