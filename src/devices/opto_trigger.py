# ./src/devices/opto_trigger.py
import serial
import logging
import random
from typing import Optional, Type, TracebackType

logging.basicConfig(level=logging.INFO)


class OptoTrigger:
    def __init__(
        self,
        config: dict,
        connect_on_init: bool = True,
    ) -> None:
        """
        Initializes an instance of the OptoTrigger class.

        Args:
            config (Dict[str, Dict[str, Union[str, int]]]): A dictionary containing the configuration settings.
            connect_on_init (bool, optional): Whether to connect to the Arduino upon initialization. Defaults to True.

        Returns:
            None

        Initializes the instance variables of the OptoTrigger class with the values from the provided configuration.
        Sets the port, baudrate, and device to the corresponding values from the configuration.
        Sets the duration, intensity, and frequency to the corresponding values from the configuration.
        Logs the connection information and the stimulation parameters.
        If connect_on_init is True, calls the connect() method to establish the connection to the Arduino.
        """
        self.config = config

        self.port: str = self.config["hardware"]["arduino"]["port"]
        self.baudrate: int = self.config["hardware"]["arduino"]["baudrate"]
        self.device: Optional[serial.Serial] = None

        self.duration: int = self.config["optogenetic_light"]["duration"]
        self.intensity: float = self.config["optogenetic_light"]["intensity"]
        self.frequency: float = self.config["optogenetic_light"]["frequency"]

        logging.info(f"Connecting to arduino at {self.port}")
        logging.debug(
            f"Stim parameters: duration {self.duration} intensity {self.intensity} frequency {self.frequency}"
        )
        if connect_on_init:
            self.connect()

    def __enter__(self) -> "OptoTrigger":
        if not self.device:
            self.connect()
        return self

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_value: Optional[BaseException],
        traceback: Optional[TracebackType],
    ) -> None:
        """
        Exit the context manager.

        Args:
            exc_type (Optional[Type[BaseException]]): The type of exception raised, if any.
            exc_value (Optional[BaseException]): The exception raised, if any.
            traceback (Optional[TracebackType]): The traceback of the exception, if any.

        Returns:
            None
        """
        self.close()

    def connect(self) -> None:
        try:
            self.device = serial.Serial(self.port, self.baudrate)
        except Exception as e:
            logging.error(f"Could not connect to arduino: {e}")

    def trigger(self) -> None:
        if self._sham():
            logging.debug("Sham trial")
        else:
            if self.device:
                self.device.write(
                    f"<{self.duration} {self.intensity} {self.frequency}>".encode(
                        "utf-8"
                    )
                )
            else:
                logging.error("Cannot trigger: device is not connected")

    def _sham(self) -> bool:
        return (
            random.randint(0, 100)
            < self.config["optogenetic_light"]["sham_trial_percentage"]
        )

    def close(self) -> None:
        if self.device:
            self.device.close()
            self.device = None
            logging.info("Arduino disconnected")
        else:
            logging.debug("Arduino was not connected")
