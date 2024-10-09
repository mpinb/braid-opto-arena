import requests
import json
import logging
import time
from typing import Iterator
from src.messages import Publisher

DATA_PREFIX = "data: "


class BraidProxy:
    def __init__(
        self,
        base_url: str,
        event_port: int,
        control_port: int,
        zmq_pub_port: int,
        auto_connect: bool = True,
    ):
        self.event_url = f"{base_url}:{event_port}/events"
        self.control_url = f"{base_url}:{control_port}/callback"
        self.session = requests.Session()
        self.logger = logging.getLogger(__name__)

        # Set up ZeroMQ publisher
        self.publisher = Publisher(zmq_pub_port)
        self.publisher.initialize()

        self.stream = None
        if auto_connect:
            self.connect_to_event_stream()

    def connect_to_event_stream(self):
        """
        Connects to the Braid proxy server and retrieves the events stream.
        """
        if self.stream is None:  # Connect only if not already connected
            try:
                self.stream = self.session.get(
                    self.event_url, stream=True, headers={"Accept": "text/event-stream"}
                )
                self.stream.raise_for_status()
            except requests.RequestException as e:
                self.logger.error(f"Failed to connect to event stream: {e}")
                raise

    def toggle_recording(self, start: bool):
        """
        Toggles the recording on or off.
        """
        payload = {"DoRecordCsvTables": start}
        headers = {"Content-Type": "application/json"}

        try:
            response = self.session.post(
                self.control_url, data=json.dumps(payload), headers=headers
            )
            response.raise_for_status()
            self.logger.info(
                f"{'Started' if start else 'Stopped'} recording successfully"
            )
        except requests.RequestException as e:
            self.logger.error(
                f"Failed to {'start' if start else 'stop'} recording: {e}"
            )
            raise

    def process_events(self):
        """
        Processes events from the Braid proxy and publishes them via ZMQ.
        """
        for chunk in self.stream.iter_content(chunk_size=None, decode_unicode=True):
            if chunk:
                try:
                    parsed_data = self.parse_chunk(chunk)
                    received_time = time.time()
                    self.logger.debug(f"Received message at {received_time}")

                    # Add timestamp to the message
                    parsed_data["received_time"] = received_time

                    # Publish the message
                    self.publisher.send("braid_event", json.dumps(parsed_data))
                except (AssertionError, json.JSONDecodeError) as e:
                    self.logger.error(f"Failed to parse chunk: {e}")

    @staticmethod
    def parse_chunk(chunk: str) -> dict:
        """
        Parses a chunk of data and returns the parsed JSON object.
        """
        lines = chunk.strip().split("\n")
        assert len(lines) == 2, "Invalid chunk format"
        assert lines[0] == "event: braid", "Invalid event type"
        assert lines[1].startswith(DATA_PREFIX), "Invalid data prefix"

        buf = lines[1][len(DATA_PREFIX) :]
        return json.loads(buf)

    def close(self):
        """
        Closes the publisher and terminates the ZMQ context.
        """
        self.publisher.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


if __name__ == "__main__":
    braidproxy = BraidProxy()
