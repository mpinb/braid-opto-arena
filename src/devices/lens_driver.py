"""
Hardware interface for the liquid lens controller.
Handles serial communication, command formatting, and safe operation modes.
"""
import struct
import serial
import time
import logging
from enum import Enum
from typing import Tuple, Optional, Callable
from contextlib import contextmanager

class LensMode(Enum):
    CURRENT = 1
    FOCAL_POWER = 5

class LensDriver:
    def __init__(self, port: str, debug: bool = False):
        self.debug = debug
        self.logger = self._setup_logger()
        self.connection = self._setup_connection(port)
        
        # Initialize hardware state
        self._handshake()
        self.firmware_type = self._get_firmware_type()
        self.max_output_current = self._get_max_output_current()
        self.mode: Optional[LensMode] = None
        self._refresh_active_mode()

    def _setup_logger(self) -> logging.Logger:
        logger = logging.getLogger("LensDriver")
        logger.setLevel(logging.DEBUG if self.debug else logging.INFO)
        return logger

    def _setup_connection(self, port: str) -> serial.Serial:
        """Initialize serial connection with safe defaults."""
        connection = serial.Serial(
            port=port,
            baudrate=115200,
            timeout=1.0,  # Default read timeout
            write_timeout=1.0  # Default write timeout
        )
        connection.flush()
        return connection

    @contextmanager
    def _temp_timeout(self, timeout: float):
        """Temporarily change serial connection timeout."""
        old_timeout = self.connection.timeout
        try:
            self.connection.timeout = timeout
            yield
        finally:
            self.connection.timeout = old_timeout

    def _send_command(self, command: str, reply_fmt: Optional[str] = None, 
                     timeout: Optional[float] = None) -> Optional[Tuple]:
        """Send command to device with optional timeout override."""
        command_bytes = command.encode("ascii") if isinstance(command, str) else command
        command_with_crc = command_bytes + struct.pack("<H", self._crc_16(command_bytes))

        if timeout is None:
            timeout = self.connection.timeout

        with self._temp_timeout(timeout):
            try:
                self.connection.write(command_with_crc)
                
                if reply_fmt is None:
                    return None

                response_size = struct.calcsize(reply_fmt)
                response = self.connection.read(response_size + 4)

                if not response:
                    raise TimeoutError("No response received")

                data, crc, newline = struct.unpack(f"<{response_size}sH2s", response)
                if crc != self._crc_16(data) or newline != b"\r\n":
                    raise ValueError("Response CRC check failed")

                return struct.unpack(reply_fmt, data)

            except (serial.SerialTimeoutException, TimeoutError) as e:
                self.logger.warning(f"Command timed out: {e}")
                raise TimeoutError(f"Command timed out after {timeout}s")

    def set_mode(self, mode: str) -> None:
        """Set lens operating mode with fast timeout."""
        with self._temp_timeout(0.5):  # Fast mode switching
            if mode == "current":
                self._send_command("MwDA", ">xxx")
                self.mode = LensMode.CURRENT
            elif mode == "focal_power":
                self._send_command("MwCA", ">xxxBhh")
                self.mode = LensMode.FOCAL_POWER
            else:
                raise ValueError("Invalid mode. Choose 'current' or 'focal_power'")
            
            self._refresh_active_mode()

    def set_value(self, value: float) -> None:
        """Set lens value (current or focal power) based on current mode."""
        if self.mode == LensMode.CURRENT:
            self.set_current(value)
        elif self.mode == LensMode.FOCAL_POWER:
            self.set_diopter(value)
        else:
            raise ValueError(f"Invalid mode: {self.mode}")

    def get_value(self) -> float:
        """Get current lens value based on mode."""
        return self.get_current() if self.mode == LensMode.CURRENT else self.get_diopter()

    def set_current(self, current: float) -> None:
        """Set lens current with validation."""
        if self.mode != LensMode.CURRENT:
            raise ValueError(f"Cannot set current in {self.mode} mode")
        raw_current = int(current * 4095 / self.max_output_current)
        self._send_command(b"Aw" + struct.pack(">h", raw_current))

    def set_diopter(self, diopter: float) -> None:
        """Set lens diopter with validation."""
        if self.mode != LensMode.FOCAL_POWER:
            raise ValueError(f"Cannot set diopter in {self.mode} mode")
        raw_diopter = int((diopter + 5) * 200 if self.firmware_type == "A" else diopter * 200)
        self._send_command(b"PwDA" + struct.pack(">h", raw_diopter) + b"\x00\x00")

    def safe_shutdown(self, timeout: float = 0.5) -> None:
        """Safely shutdown the lens with timeout."""
        try:
            if timeout <= 0:
                return

            start_time = time.perf_counter()
            current_value = self.get_value()

            if abs(current_value) > 0.1:  # Only ramp if not near zero
                steps = 3  # Minimal steps for shutdown
                step_time = timeout / (steps + 1)  # Reserve time for final close
                
                for i in range(steps + 1):
                    if time.perf_counter() - start_time >= timeout:
                        break
                        
                    target = current_value * (1 - i/steps)
                    try:
                        with self._temp_timeout(min(step_time/2, 0.1)):
                            self.set_value(target)
                    except TimeoutError:
                        break

        except Exception as e:
            self.logger.warning(f"Error during safe shutdown: {e}")
        finally:
            self.close()

    def close(self) -> None:
        """Close connection immediately."""
        if self.connection and self.connection.is_open:
            self.connection.close()

    @staticmethod
    def _crc_16(s: bytes) -> int:
        """Calculate CRC-16 for command validation."""
        crc = 0x0000
        for c in s:
            crc = crc ^ c
            for _ in range(8):
                crc = (crc >> 1) ^ 0xA001 if (crc & 1) > 0 else crc >> 1
        return crc

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.safe_shutdown()