import serial
import logging
import random

logging.basicConfig(level=logging.INFO)


class OptoTrigger:
    def __init__(self, config: dict, connect_on_init=True):
        self.config = config

        self.port = self.config["hardware"]["arduino"]["port"]
        self.baudrate = self.config["hardware"]["arduino"]["baudrate"]
        self.device = None

        self.duration = self.config["optogenetic_light"]["duration"]
        self.intensity = self.config["optogenetic_light"]["intensity"]
        self.frequency = self.config["optogenetic_light"]["frequency"]

        logging.info(f"Connecting to arduino at {self.port}")
        logging.debug(
            f"Stim parameters: duration {self.duration} intensity {self.intensity} frequency {self.frequency}"
        )
        if connect_on_init:
            self.connect()

    def __enter__(self):
        if not self.device:
            self.connect()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def connect(self):
        try:
            self.device = serial.Serial(self.port, self.baudrate)
        except Exception as e:
            logging.error(f"Could not connect to arduino: {e}")

    def trigger(self):
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

    def _sham(self):
        return (
            random.randint(0, 100)
            < self.config["optogenetic_light"]["sham_trial_percentage"]
        )

    def close(self):
        if self.device:
            self.device.close()
            self.device = None
            logging.info("Arduino disconnected")
        else:
            logging.debug("Arduino was not connected")
