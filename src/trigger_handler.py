import time
import logging
import numpy as np


class TriggerHandler:
    def __init__(self, config, opto_trigger, csv_writer, trigger_publisher):
        self.config = config
        self.opto_trigger = opto_trigger
        self.csv_writer = csv_writer
        self.trigger_publisher = trigger_publisher

        self.trigger_time = time.time()
        self.obj_birth_times = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def close(self):
        # Perform any cleanup here if needed
        logging.info("TriggerHandler is shutting down")

    def handle_birth(self, obj_id):
        logging.debug(f"Got Birth: {obj_id}")
        self.obj_birth_times[obj_id] = time.time()

    def handle_death(self, msg_dict):
        logging.debug(f"Got Death: {msg_dict}")
        if msg_dict in self.obj_birth_times:
            del self.obj_birth_times[msg_dict]

    def handle_update(self, msg_dict):
        logging.debug(f"Got Update: {msg_dict['obj_id']}")
        if msg_dict["obj_id"] in self.obj_birth_times:
            if self._check_trigger_conditions(msg_dict):
                self._trigger_action(msg_dict)

    def _check_trigger_conditions(self, msg_dict):
        curr_time = time.time()
        obj_id = msg_dict["obj_id"]

        if (
            curr_time - self.obj_birth_times[obj_id]
            < self.config["min_trajectory_time"]
        ):
            return False
        if curr_time - self.trigger_time < self.config["min_trigger_interval"]:
            return False

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
        if self.opto_trigger is not None:
            self.opto_trigger.trigger()
        self.trigger_time = time.time()
        self.csv_writer.write_row(msg_dict)
        self.trigger_publisher.send(msg_dict)
        logging.info(f"Triggered action for object {msg_dict['obj_id']}")
