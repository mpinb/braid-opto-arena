# -*- coding: utf-8 -*-
"""
Simple class for controlling RS-3000 and 6000-series programmable power supplies

Not tested with 6000-series, and a few features for 6000-series are not implemented.
Please feel free to fork and push these missing features:
    * Support for two channels
    * STATUS? and SAV, RCL functions

Andreas Svela 2020
"""

import time

import numpy as np
import serial
from typing import TracebackType, Optional, Type

PORT = "/dev/ttyACM1"
_CONNECTION_SETTINGS = {
    "baudrate": 9600,
    "parity": serial.PARITY_NONE,
    "bytesize": serial.EIGHTBITS,
    "stopbits": serial.STOPBITS_ONE,
}


class PowerSupply:
    """Control for RS PRO 3000/6000 Series programmable power supply"""

    _is_open = False

    def __init__(
        self,
        port: str = PORT,
        connection_settings: dict = _CONNECTION_SETTINGS,
        open_on_init: bool = True,
        timeout: float = 1.0,
        verbose: bool = True,
    ) -> None:
        self.port = port
        self.connection_settings = connection_settings
        self.timeout = timeout
        self.verbose = verbose
        if open_on_init:
            self.open_connection()

    def __enter__(self) -> "PowerSupply":
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        if self._is_open:
            self.set_voltage(0.0)
            self.dev.close()

    def _write(self, command: str) -> int:
        return self.dev.write(command.encode())

    def _query(self, command: str) -> str:
        self._write(command)
        ret = self.dev.readline().decode("utf-8").strip()
        if not ret:
            time.sleep(0.2)
            self._write(command)
            ret = self.dev.readline().decode("utf-8").strip()
        return ret

    def open_connection(self, timeout: Optional[float] = None) -> None:
        if timeout is not None:
            self.timeout = timeout
        for _ in range(3):
            try:
                self.dev = serial.Serial(
                    self.port, **self.connection_settings, timeout=self.timeout
                )
                break
            except serial.SerialException:
                pass
        else:
            raise RuntimeError(f"Could not connect to {self.port}")
        self._is_open = True
        self.dev.flush()
        self.idn = self.get_idn()
        if self.verbose:
            print(f"Connected to {self.idn}")

    def get_idn(self) -> str:
        return self._query("*IDN?")

    def set_output(self, state: str) -> None:
        if "RS-300" not in self.idn:
            raise NotImplementedError(
                "The set_output() function only works with 6000 series"
            )
        self._write(f"OUT{state}")

    def get_actual_current(self) -> float:
        current = float(self._query("IOUT1?"))
        return current if 0 <= current <= 5 else np.nan

    def set_current(self, current: float) -> None:
        self._write(f"ISET1:{current}")

    def get_actual_voltage(self) -> float:
        voltage = float(self._query("VOUT1?"))
        return voltage if 0 <= voltage <= 30 else np.nan

    def set_voltage(self, voltage: float) -> None:
        """
        Sets the voltage of the power supply to the specified value.
        """
        self._write(f"VSET1:{voltage}")
