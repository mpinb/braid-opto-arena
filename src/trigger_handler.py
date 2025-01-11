# ./src/trigger_handler.py
import json
import logging
import time
from numba import jit
from typing import Optional

import numpy as np
from .csv_writer import CsvWriter
from .devices.opto_trigger import OptoTrigger
from .fly_heading_tracker import FlyHeadingTracker
from .messages import Publisher

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(name="Trigger Handler")


@jit(nopython=True)
def predict_radius_trajectory(
    x: float,
    y: float,
    xvel: float,
    yvel: float,
    prediction_time: float,
    center_x: float,
    center_y: float,
    radius: float,
) -> bool:
    """
    Predict if object will enter radius zone.
    """
    # Current position relative to center
    curr_x = x - center_x
    curr_y = y - center_y
    curr_rad = (curr_x**2 + curr_y**2) ** 0.5

    # Predicted position
    pred_x = curr_x + (xvel * prediction_time)
    pred_y = curr_y + (yvel * prediction_time)
    pred_rad = (pred_x**2 + pred_y**2) ** 0.5

    # Check if will enter radius
    if curr_rad > radius and pred_rad <= radius:
        # Calculate velocity magnitude
        vel_magnitude = (xvel**2 + yvel**2) ** 0.5
        if vel_magnitude > 1e-6:
            # Check if moving towards center
            dot_product = (curr_x * xvel + curr_y * yvel) / vel_magnitude
            return dot_product < 0

    return False


@jit(nopython=True)
def predict_box_trajectory(
    x: float,
    y: float,
    z: float,
    xvel: float,
    yvel: float,
    zvel: float,
    prediction_time: float,
    box_bounds: np.ndarray,
) -> bool:
    """
    Predict if object will enter box zone.
    """
    # Current position - using absolute coordinates
    curr_outside = (
        x < box_bounds[0]
        or x > box_bounds[1]
        or y < box_bounds[2]
        or y > box_bounds[3]
        or z < box_bounds[4]
        or z > box_bounds[5]
    )

    # Predicted position - using absolute coordinates
    pred_x = x + (xvel * prediction_time)
    pred_y = y + (yvel * prediction_time)
    pred_z = z + (zvel * prediction_time)

    pred_inside = (
        box_bounds[0] <= pred_x <= box_bounds[1]
        and box_bounds[2] <= pred_y <= box_bounds[3]
        and box_bounds[4] <= pred_z <= box_bounds[5]
    )

    return curr_outside and pred_inside


