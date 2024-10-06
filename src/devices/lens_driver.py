import struct
import serial
import time
import logging
from enum import Enum
from typing import Tuple, Optional, Callable

class LensMode(Enum):
    CURRENT = 1
    FOCAL_POWER = 5

class LensDriver:
    def __init__(self, port: str, debug: bool = False, log_level: int = logging.INFO):
        self.debug = debug
        self.logger = self._setup_logger(log_level)
        self.logger.debug(f"Initializing LensController on port {port}")

        self.connection = serial.Serial(port, 115200, timeout=1)
        self.connection.flush()
        self.logger.debug("Serial connection established and flushed")

        self._handshake()

        self.firmware_type = self._get_firmware_type()
        self.firmware_version = self._get_firmware_version()
        self.max_output_current = self._get_max_output_current()
        self.mode: Optional[LensMode] = None
        self._refresh_active_mode()

        self.logger.info("LensController initialization complete")

    def _setup_logger(self, log_level: int) -> logging.Logger:
        logger = logging.getLogger("LensController")
        logger.setLevel(log_level)
        handler = logging.StreamHandler()
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        return logger

    def _handshake(self) -> None:
        self.connection.write(b"Start")
        response = self.connection.readline()
        if response != b"Ready\r\n":
            self.logger.error(f"Unexpected handshake response: {response}")
            raise Exception("Lens Driver did not reply to handshake")
        self.logger.debug("Handshake successful")

    def _send_command(self, command: str, reply_fmt: Optional[str] = None) -> Optional[Tuple]:
        command_bytes = command.encode("ascii") if isinstance(command, str) else command
        command_with_crc = command_bytes + struct.pack("<H", self._crc_16(command_bytes))
        self.logger.debug(f"Sending command: {command_with_crc.hex()}")
        self.connection.write(command_with_crc)

        if reply_fmt is None:
            return None

        response_size = struct.calcsize(reply_fmt)
        response = self.connection.read(response_size + 4)
        self.logger.debug(f"Received response: {response.hex()}")

        if not response:
            self.logger.error("No response received")
            raise Exception("Expected response not received")

        data, crc, newline = struct.unpack(f"<{response_size}sH2s", response)
        if crc != self._crc_16(data) or newline != b"\r\n":
            self.logger.error("Response CRC check failed")
            raise Exception("Response CRC not correct")

        return struct.unpack(reply_fmt, data)

    def _get_max_output_current(self) -> float:
        self.logger.debug("Getting maximum output current")
        max_current = self._send_command("CrMA\x00\x00", ">xxxh")[0] / 100
        self.logger.debug(f"Maximum output current: {max_current} mA")
        return max_current

    def _get_firmware_type(self) -> str:
        self.logger.debug("Getting firmware type")
        fw_type = self._send_command("H", ">xs")[0].decode("ascii")
        self.logger.debug(f"Firmware type: {fw_type}")
        return fw_type

    def _get_firmware_version(self) -> Tuple[int, int, int, int]:
        self.logger.debug("Getting firmware version")
        version = self._send_command(b"V\x00", ">xBBHH")
        self.logger.debug(f"Firmware version: {version}")
        return version

    def get_temperature(self) -> float:
        self.logger.debug("Getting temperature")
        temp = self._send_command(b"TCA", ">xxxh")[0] * 0.0625
        self.logger.debug(f"Temperature: {temp}°C")
        return temp

    def set_mode(self, mode: str) -> Optional[Tuple[float, float]]:
        self.logger.info(f"Setting mode to {mode}")
        if mode == "current":
            self._send_command("MwDA", ">xxx")
            self.mode = LensMode.CURRENT
        elif mode == "focal_power":
            error, max_fp_raw, min_fp_raw = self._send_command("MwCA", ">xxxBhh")
            self.mode = LensMode.FOCAL_POWER
            min_fp, max_fp = min_fp_raw / 200, max_fp_raw / 200
            if self.firmware_type == "A":
                min_fp, max_fp = min_fp - 5, max_fp - 5
            self.logger.debug(f"Focal power range: {min_fp} to {max_fp}")
            return min_fp, max_fp
        else:
            self.logger.error(f"Invalid mode: {mode}")
            raise ValueError("Invalid mode. Choose 'current' or 'focal_power'.")

        self._refresh_active_mode()
        return None

    def get_mode(self) -> str:
        return self.mode.name.lower() if self.mode else "unknown"

    def _refresh_active_mode(self) -> None:
        self.logger.debug("Refreshing active mode")
        mode_value = self._send_command("MMA", ">xxxB")[0]
        self.mode = LensMode(mode_value)

    def get_current(self) -> float:
        self.logger.debug("Getting current")
        (raw_current,) = self._send_command(b"Ar\x00\x00", ">xh")
        current = raw_current * self.max_output_current / 4095
        self.logger.debug(f"Current: {current} mA")
        return current

    def set_current(self, current: float) -> None:
        self.logger.debug(f"Setting current to {current} mA")
        if self.mode != LensMode.CURRENT:
            raise ValueError(f"Cannot set current when not in current mode. Current mode: {self.get_mode()}")
        raw_current = int(current * 4095 / self.max_output_current)
        self._send_command(b"Aw" + struct.pack(">h", raw_current))

    def get_diopter(self) -> float:
        self.logger.debug("Getting diopter")
        (raw_diopter,) = self._send_command(b"PrDA\x00\x00\x00\x00", ">xxh")
        diopter = raw_diopter / 200 - 5 if self.firmware_type == "A" else raw_diopter / 200
        self.logger.debug(f"Diopter: {diopter}")
        return diopter

    def set_diopter(self, diopter: float) -> None:
        self.logger.debug(f"Setting diopter to {diopter}")
        if self.mode != LensMode.FOCAL_POWER:
            raise ValueError(f"Cannot set focal power when not in focal power mode. Current mode: {self.get_mode()}")
        raw_diopter = int((diopter + 5) * 200 if self.firmware_type == "A" else diopter * 200)
        self._send_command(b"PwDA" + struct.pack(">h", raw_diopter) + b"\x00\x00")

    def ramp_to_zero(self, duration: float = 1.0, steps: int = 50) -> None:
        """
        Ramp the lens setting to zero over a specified duration.
        
        Args:
            duration (float): The time over which to ramp (in seconds).
            steps (int): The number of steps to use in the ramp.
        """
        self.logger.debug(f"Ramping to zero over {duration} seconds with {steps} steps")
        
        if self.mode == LensMode.CURRENT:
            start_value = self.get_current()
            set_func = self.set_current
        elif self.mode == LensMode.FOCAL_POWER:
            start_value = self.get_diopter()
            set_func = self.set_diopter
        else:
            self.logger.warning(f"Unknown mode: {self.mode}. Unable to ramp to zero.")
            return

        self._ramp(start_value, 0, duration, steps, set_func)
        self.logger.info("Ramp to zero complete")

    def _ramp(self, start: float, end: float, duration: float, steps: int, 
               set_func: Callable[[float], None]) -> None:
        """
        General ramping function.
        
        Args:
            start (float): Starting value.
            end (float): Ending value.
            duration (float): Total duration of the ramp in seconds.
            steps (int): Number of steps in the ramp.
            set_func (Callable[[float], None]): Function to set the value at each step.
        """
        step_size = (end - start) / steps
        step_duration = duration / steps
        
        for i in range(steps + 1):
            target_value = start + i * step_size
            set_func(target_value)
            time.sleep(step_duration)

    @staticmethod
    def _crc_16(s: bytes) -> int:
        crc = 0x0000
        for c in s:
            crc = crc ^ c
            for _ in range(8):
                crc = (crc >> 1) ^ 0xA001 if (crc & 1) > 0 else crc >> 1
        return crc

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    def disconnect(self):
        self.logger.info("Disconnecting LensController")
        try:
            self.ramp_to_zero()
        except Exception as e:
            self.logger.error(f"Error while ramping to zero: {e}")
        finally:
            self.connection.close()
            self.logger.info("Serial connection closed")

if __name__ == "__main__":
    with LensDriver("/dev/optotune_ld", debug=True) as lens:
        print(f"Firmware Type: {lens.firmware_type}")
        print(f"Firmware Version: {lens.firmware_version}")
        print(f"Max Output Current: {lens.max_output_current}")
        print(f"Temperature: {lens.get_temperature()}")

        print("Setting mode to current")
        lens.set_mode("current")
        print(f"Current mode: {lens.get_mode()}")
        lens.set_current(50)  # Set current to 50mA

        print("Setting mode to focal_power")
        min_fp, max_fp = lens.set_mode("focal_power")
        print(f"Current mode: {lens.get_mode()}")
        print(f"Focal power range: {min_fp} to {max_fp}")
        lens.set_diopter(3)  # Set focal power to 3 diopters
        print(f"Current focal power: {lens.get_diopter()}")

        # Demonstrate the new ramping function
        print("Ramping to zero")
        lens.ramp_to_zero(duration=2.0, steps=100)  # Slower, smoother ramp
        print("Ramp complete")