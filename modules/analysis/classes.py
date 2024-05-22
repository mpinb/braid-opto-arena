import pandas as pd
from typing import Union, List
import numpy as np


class Trajectory(pd.DataFrame):
    _metadata = ["trajectories"]

    def __init__(self, *args, **kwargs):
        super(Trajectory, self).__init__(*args, **kwargs)

    @property
    def _constructor(self):
        return Trajectory

    @property
    def duration(self) -> float:
        """Returns the duration of the trajectory."""
        return self["timestamp"].max() - self["timestamp"].min()

    @property
    def n_frames(self) -> int:
        """Returns the number of frames in the trajectory."""
        return (
            self["frame"].max() - self["frame"].min() + 1
        )  # +1 to count the total frames

    def distance(self, axes: str = "xyz") -> float:
        """Calculates the total Euclidean distance covered by the trajectory along the specified axes.

        Parameters:
        axes (str): A string specifying which axes to consider ('x', 'y', 'z' or any combination).

        Returns:
        float: The total distance covered.
        """
        diffs = []
        for axis in axes:
            if axis in self.columns:
                diffs.append(self[axis].diff().fillna(0) ** 2)

        return np.sum(np.sqrt(np.sum(diffs, axis=0)))

    def filter_by_obj_id(self, obj_id: Union[int, List[int]]) -> "Trajectory":
        """Filters the DataFrame by given object IDs.

        Parameters:
        obj_id (Union[int, List[int]]): A single object ID or a list of object IDs to filter by.

        Returns:
        Trajectory: A filtered DataFrame containing only the specified object IDs.
        """
        if isinstance(obj_id, int):
            obj_id = [obj_id]

        return self[self["obj_id"].isin(obj_id)]

    def filter_by_duration(self, min_duration: float) -> List[int]:
        """Filters object IDs by a minimum duration threshold.

        Parameters:
        min_duration (float): The minimum duration to filter object IDs.

        Returns:
        List[int]: A list of object IDs that meet the minimum duration criteria.
        """
        durations = self.groupby("obj_id")["timestamp"].agg(lambda x: x.max() - x.min())
        valid_obj_ids = durations[durations > min_duration].index.to_list()
        return valid_obj_ids


if __name__ == "__main__":
    # Example usage
    data = {
        "obj_id": [1, 1, 1, 2, 2, 3, 3, 3],
        "frame": [1, 2, 3, 1, 2, 1, 2, 3],
        "timestamp": [10, 20, 30, 15, 25, 5, 10, 15],
        "x": [0, 1, 2, 0, 1, 0, 1, 2],
        "y": [0, 1, 2, 0, 1, 0, 1, 2],
        "z": [0, 1, 2, 0, 1, 0, 1, 2],
    }

    df = Trajectory(data)

    # Calculate total distance considering all axes
    print("Total distance covered by the trajectory (xyz):", df.distance(axes="xyz"))

    # Filter by a single obj_id
    print("Filtered DataFrame for a single obj_id (2):")
    print(df.filter_by_obj_id(2))

    # Filter by a list of obj_ids
    print("\nFiltered DataFrame for a list of obj_ids ([1, 3]):")
    print(df.filter_by_obj_id([1, 3]))

    # Filter obj_ids by duration
    min_duration = 10
    print("\nObj_ids with duration greater than", min_duration, ":")
    print(df.filter_by_duration(min_duration))