class TriggerHandler:
    def __init__(
        self,
        config: dict,
        opto_trigger: Optional["OptoTrigger"] = None,
        csv_writer: Optional["CsvWriter"] = None,
        trigger_publisher: Optional["Publisher"] = None,
    ):
        """
        Initialize TriggerHandler with improved validation and type hints.
        """
        self._validate_config(config)
        self.config = config
        self.opto_trigger = opto_trigger
        self.csv_writer = csv_writer
        self.trigger_publisher = trigger_publisher

        self.trigger_counter = 0
        self.trigger_time = 0.0
        self.obj_birth_times = {}
        self.obj_heading = {}

        # Extract prediction parameters during initialization
        self._setup_prediction_parameters()

    def _setup_prediction_parameters(self) -> None:
        """
        Sets up prediction parameters with proper initialization.
        """
        self.prediction_time = self.config.get("prediction_time", 0.1)

        if self.config["zone_type"] == "radius":
            self.radius_center = np.array(
                self.config["radius"]["center"], dtype=np.float64
            )
            self.radius_distance = float(self.config["radius"]["distance"])
            self.radius_z_bounds = np.array(
                self.config["radius"]["z"], dtype=np.float64
            )
            # Initialize box_bounds as None for radius mode
            self.box_bounds = None
        else:  # box mode
            self.box_bounds = np.array(
                [
                    self.config["box"]["x"][0],
                    self.config["box"]["x"][1],
                    self.config["box"]["y"][0],
                    self.config["box"]["y"][1],
                    self.config["box"]["z"][0],
                    self.config["box"]["z"][1],
                ],
                dtype=np.float64,
            )
            # Initialize radius parameters as None for box mode
            self.radius_center = None
            self.radius_distance = None
            self.radius_z_bounds = None

    def _validate_config(self, config: dict) -> None:
        """
        Validates config with proper nested dictionary checks.
        """
        # Check basic required parameters
        required_base = {
            "zone_type",
            "min_trajectory_time",
            "min_trigger_interval",
            "prediction_time",
        }
        missing_base = required_base - set(config.keys())
        if missing_base:
            raise ValueError(f"Missing base parameters: {missing_base}")

        # Validate zone-specific parameters
        if config["zone_type"] == "radius":
            if "radius" not in config:
                raise ValueError("Missing 'radius' configuration section")

            required_radius = {"center", "distance", "z"}
            missing_radius = required_radius - set(config["radius"].keys())
            if missing_radius:
                raise ValueError(f"Missing radius parameters: {missing_radius}")

            # Validate nested parameters
            if (
                not isinstance(config["radius"]["center"], (list, tuple))
                or len(config["radius"]["center"]) != 2
            ):
                raise ValueError("radius.center must be a list/tuple of 2 coordinates")
            if (
                not isinstance(config["radius"]["z"], (list, tuple))
                or len(config["radius"]["z"]) != 2
            ):
                raise ValueError("radius.z must be a list/tuple of 2 bounds")

        elif config["zone_type"] == "box":
            if "box" not in config:
                raise ValueError("Missing 'box' configuration section")

            required_box = {"x", "y", "z"}
            missing_box = required_box - set(config["box"].keys())
            if missing_box:
                raise ValueError(f"Missing box parameters: {missing_box}")

            # Validate bounds
            for coord in ["x", "y", "z"]:
                bounds = config["box"][coord]
                if not isinstance(bounds, (list, tuple)) or len(bounds) != 2:
                    raise ValueError(f"box.{coord} must be a list/tuple of 2 bounds")
                if bounds[0] >= bounds[1]:
                    raise ValueError(
                        f"box.{coord} lower bound must be less than upper bound"
                    )

        else:
            raise ValueError(f"Invalid zone_type: {config['zone_type']}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self):
        """
        Closes the TriggerHandler and sends a "kill" message to the trigger publisher.

        This method sends a "kill" message to the trigger publisher to indicate that the TriggerHandler is shutting down.

        Parameters:
            None

        Returns:
            None
        """
        self.trigger_publisher.send("trigger", "kill")
        logging.info("TriggerHandler is shutting down")

    def handle_birth(self, obj_id):
        """
        Handle the birth of an object.

        Args:
            obj_id (Any): The ID of the object.

        Returns:
            None
        """
        logging.debug(f"Got Birth: {obj_id}")
        self.obj_birth_times[obj_id] = time.time()
        self.obj_heading[obj_id] = FlyHeadingTracker()

    def handle_death(self, obj_id):
        """
        Handle the death of an object.

        Args:
            obj_id (str): The ID of the object that died.

        This function is called when an object dies. It logs a debug message indicating the death of the object and removes the object's birth time and heading from the respective dictionaries if the object ID exists in the dictionaries.

        Returns:
            None
        """
        logging.debug(f"Got Death: {obj_id}")
        if obj_id in self.obj_birth_times:
            del self.obj_birth_times[obj_id]
            del self.obj_heading[obj_id]

    def handle_update(self, msg_dict):
        """
        Handle an update message.

        Args:
            msg_dict (dict): A dictionary containing the update message. It should have the following keys:
                - 'obj_id' (Any): The ID of the object being updated.
                - 'xvel' (float): The x-component of the object's velocity.
                - 'yvel' (float): The y-component of the object's velocity.

        This function checks if the object with the given ID has already been detected. If it has, it updates the object's heading tracker with the new velocity components. Then, it checks if the trigger conditions are met and triggers the action if so. If the object has not been detected before, it records its birth time.

        Returns:
            None
        """
        logging.debug(f"Got Update: {msg_dict['obj_id']}")
        obj_id = msg_dict["obj_id"]

        # check if object was already detected
        if obj_id in self.obj_birth_times:
            self.obj_heading[obj_id].update(
                msg_dict["xvel"], msg_dict["yvel"]
            )  # update object tracker

            # check the trigger conditions
            if self._check_trigger_conditions(msg_dict):
                self._trigger_action(msg_dict)  # and trigger
        else:
            self.obj_birth_times[obj_id] = (
                time.time()
            )  # if the object was not already detected
            self.obj_heading[obj_id] = FlyHeadingTracker()

    def _check_trigger_conditions(self, msg_dict: dict) -> bool:
        """
        Checks trigger conditions with separated prediction logic.
        """
        current_time = time.time()
        msg_dict["_check_time"] = current_time

        obj_id = msg_dict["obj_id"]

        # Basic checks
        if (
            current_time - self.obj_birth_times[obj_id]
            < self.config["min_trajectory_time"]
        ):
            logger.debug("Trajectory not long enough")
            return False

        if current_time - self.trigger_time < self.config["min_trigger_interval"]:
            logger.debug("Not enough time passed since last trigger")
            return False

        # Zone-specific predictions
        if self.config["zone_type"] == "radius":
            will_enter = predict_radius_trajectory(
                msg_dict["x"],
                msg_dict["y"],
                msg_dict["xvel"],
                msg_dict["yvel"],
                self.prediction_time,
                self.radius_center[0],
                self.radius_center[1],
                self.radius_distance,
            )
            # Check z-bounds for radius mode
            z_in_bounds = (
                self.radius_z_bounds[0] <= msg_dict["z"] <= self.radius_z_bounds[1]
            )
            return will_enter and z_in_bounds

        else:  # box mode
            return predict_box_trajectory(
                msg_dict["x"],
                msg_dict["y"],
                msg_dict["z"],
                msg_dict["xvel"],
                msg_dict["yvel"],
                msg_dict["zvel"],
                self.prediction_time,
                self.box_bounds,
            )

    def _trigger_action(self, msg_dict: dict) -> None:
        """
        Triggers an action based on the given message dictionary.

        Args:
            msg_dict (dict): A dictionary containing the message with required keys:
                - 'obj_id': The ID of the object
                - '_check_time': The timestamp when conditions were checked

        This function executes the trigger action, including:
        - Recording the trigger time
        - Activating the opto trigger if configured
        - Adding heading data
        - Publishing trigger event
        - Saving data to CSV

        Raises:
            KeyError: If required message keys are missing
        """
        try:
            obj_id = msg_dict["obj_id"]

            # Use timestamp from condition check
            try:
                self.trigger_time = msg_dict.pop("_check_time")
            except KeyError:
                logger.warning("Missing _check_time, using current time instead")
                self.trigger_time = time.time()

            msg_dict["timestamp"] = self.trigger_time

            # Handle opto trigger
            if self.opto_trigger is not None:
                try:
                    result = self.opto_trigger.trigger(self.trigger_time)
                    msg_dict.update(
                        {
                            "execution_time": result.execution_time,
                            "delay": result.delay,
                            "is_sham": result.is_sham,
                        }
                    )
                except Exception as e:
                    logger.error(f"Failed to trigger opto: {e}")
                    # Continue execution - opto failure shouldn't stop other actions

            # Add heading data - we know obj_id must be in obj_heading if it's in obj_birth_times
            msg_dict["heading"] = self.obj_heading[obj_id].get_average_heading()

            # Publish trigger event
            if self.trigger_publisher is not None:
                try:
                    self.trigger_publisher.send("trigger", json.dumps(msg_dict))
                except Exception as e:
                    logger.error(f"Failed to publish trigger: {e}")

            # Save to CSV
            if self.csv_writer is not None:
                try:
                    self.csv_writer.write_row(msg_dict)
                except Exception as e:
                    logger.error(f"Failed to write to CSV: {e}")

            # Log successful trigger
            logger.info(f"Triggered action #{self.trigger_counter} for object {obj_id}")
            self.trigger_counter += 1

        except Exception as e:
            logger.error(f"Error in trigger action: {e}")
            raise  # Re-raise the exception after logging it
