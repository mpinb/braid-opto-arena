# ./src/trigger_handler.py
import json
import logging
import time

import numpy as np
from .csv_writer import CsvWriter
from .devices.opto_trigger import OptoTrigger
from .fly_heading_tracker import FlyHeadingTracker
from .messages import Publisher

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(name="Trigger Handler")


class TriggerHandler:
    def __init__(
        self,
        config: dict,
        opto_trigger: OptoTrigger | None,
        csv_writer: CsvWriter | None,
        trigger_publisher: Publisher,
    ):
        """
        Initializes the TriggerHandler class.

        Args:
            config (dict): The configuration dictionary.
            opto_trigger (OptoTrigger): The OptoTrigger instance.
            csv_writer (CsvWriter): The CsvWriter instance.
            trigger_publisher (Publisher): The Publisher instance.

        Attributes:
            config (dict): The configuration dictionary.
            opto_trigger (OptoTrigger): The OptoTrigger instance.
            csv_writer (CsvWriter): The CsvWriter instance.
            trigger_publisher (Publisher): The Publisher instance.
            trigger_time (float): The trigger time.
            obj_birth_times (dict): The dictionary of object birth times.
            obj_heading (dict): The dictionary of object headings.
        """
        self.config = config
        self.opto_trigger = opto_trigger
        self.csv_writer = csv_writer
        self.trigger_publisher = trigger_publisher

        self.trigger_counter = 0
        self.trigger_time = 0.0
        self.obj_birth_times = {}
        self.obj_heading = {}

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
            # check if object heading is already tracked
            if obj_id in self.obj_heading:
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

    def _check_trigger_conditions(self, msg_dict):
        """
        Checks if the given `msg_dict` satisfies all the trigger conditions.

        Args:
            msg_dict (dict): A dictionary containing the object's ID, x-coordinate, y-coordinate, and z-coordinate.

        Returns:
            bool: True if all the trigger conditions are satisfied, False otherwise.

        This function checks if the trajectory of the object with the given ID has been detected for longer than the minimum trajectory time specified in the configuration. It also checks if enough time has passed since the last trigger. Additionally, it checks if the object is within the specified zone, either a radius or a box.

        The function first retrieves the current time and the object's ID from the `msg_dict`. It then checks if the time elapsed since the object's birth is less than the minimum trajectory time. If it is, the function logs a debug message and returns False.

        Next, the function checks if enough time has passed since the last trigger. If it hasn't, the function logs a debug message and returns False.

        If the object is within the specified zone, the function calculates the radius of the object from the center of the radius zone and checks if it is less than or equal to the distance specified in the configuration. If it is, the function returns True.

        If the zone type is "box", the function checks if the object's x-coordinate, y-coordinate, and z-coordinate are within the specified box boundaries. If all the conditions are met, the function returns True.

        If the zone type is unknown, the function logs a debug message and returns False.

        Note: The function assumes that the `msg_dict` contains the necessary keys: "obj_id", "x", "y", and "z".
        """
        curr_time = time.time()
        obj_id = msg_dict["obj_id"]

        # check if the trajectory was detected for longer than min_trajectory_time
        if (
            curr_time - self.obj_birth_times[obj_id]
            < self.config["min_trajectory_time"]
        ):
            logger.debug("Trajectory not long enough")
            return False

        # check if the trigger interval has passed
        if curr_time - self.trigger_time < self.config["min_trigger_interval"]:
            logger.debug("Not enough time passed since last trigger.")
            return False

        # check if object is within zone (either radius or box)
        if self.config["zone_type"] == "radius":
            # check both the radius and the z limit
            rad = np.sqrt(
                (msg_dict["x"] - self.config["radius"]["center"][0]) ** 2
                + (msg_dict["y"] - self.config["radius"]["center"][1]) ** 2
            )

            rad_condition = rad <= self.config["radius"]["distance"]
            z_condition = (
                self.config["radius"]["z"][0]
                <= msg_dict["z"]
                <= self.config["radius"]["z"][1]
            )
            return rad_condition and z_condition

        elif self.config["zone_type"] == "box":
            x_condition = (
                self.config["box"]["x"][0]
                <= msg_dict["x"]
                <= self.config["box"]["x"][1]
            )
            y_condition = (
                self.config["box"]["y"][0]
                <= msg_dict["y"]
                <= self.config["box"]["y"][1]
            )
            z_condition = (
                self.config["box"]["z"][0]
                <= msg_dict["z"]
                <= self.config["box"]["z"][1]
            )
            return x_condition and y_condition and z_condition
        else:
            logging.debug(f"Unknown zone type: {self.config['zone_type']}")
            return False

    def _trigger_action(self, msg_dict):
        """
        Triggers an action based on the given message dictionary.

        Args:
            msg_dict (dict): A dictionary containing the message. It should have the following keys:
                - 'obj_id' (Any): The ID of the object.

        This function saves the current time as the trigger time, triggers the opto if it is activated,
        adds the heading to the message dictionary if the object ID is in the obj_heading dictionary,
        sends the trigger to the trigger publisher, writes the message dictionary to the CSV writer,
        and logs an info message indicating that the action was triggered for the object.

        Returns:
            None
        """
        obj_id = msg_dict["obj_id"]
        msg_dict["timestamp"] = time.time()

        # save the trigger time
        self.trigger_time = time.time()

        # trigger opto if activated
        if self.opto_trigger is not None:
            sham = self.opto_trigger.trigger()
            msg_dict["sham"] = sham

        # add the heading to the data
        if obj_id in self.obj_heading:
            msg_dict["heading"] = self.obj_heading[obj_id].get_average_heading()
        else:
            logging.debug(f"{obj_id} not in obj_heading")

        # send trigger to publisher
        self.trigger_publisher.send("trigger", json.dumps(msg_dict))

        # save data to csv
        if self.csv_writer is not None:
            self.csv_writer.write_row(msg_dict)

        logging.info(
            f"Triggered action #{self.trigger_counter} for object {msg_dict['obj_id']}"
        )
        self.trigger_counter += 1
