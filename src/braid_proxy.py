import requests
import json
import logging
from typing import Iterator

DATA_PREFIX = "data: "


class BraidProxy:
    def __init__(
        self,
        base_url: str,
        event_port: int,
        control_port: int,
        auto_connect: bool = True,
    ):
        self.event_url = f"{base_url}:{event_port}/events"
        self.control_url = f"{base_url}:{control_port}/callback"
        self.session = requests.Session()
        self.logger = logging.getLogger(__name__)

        self.raw_sock = None
        self.stream = None
        if auto_connect:
            self.connect_to_event_stream()

    def __enter__(self):
        """
        Context manager entry point. Ensures connection is established.

        Returns:
            BraidProxy: The instance itself.
        """
        if self.stream is None:
            self.connect_to_event_stream()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """
        Context manager exit point. Ensures proper cleanup of resources.

        Args:
            exc_type: The type of the exception that occurred, if any
            exc_value: The instance of the exception that occurred, if any
            traceback: The traceback of the exception that occurred, if any
        """
        self.close()

    def close(self):
        """
        Closes all open resources and connections.
        """
        if self.stream is not None:
            self.stream.close()
            self.stream = None

        if self.raw_sock is not None:
            self.raw_sock = None

        if self.session is not None:
            self.session.close()
            self.session = None

        self.logger.debug("Closed all BraidProxy connections and resources")

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
                # self.raw_sock = self.stream.raw._fp.fp.raw
            except requests.RequestException as e:
                self.logger.debug(f"Failed to connect to event stream: {e}")
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

    def iter_events(self, timeout=60) -> Iterator[dict]:
        """
        Iterates over events from the Braid proxy.

        Yields:
            dict: The parsed event data.
        """
        for chunk in self.stream.iter_content(chunk_size=None, decode_unicode=True):
            if chunk:
                try:
                    yield self.parse_chunk(chunk)
                except (AssertionError, json.JSONDecodeError) as e:
                    self.logger.error(f"Failed to parse chunk: {e}")

    @staticmethod
    def parse_chunk(chunk: str) -> dict:
        """
        Parses a chunk of data and returns the parsed JSON object.

        Args:
            chunk (str): The chunk of data to be parsed.

        Returns:
            dict: The parsed JSON object.

        Raises:
            AssertionError: If the chunk format is invalid.
            json.JSONDecodeError: If JSON decoding fails.
        """
        lines = chunk.strip().split("\n")
        assert len(lines) == 2, "Invalid chunk format"
        assert lines[0] == "event: braid", "Invalid event type"
        assert lines[1].startswith(DATA_PREFIX), "Invalid data prefix"

        buf = lines[1][len(DATA_PREFIX) :]
        return json.loads(buf)
