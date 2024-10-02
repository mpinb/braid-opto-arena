import struct
import serial
import time
import logging


class LensDriver:
    def __init__(self, port, debug=False, log_level=logging.INFO):
        self.debug = debug
        self.logger = self.setup_logger(log_level)
        self.logger.debug(f"Initializing LensController on port {port}")

        self.connection = serial.Serial(port, 115200, timeout=1)
        self.connection.flush()
        self.logger.debug("Serial connection established and flushed")

        self.connection.write(b"Start")
        response = self.connection.readline()
        if response != b"Ready\r\n":
            self.logger.error(f"Unexpected handshake response: {response}")
            raise Exception("Lens Driver did not reply to handshake")
        self.logger.debug("Handshake successful")

        self.firmware_type = self.get_firmware_type()
        self.firmware_version = self.get_firmware_version()
        self.max_output_current = self.get_max_output_current()
        self.mode = None
        self.refresh_active_mode()

        self.steps = 20  # Number of steps to use when ramping down
        self.step_delay = 0.05  # Delay between steps in seconds

        self.logger.info("LensController initialization complete")

    def setup_logger(self, log_level):
        logger = logging.getLogger("LensController")
        logger.setLevel(log_level)
        handler = logging.StreamHandler()
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        return logger

    def send_command(self, command, reply_fmt=None):
        if isinstance(command, str):
            command = command.encode("ascii")
        command = command + struct.pack("<H", self.crc_16(command))
        self.logger.debug(f"Sending command: {command.hex()}")
        self.connection.write(command)

        if reply_fmt is not None:
            response_size = struct.calcsize(reply_fmt)
            response = self.connection.read(response_size + 4)
            self.logger.debug(f"Received response: {response.hex()}")

            if not response:
                self.logger.error("No response received")
                raise Exception("Expected response not received")

            data, crc, newline = struct.unpack(f"<{response_size}sH2s", response)
            if crc != self.crc_16(data) or newline != b"\r\n":
                self.logger.error("Response CRC check failed")
                raise Exception("Response CRC not correct")

            return struct.unpack(reply_fmt, data)

    def get_max_output_current(self):
        self.logger.debug("Getting maximum output current")
        max_current = self.send_command("CrMA\x00\x00", ">xxxh")[0] / 100
        self.logger.debug(f"Maximum output current: {max_current} mA")
        return max_current

    def get_firmware_type(self):
        self.logger.debug("Getting firmware type")
        fw_type = self.send_command("H", ">xs")[0].decode("ascii")
        self.logger.debug(f"Firmware type: {fw_type}")
        return fw_type

    def get_firmware_version(self):
        self.logger.debug("Getting firmware version")
        version = self.send_command(b"V\x00", ">xBBHH")
        self.logger.debug(f"Firmware version: {version}")
        return version

    def get_temperature(self):
        self.logger.debug("Getting temperature")
        temp = self.send_command(b"TCA", ">xxxh")[0] * 0.0625
        self.logger.debug(f"Temperature: {temp}°C")
        return temp

    def set_mode(self, mode):
        self.logger.info(f"Setting mode to {mode}")
        if mode == "current":
            self.send_command("MwDA", ">xxx")
            self.mode = 1
        elif mode == "focal_power":
            error, max_fp_raw, min_fp_raw = self.send_command("MwCA", ">xxxBhh")
            self.mode = 5
            min_fp, max_fp = min_fp_raw / 200, max_fp_raw / 200
            if self.firmware_type == "A":
                min_fp, max_fp = min_fp - 5, max_fp - 5
            self.logger.debug(f"Focal power range: {min_fp} to {max_fp}")
            return min_fp, max_fp
        else:
            self.logger.error(f"Invalid mode: {mode}")
            raise ValueError("Invalid mode. Choose 'current' or 'focal_power'.")

        self.refresh_active_mode()
        return self.get_mode()

    def get_mode(self):
        mode = (
            "current"
            if self.mode == 1
            else "focal_power"
            if self.mode == 5
            else "unknown"
        )
        self.logger.debug(f"Current mode: {mode}")
        return mode

    def refresh_active_mode(self):
        self.logger.debug("Refreshing active mode")
        self.mode = self.send_command("MMA", ">xxxB")[0]
        return self.get_mode()

    def get_current(self):
        self.logger.debug("Getting current")
        (raw_current,) = self.send_command(b"Ar\x00\x00", ">xh")
        current = raw_current * self.max_output_current / 4095
        self.logger.debug(f"Current: {current} mA")
        return current

    def set_current(self, current):
        self.logger.debug(f"Setting current to {current} mA")
        if self.get_mode() != "current":
            self.logger.error(
                f"Cannot set current when not in current mode. Current mode: {self.get_mode()}"
            )
            raise Exception("Cannot set current when not in current mode")
        raw_current = int(current * 4095 / self.max_output_current)
        self.send_command(b"Aw" + struct.pack(">h", raw_current))

    def get_diopter(self):
        self.logger.debug("Getting diopter")
        (raw_diopter,) = self.send_command(b"PrDA\x00\x00\x00\x00", ">xxh")
        diopter = (
            raw_diopter / 200 - 5 if self.firmware_type == "A" else raw_diopter / 200
        )
        self.logger.debug(f"Diopter: {diopter}")
        return diopter

    def set_diopter(self, diopter):
        self.logger.debug(f"Setting diopter to {diopter}")
        if self.get_mode() != "focal_power":
            self.logger.error(
                f"Cannot set focal power when not in focal power mode. Current mode: {self.get_mode()}"
            )
            raise Exception("Cannot set focal power when not in focal power mode")
        raw_diopter = int(
            (diopter + 5) * 200 if self.firmware_type == "A" else diopter * 200
        )
        self.send_command(b"PwDA" + struct.pack(">h", raw_diopter) + b"\x00\x00")

    def ramp_to_zero(self):
        self.logger.debug("Ramping to zero")
        current_mode = self.get_mode()
        if current_mode == "current":
            start_value = self.get_current()
            for i in range(self.steps + 1):
                value = start_value * (1 - i / self.steps)
                self.set_current(value)
                time.sleep(self.step_delay)
        elif current_mode == "focal_power":
            start_value = self.get_diopter()
            for i in range(self.steps + 1):
                value = start_value * (1 - i / self.steps)
                self.set_diopter(value)
                time.sleep(self.step_delay)
        else:
            self.logger.warning(
                f"Unknown mode: {current_mode}. Unable to ramp to zero."
            )
        self.logger.info("Ramp to zero complete")

    @staticmethod
    def crc_16(s):
        crc = 0x0000
        for c in s:
            crc = crc ^ c
            for _ in range(8):
                crc = (crc >> 1) ^ 0xA001 if (crc & 1) > 0 else crc >> 1
        return crc

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.logger.info("Exiting LensController")
        try:
            self.ramp_to_zero()
        except Exception as e:
            self.logger.error(f"Error while ramping to zero: {e}")
        finally:
            self.connection.close()
            self.logger.info("Serial connection closed")

    def disconnect(self):
        try:
            self.ramp_to_zero()
        except Exception as e:
            self.logger.error(f"Error while ramping to zero: {e}")
        finally:
            self.connection.close()
            self.logger.info("Serial connection closed")


if __name__ == "__main__":
    import time

    with LensDriver("/dev/optotune_ld", debug=False) as lens:
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
