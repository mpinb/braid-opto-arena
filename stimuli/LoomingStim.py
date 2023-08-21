from itertools import product

import numpy as np
import pandas as pd
import pygame

from . import BaseStim

MM_PER_PIXEL = 2.5


class LoomingStim(BaseStim):
    """_summary_

    Args:
        BaseStim (_type_): _description_
    """

    def __init__(self, radius, duration, position, stim_type, *args, **kwargs):
        """_summary_

        Args:
            radius (_type_): _description_
            duration (_type_): _description_
            position (_type_): _description_
        """
        super(LoomingStim, self).__init__(*args, **kwargs)

        # Define stimulus parameters
        self.radius = radius
        self.duration = duration
        self.position = position
        self.type = stim_type
        print(f"Stimulus type: {self.type}")

        # Define stimulus flag
        self.is_looming = False

        # Define and generate stimuli
        self.define_stimulus()
        self.generate_stimuli()

    def define_stimulus(self):
        """_summary_"""
        # Define stimulus based on parameters

        # Get radius
        if self.radius == "random":
            if self.type == "linear":
                self.possible_radii = [32, 64]
            else:
                self.possible_radii = [45, 90]

        elif isinstance(self.radius, int):
            self.possible_radii = [self.radius]
        else:
            self.possible_radii = self.radius

        # Get duration
        if self.duration == "random":
            self.possible_durations = [300, 500]
        elif isinstance(self.duration, int):
            self.possible_durations = [self.duration]
        else:
            self.possible_durations = self.duration

        # Get position
        if self.position == "random":
            possible_x = list(range(0, self.screen.get_width(), 32))
            # possible_y = [self.screen.get_height() // 2] * len(possible_x)
            self.possible_positions = np.asarray(possible_x).T
        elif isinstance(self.position, int):
            self.possible_positions = np.asarray(self.position).T
        else:
            self.possible_positions = self.position

    def generate_stimuli(self):
        """_summary_"""
        # Stimuli combinations
        combinations = np.asarray(
            list(
                product(
                    self.possible_radii,
                    self.possible_durations,
                    self.possible_positions,
                )
            )
        )

        # Convert to pandas dataframe
        self.stimuli_df = pd.DataFrame(
            data=combinations, columns=["radius", "duration", "position"]
        )

        # Get all possible combinations in a pandas dataframe
        stimuli = []
        for _, row in self.stimuli_df.iterrows():
            stimuli.append(
                self._generate_stimulus(row["radius"], row["duration"], self.type)
            )

        # Add stimuli to dataframe
        self.stimuli_df["stim"] = stimuli

    def _find_rv_timecourse(
        self, stimulus_duration_ms, theta_min_deg, theta_max_deg, delta_t
    ):
        display_frequency = 1 / delta_t  # in Hz
        deg_to_rad = np.pi / 180
        theta_max = theta_max_deg * deg_to_rad
        theta_min = theta_min_deg * deg_to_rad

        # Calculate time to collision for the given stimulus duration
        r_v_ratio = np.tan(theta_min / 2) * (stimulus_duration_ms / 1000)
        min_collision_time = r_v_ratio / np.tan(theta_max / 2)
        max_collision_time = r_v_ratio / np.tan(theta_min / 2)
        total_collision_time = max_collision_time - min_collision_time
        num_frames = int(np.ceil(total_collision_time * display_frequency))  # round up

        # initialize the time and theta arrays
        time_theta_array = np.zeros((num_frames, 4))

        # fill in the time array
        time_theta_array[:, 0] = -np.linspace(
            min_collision_time, max_collision_time, num_frames
        )

        # fill in the theta in radians
        time_theta_array[:, 1] = 2 * np.arctan2(
            r_v_ratio, np.abs(time_theta_array[:, 0])
        )

        # fill in the theta in mm
        # arctan(theta/2) = x (size on screen) / 250 mm (r)
        # arctan(theta/2) * 250 mm = x mm
        time_theta_array[:, 2] = np.tan(time_theta_array[:, 1] / 2) * 250

        # fill in the theta in pixels
        # x mm / (2.5 mm / pixel) = x mm * (1 pixel / 2.5 mm) = x pixels
        time_theta_array[:, 3] = time_theta_array[:, 2] / MM_PER_PIXEL

        return time_theta_array, r_v_ratio

    def _generate_stimulus(self, radius: int, duration: int, type: str):
        """_summary_

        Args:
            radius (_type_): _description_
            duration (_type_): _description_

        Returns:
            _type_: _description_
        """
        # generate a stimulus according to the type
        n_frames = int(duration / (1000 / 60))
        if type == "linear":
            stim = np.linspace(1, radius, n_frames)
        else:
            print(f"Generating stimulus with radius {radius} and duration {duration}")
            temp_stim, _ = self._find_rv_timecourse(
                stimulus_duration_ms=duration,
                theta_min_deg=5,
                theta_max_deg=radius,
                delta_t=1 / 60,
            )
            stim = np.flip(temp_stim[:, 3])
            print(stim)

        return stim

    def draw(self):
        """_summary_"""
        # Draw stimulus
        pygame.draw.circle(self.screen, self.color, (self.x, self.y), self.radius)

        # wraparound the x position if the circle goes off the screen
        if self.x - self.radius < 0:
            pygame.draw.circle(
                self.screen,
                self.color,
                (self.x + self.screen.get_width(), self.y),
                self.radius,
            )
        elif self.x + self.radius > self.screen.get_width():
            pygame.draw.circle(
                self.screen,
                self.color,
                (self.x - self.screen.get_width(), self.y),
                self.radius,
            )

    def init_loom(self):
        self.curr_loom = self.stimuli_df.sample().iloc[0]
        return True

    def loom(self):
        """_summary_

        Returns:
            _type_: _description_
        """
        # Loom stimulus
        if self.is_looming is False:
            # Get a random row from the DF
            self.curr_radius = self.curr_loom["radius"]
            self.curr_duration = self.curr_loom["duration"]

            # Get all parameters from the row
            self.x = self.curr_loom["position"]
            self.y = self.screen.get_height() // 2

            # Define our radius array as an iterator
            self.radius_array = iter(self.curr_loom["stim"])

            # And get the first value
            self.radius = next(self.radius_array)

            # set looming flag as True
            self.is_looming = True

        # Otherwise, if we started the looming alread
        else:
            try:
                # Get the next value from the iterator
                self.radius = next(self.radius_array)
                self.draw()
                return True

            except StopIteration:
                # If the iterator is exhausted, reset the radius and set the looming flag to False  # noqa: E501
                self.radius = 0
                self.is_looming = False
                self.draw()
                return False
