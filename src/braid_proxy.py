import requests
import json
import logging
import select
from typing import Iterator

DATA_PREFIX = "data: "

class BraidProxy:
    def __init__(self, base_url: str, event_port: int, control_port: int):
        self.event_url = f"{base_url}:{event_port}/events"
        self.control_url = f"{base_url}:{control_port}/callback"
        self.session = requests.Session()
        self.logger = logging.getLogger(__name__)

    def connect_to_event_stream(self):
        """
        Connects to the Braid proxy server and retrieves the events stream.
        """
        try:
            r = self.session.get(self.event_url, stream=True, headers={"Accept": "text/event-stream"})
            r.raise_for_status()
            return r
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
            response = self.session.post(self.control_url, data=json.dumps(payload), headers=headers)
            response.raise_for_status()
            self.logger.info(f"{'Started' if start else 'Stopped'} recording successfully")
        except requests.RequestException as e:
            self.logger.error(f"Failed to {'start' if start else 'stop'} recording: {e}")
            raise

    def iter_events(self) -> Iterator[dict]:
        """
        Iterates over events from the Braid proxy.

        Yields:
            dict: The parsed event data.
        """
        stream = self.connect_to_event_stream()
        # Retrieve the raw socket from the response object
        raw_sock = stream.raw._fp.fp.raw

        while True:
            # Use select to wait until the socket is ready for reading
            rlist, _, _ = select.select([raw_sock], [], [], 10)  # Timeout of 10 seconds

            if rlist:
                # Read data using iter_content in chunks
                for chunk in stream.iter_content(chunk_size=None, decode_unicode=True):
                    if chunk:
                        try:
                            yield self.parse_chunk(chunk)
                        except (AssertionError, json.JSONDecodeError) as e:
                            self.logger.error(f"Failed to parse chunk: {e}")
                    else:
                        # If no data is returned, yield None to indicate timeout or no data
                        yield None
            else:
                # If select times out, yield None
                yield None

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
        
        buf = lines[1][len(DATA_PREFIX):]
        return json.loads(buf)
