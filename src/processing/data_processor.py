import json
import time
from typing import Dict, Any, List


from src.core.messages import Publisher
from src.utils.csv_writer import CsvWriter
from src.devices.opto import OptoTrigger
from src.utils.log_config import setup_logging
from src.processing.trajectory import RealTimeHeadingCalculator, check_position


logger = setup_logging(logger_name="Main", level="INFO")


class DataProcessor:
    def __init__(
        self,
        params: Dict[str, Any],
        pub: Publisher,
        csv_writer: CsvWriter,
        opto_trigger: OptoTrigger = None,
        pub_plot=None,
    ):
        self.params = params
        self.pub = pub
        self.csv_writer = csv_writer
        self.opto_trigger = opto_trigger
        self.pub_plot = pub_plot

        self.obj_ids: List[str] = []
        self.obj_birth_times: Dict[str, float] = {}
        self.headings: Dict[str, RealTimeHeadingCalculator] = {}
        self.last_trigger_time: float = time.time()
        self.ntrig: int = 0

        self.trigger_params = params["trigger_params"]
        self.opto_params = params["opto_params"]

    async def process_data(self, data: Dict[str, Any]) -> None:
        tcall = time.time()

        try:
            msg_dict = data["msg"]
        except KeyError:
            return

        if "Birth" in msg_dict:
            self._handle_birth(msg_dict["Birth"], tcall)
        elif "Update" in msg_dict:
            await self._handle_update(msg_dict["Update"], tcall)
        elif "Death" in msg_dict:
            self._handle_death(msg_dict["Death"])

    def _handle_birth(self, birth_data: Dict[str, Any], tcall: float) -> None:
        curr_obj_id = birth_data["obj_id"]
        self.obj_ids.append(curr_obj_id)
        self.obj_birth_times[curr_obj_id] = tcall
        self.headings[curr_obj_id] = RealTimeHeadingCalculator()

    async def _handle_update(self, update_data: Dict[str, Any], tcall: float) -> None:
        curr_obj_id = update_data["obj_id"]

        if curr_obj_id not in self.headings:
            self.headings[curr_obj_id] = RealTimeHeadingCalculator()
        self.headings[curr_obj_id].add_data_point(
            update_data["xvel"],
            update_data["yvel"],
            update_data["zvel"],
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

        pos = update_data

        if self.pub_plot:
            logger.debug(f"Publishing message to 'plot': {pos}")
            self.pub_plot.send_string(json.dumps(pos))

        if check_position(pos, self.trigger_params):
            self.ntrig += 1
            self.last_trigger_time = tcall

            pos["trigger_time"] = self.last_trigger_time
            pos["ntrig"] = self.ntrig
            pos["main_timestamp"] = tcall
            pos["heading_direction"] = self.headings[curr_obj_id].calculate_heading()

            if self.opto_params.get("active", False) and self.opto_trigger:
                logger.info("Triggering opto.")
                pos = await self._trigger_opto(pos)

            logger.debug(f"Publishing message to 'trigger': {pos}")
            await self.pub.publish(json.dumps(pos), "trigger")
            self.csv_writer.write(pos)

    def _handle_death(self, death_data: str) -> None:
        curr_obj_id = death_data
        if curr_obj_id in self.obj_ids:
            self.obj_ids.remove(curr_obj_id)

    async def _trigger_opto(self, pos: Dict[str, Any]) -> Dict[str, Any]:
        try:
            duration, intensity, frequency = self.opto_trigger.trigger()
            pos["opto_duration"] = duration
            pos["opto_intensity"] = intensity
            pos["opto_frequency"] = frequency
        except Exception as e:
            logger.error(f"Failed to trigger opto: {e}")
        return pos
