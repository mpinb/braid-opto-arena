import aiohttp
import asyncio
import json
import logging
from typing import AsyncIterable, Optional, Dict, Any
from json.decoder import JSONDecodeError

DATA_PREFIX = "data: "

class BraidDecoder(json.JSONDecoder):
    def decode(self, s):
        try:
            result = super().decode(s)
            return result
        except JSONDecodeError as e:
            logging.warning(f"Failed to parse JSON: {e}. Returning None.")
            return None

class AsyncBraidProxy:
    def __init__(
        self,
        base_url: str,
        event_port: int,
        control_port: int,
        auto_connect: bool = True,
        max_retries: int = 5,
        backoff_factor: float = 1.5,
        timeout: float = 60.0,
        max_chunk_size: int = 1024 * 1024  # 1 MB
    ):
        self.event_url = f"{base_url}:{event_port}/events"
        self.control_url = f"{base_url}:{control_port}/callback"
        self.session: Optional[aiohttp.ClientSession] = None
        self.stream: Optional[aiohttp.ClientResponse] = None
        self.logger = logging.getLogger(__name__)
        self.auto_connect = auto_connect
        self.max_retries = max_retries
        self.backoff_factor = backoff_factor
        self.timeout = timeout
        self.max_chunk_size = max_chunk_size

    async def __aenter__(self):
        if self.auto_connect:
            await self.connect_to_event_stream()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def connect_to_event_stream(self):
        """
        Connects to the Braid proxy server and retrieves the events stream.
        """
        if self.session is None:
            self.session = aiohttp.ClientSession()

        if self.stream is None:  # Connect only if not already connected
            try:
                self.stream = await self.session.get(
                    self.event_url,
                    headers={"Accept": "text/event-stream"},
                    timeout=self.timeout
                )
                await self.stream.content.read(0)  # Ensure the connection is established
            except aiohttp.ClientError as e:
                self.logger.error(f"Failed to connect to event stream: {e}")
                raise

    async def connect_with_retry(self):
        """
        Attempts to connect to the event stream with exponential backoff.
        """
        retries = 0
        while retries < self.max_retries:
            try:
                await self.connect_to_event_stream()
                return
            except aiohttp.ClientError as e:
                wait_time = self.backoff_factor ** retries
                self.logger.warning(f"Connection failed. Retrying in {wait_time:.2f} seconds...")
                await asyncio.sleep(wait_time)
                retries += 1
        raise ConnectionError("Failed to connect after maximum retries")

    async def toggle_recording(self, start: bool) -> None:
        """
        Toggles the recording on or off.

        Args:
            start (bool): True to start recording, False to stop.

        Raises:
            aiohttp.ClientError: If the request fails.
        """
        payload = {"DoRecordCsvTables": start}
        headers = {"Content-Type": "application/json"}

        try:
            async with self.session.post(
                self.control_url,
                data=json.dumps(payload),
                headers=headers,
                timeout=self.timeout
            ) as response:
                await response.raise_for_status()
            self.logger.info(f"{'Started' if start else 'Stopped'} recording successfully")
        except aiohttp.ClientError as e:
            self.logger.error(f"Failed to {'start' if start else 'stop'} recording: {e}")
            raise

    async def iter_events(self) -> AsyncIterable[Optional[Dict[str, Any]]]:
        """
        Asynchronously iterates over events from the Braid proxy.

        Yields:
            Optional[Dict[str, Any]]: The parsed event data, or None if parsing failed.
        """
        while True:
            try:
                if self.stream is None:
                    await self.connect_with_retry()

                async for chunk in self.stream.content.iter_chunked(self.max_chunk_size):
                    chunk = chunk.decode()
                    try:
                        yield self.parse_chunk(chunk)
                    except (AssertionError, json.JSONDecodeError) as e:
                        self.logger.error(f"Failed to parse chunk: {e}")
                        yield None

            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                self.logger.error(f"Stream interrupted: {e}. Reconnecting...")
                self.stream = None  # Reset the stream
                await asyncio.sleep(1)  # Wait a bit before reconnecting

    @staticmethod
    def parse_chunk(chunk: str) -> Optional[Dict[str, Any]]:
        """
        Parses a chunk of data and returns the parsed JSON object.

        Args:
            chunk (str): The chunk of data to be parsed.

        Returns:
            Optional[Dict[str, Any]]: The parsed JSON object, or None if parsing failed.

        Raises:
            AssertionError: If the chunk format is invalid.
        """
        lines = chunk.strip().split("\n")
        assert len(lines) == 2, "Invalid chunk format"
        assert lines[0] == "event: braid", "Invalid event type"
        assert lines[1].startswith(DATA_PREFIX), "Invalid data prefix"

        buf = lines[1][len(DATA_PREFIX):]
        return json.loads(buf, cls=BraidDecoder)

    async def close(self) -> None:
        """
        Closes the aiohttp session and any open connections.
        """
        if self.stream:
            await self.stream.release()
        if self.session:
            await self.session.close()
        self.logger.info("AsyncBraidProxy connections closed")

# Example usage
async def main():
    async with AsyncBraidProxy("http://localhost", 8080, 8081) as proxy:
        async for event in proxy.iter_events():
            if event:
                print(f"Received event: {event}")
            # Process the event as needed
            # Break the loop when done or on some condition

if __name__ == "__main__":
    asyncio.run(main())