import json
import os
import time
from typing import Any, Dict, List

from src.core.messages import Publisher
from devices.opto_trigger import OptoTrigger
from src.processing.trajectory import RealTimeHeadingCalculator, check_position
from src.utils.csv_writer import CsvWriter
from src.utils.log_config import setup_logging

logger = setup_logging(logger_name="Main", level="INFO")


class DataProcessor:
    def __init__(
        self,
        params: Dict[str, Any],
        braid_folder: str,
    ):
        """
        Initializes a DataProcessor object.

        Args:
            params (Dict[str, Any]): A dictionary of parameters for the DataProcessor.
            braid_folder: str: The path of the braid folder.

        Attributes:
            params (Dict[str, Any]): A dictionary of parameters for the DataProcessor.
            pub (Publisher): The publisher object used to publish data.
            csv_writer (CsvWriter): The CSV writer object used to write data to a CSV file.
            opto_trigger (OptoTrigger): The OptoTrigger object used to trigger the opto stimulus.
            obj_ids (List[str]): A list of object IDs.
            obj_birth_times (Dict[str, float]): A dictionary mapping object IDs to their birth times.
            headings (Dict[str, RealTimeHeadingCalculator]): A dictionary mapping object IDs to RealTimeHeadingCalculator objects.
            last_trigger_time (float): The timestamp of the last trigger.
            ntrig (int): The number of triggers.
            trigger_params (Dict[str, Any]): A dictionary of trigger parameters.
            opto_params (Dict[str, Any]): A dictionary of opto parameters.
        """

        # parameters
        self.params = params
        self.trigger_params = params["trigger_params"]
        self.opto_params = params["opto_params"]

        # csv writer
        self.csv_writer = CsvWriter(os.path.join(braid_folder, "opto.csv"))
        self.csv_writer.open()

        # opto trigger
        self.opto_trigger = (
            self.setup_opto_device() if self.trigger_params["active"] else None
        )

        # tracking
        self.obj_ids: List[int] = []
        self.obj_birth_times: Dict[int, float] = {}
        self.headings: Dict[int, RealTimeHeadingCalculator] = {}
        self.last_trigger_time: float = time.time()
        self.ntrig: int = 0

        # publisher
        self.pub = Publisher(port=5555)

    def setup_opto_device(self):
        opto_trigger = OptoTrigger(
            port=self.params["arduino_devices"]["opto_trigger"],
            baudrate=9600,
            params=self.opto_params,
        )
        opto_trigger.connect()
        return opto_trigger

    def process_data(self, data: Dict[str, Any]) -> None:
        tcall = time.time()

        try:
            msg_dict = data["msg"]
        except KeyError:
            return

        if "Birth" in msg_dict:
            self._handle_birth(msg_dict["Birth"], tcall)
        elif "Update" in msg_dict:
            self._handle_update(msg_dict["Update"], tcall)
        elif "Death" in msg_dict:
            self._handle_death(msg_dict["Death"])

    def _handle_birth(self, birth_data: Dict[str, Any], tcall: float) -> None:
        curr_obj_id = birth_data["obj_id"]
        self.obj_ids.append(curr_obj_id)
        self.obj_birth_times[curr_obj_id] = tcall
        self.headings[curr_obj_id] = RealTimeHeadingCalculator()

    def _handle_update(self, pos: Dict[str, Any], tcall: float) -> None:
        curr_obj_id = pos["obj_id"]

        if curr_obj_id not in self.headings:
            self.headings[curr_obj_id] = RealTimeHeadingCalculator()
        self.headings[curr_obj_id].add_data_point(
            pos["xvel"],
            pos["yvel"],
            pos["zvel"],
        )

        if curr_obj_id not in self.obj_ids:
            self.obj_ids.append(curr_obj_id)
            self.obj_birth_times[curr_obj_id] = tcall
            return

        if (tcall - self.obj_birth_times[curr_obj_id]) < self.trigger_params[
            "min_trajectory_time"
        ]:
            return

        if tcall - self.last_trigger_time < self.trigger_params["min_trigger_interval"]:
            return

        if check_position(pos, self.trigger_params):
            self.ntrig += 1
            self.last_trigger_time = tcall

            pos["trigger_time"] = self.last_trigger_time
            pos["ntrig"] = self.ntrig
            pos["main_timestamp"] = tcall
            pos["heading_direction"] = self.headings[curr_obj_id].calculate_heading()

            if self.opto_params.get("active", False) and self.opto_trigger:
                logger.info("Triggering opto.")
                pos = self._trigger_opto(pos)

            logger.debug(f"Publishing message to 'trigger': {pos}")
            self.pub.publish(json.dumps(pos), "trigger")
            self.csv_writer.write(pos)

    def _handle_death(self, death_data: str) -> None:
        curr_obj_id = death_data
        if curr_obj_id in self.obj_ids:
            self.obj_ids.remove(curr_obj_id)

    def _trigger_opto(self, pos: Dict[str, Any]) -> Dict[str, Any]:
        try:
            duration, intensity, frequency = self.opto_trigger.trigger()
            pos["opto_duration"] = duration
            pos["opto_intensity"] = intensity
            pos["opto_frequency"] = frequency
        except Exception as e:
            logger.error(f"Failed to trigger opto: {e}")
        return pos

    def close(self):
        if self.pub:
            logger.info("Sending kill message to all processes.")
            self.pub.publish("", "kill")
            logger.info("Closing publisher socket.")
            self.pub.close()
        if self.csv_writer:
            logger.info("Closing CSV writer.")
            self.csv_writer.close()
        if self.opto_trigger:
            logger.info("Closing OptoTrigger connection.")
            self.opto_trigger.close()
