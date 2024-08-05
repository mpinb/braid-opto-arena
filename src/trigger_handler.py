import time
import logging
import numpy as np
from src.fly_heading_tracker import FlyHeadingTracker
from src.devices.opto_trigger import OptoTrigger
from src.csv_writer import CsvWriter
from src.messages import Publisher


class TriggerHandler:
    def __init__(
        self,
        config: dict,
        opto_trigger: OptoTrigger,
        csv_writer: CsvWriter,
        trigger_publisher: Publisher,
    ):
        self.config = config
        self.opto_trigger = opto_trigger
        self.csv_writer = csv_writer
        self.trigger_publisher = trigger_publisher

        self.trigger_time = time.time()
        self.obj_birth_times = {}
        self.obj_heading = {}

    def __enter__(self):
        return self

    def __exit__(self):
        self.close()

    def close(self):
        # Perform any cleanup here if needed
        logging.info("TriggerHandler is shutting down")

    def handle_birth(self, obj_id):
        logging.debug(f"Got Birth: {obj_id}")
        self.obj_birth_times[obj_id] = time.time()
        self.obj_heading[obj_id] = FlyHeadingTracker()

    def handle_death(self, obj_id):
        logging.debug(f"Got Death: {obj_id}")
        if obj_id in self.obj_birth_times:
            del self.obj_birth_times[obj_id]
            del self.obj_heading[obj_id]

    def handle_update(self, msg_dict):
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

    def _check_trigger_conditions(self, msg_dict):
        curr_time = time.time()
        obj_id = msg_dict["obj_id"]

        # check if the trajectory was detected for longer than min_trajectory_time
        if (
            curr_time - self.obj_birth_times[obj_id]
            < self.config["min_trajectory_time"]
        ):
            return False

        # check if the trigger interval has passed
        if curr_time - self.trigger_time < self.config["min_trigger_interval"]:
            return False

        # check if object is within zone (either radius or box)
        if self.config["zone_type"] == "radius":
            rad = np.sqrt(msg_dict["x"] ** 2 + msg_dict["y"] ** 2)
            return rad <= self.config["radius"]["distance"]
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
        obj_id = msg_dict["obj_id"]

        # trigger opto if activated
        if self.opto_trigger is not None:
            self.opto_trigger.trigger()

        # send trigger to publisher
        self.trigger_publisher.send(msg_dict)

        # save the trigger time
        self.trigger_time = time.time()

        # add the heading to the data
        if obj_id in self.obj_heading:
            msg_dict["heading"] = self.obj_heading[obj_id].get_average_heading()

        # save data to csv
        self.csv_writer.write_row(msg_dict)

        logging.info(f"Triggered action for object {msg_dict['obj_id']}")
