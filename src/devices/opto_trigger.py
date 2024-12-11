import serial
import logging
import random
import time
from typing import Optional, Tuple, NamedTuple
from dataclasses import dataclass

logging.basicConfig(level=logging.INFO)


@dataclass
class TriggerResult:
    timestamp: int
    execution_time: int
    delay: int
    is_sham: bool


class OptoTrigger:
    def __init__(
        self,
        config: dict,
        connect_on_init: bool = True,
    ) -> None:
        self.config = config
        self.port: str = self.config["hardware"]["arduino"]["port"]
        self.baudrate: int = self.config["hardware"]["arduino"]["baudrate"]
        self.device: Optional[serial.Serial] = None

        # Stimulation parameters
        self.duration: int = self.config["optogenetic_light"]["duration"]
        self.intensity: float = self.config["optogenetic_light"]["intensity"]
        self.frequency: float = self.config["optogenetic_light"]["frequency"]
        self.sham_rate: int = self.config["optogenetic_light"]["sham_trial_percentage"]

        # Timing synchronization variables
        self.sync_offset = None
        self.network_latency = None

        logging.info(f"Connecting to arduino at {self.port}")
        logging.debug(
            f"Stim parameters: duration {self.duration} intensity {self.intensity} "
            f"frequency {self.frequency} sham_rate {self.sham_rate}"
        )

        if connect_on_init:
            self.connect()
            self.synchronize()
            self.set_parameters()

    def __enter__(self) -> "OptoTrigger":
        if not self.device:
            self.connect()
            self.synchronize()
            self.set_parameters()
        return self

    def __exit__(
        self,
        exc_type,
        exc_value,
        traceback,
    ) -> None:
        self.close()

    def connect(self) -> None:
        try:
            self.device = serial.Serial(self.port, self.baudrate)
            time.sleep(2)  # Wait for Arduino reset
        except Exception as e:
            logging.error(f"Could not connect to arduino: {e}")
            raise

    def synchronize(self) -> Tuple[int, int]:
        """Synchronize time with Arduino"""
        if not self.device:
            raise RuntimeError("Device not connected")

        try:
            # Send sync message
            self.device.write(b"SYNC\n")
            t1 = int(time.time() * 1000)

            # Wait for Arduino response
            response = self.device.readline().decode().strip()
            t3 = int(time.time() * 1000)

            # Parse Arduino timestamp
            arduino_time = int(response)

            # Calculate network latency and offset
            self.network_latency = (t3 - t1) // 2
            self.sync_offset = t1 - arduino_time + self.network_latency

            logging.info(
                f"Synchronized with Arduino. Offset: {self.sync_offset}ms, "
                f"Latency: {self.network_latency}ms"
            )

            return self.sync_offset, self.network_latency
        except Exception as e:
            logging.error(f"Synchronization failed: {e}")
            raise

    def set_parameters(self) -> None:
        """Set stimulation parameters on Arduino"""
        if not self.device:
            raise RuntimeError("Device not connected")

        try:
            # Validate parameters
            if not (
                0 <= self.frequency <= 100
                and 0 <= self.duration <= 1000
                and 0 <= self.intensity <= 255
                and 0 <= self.sham_rate <= 100
            ):
                raise ValueError("Parameters out of range")

            # Send parameters
            message = f"PARAM {self.frequency},{self.duration},"
            message += f"{int(self.intensity)},{self.sham_rate}\n"
            self.device.write(message.encode())

            # Wait for confirmation
            response = self.device.readline().decode().strip()
            if response != "OK":
                raise RuntimeError(f"Failed to set parameters: {response}")

            logging.debug("Parameters set successfully")
        except Exception as e:
            logging.error(f"Failed to set parameters: {e}")
            raise

    def trigger(self) -> TriggerResult:
        """
        Trigger the stimulation
        Returns: TriggerResult object containing timing information and sham status
        """
        if not self.device:
            raise RuntimeError("Cannot trigger: device not connected")

        try:
            # Get current timestamp
            detection_time = int(time.time() * 1000)

            # Send detection command with timestamp
            message = f"DETECT {detection_time}\n"
            self.device.write(message.encode())

            # Wait for execution confirmation
            response = self.device.readline().decode().strip()
            det_time, exec_time, sham_status = response.split(",")

            result = TriggerResult(
                timestamp=int(det_time),
                execution_time=int(exec_time),
                delay=int(exec_time) - int(det_time),
                is_sham=(sham_status == "SHAM"),
            )

            logging.info(
                f"{'Sham' if result.is_sham else 'Real'} trigger executed with "
                f"{result.delay}ms delay"
            )

            return result

        except Exception as e:
            logging.error(f"Trigger failed: {e}")
            raise

    def close(self) -> None:
        if self.device:
            self.device.close()
            self.device = None
            logging.info("Arduino disconnected")
        else:
            logging.debug("Arduino was not connected")
