# ./src/braid_proxy.py

import requests
import json

DATA_PREFIX = "data: "


def connect_to_braid_proxy(braid_url: str):
    """
    Connects to a Braid proxy server and retrieves the events stream.

    Args:
        braid_url (str): The URL of the Braid proxy server.

    Returns:
        requests.Response: The response object containing the events stream.

    Raises:
        AssertionError: If the status code of the initial request is not OK.
    """
    # connect and check
    session = requests.session()
    r = session.get(braid_url)
    assert r.status_code == requests.codes.ok

    # start braid proxy
    events_url = braid_url + "events"
    r = session.get(
        events_url,
        stream=True,
        headers={"Accept": "text/event-stream"},
    )

    return r


def parse_chunk(chunk):
    """
    Parses a chunk of data and returns the parsed JSON object.

    Args:
        chunk (str): The chunk of data to be parsed.

    Returns:
        dict: The parsed JSON object.

    Raises:
        AssertionError: If the number of lines in the chunk is not equal to 2.
        AssertionError: If the first line of the chunk is not equal to "event: braid".
        AssertionError: If the second line of the chunk does not start with the DATA_PREFIX.

    """
    lines = chunk.strip().split("\n")
    assert len(lines) == 2
    assert lines[0] == "event: braid"
    assert lines[1].startswith(DATA_PREFIX)
    buf = lines[1][len(DATA_PREFIX) :]
    data = json.loads(buf)
    return data

def toggle_recording(start: bool, braid_url: str):
    url = f"{braid_url}/callback"
    payload = {
        "DoRecordCsvTables": start
    }
    headers = {
        "Content-Type": "application/json"
    }
    
    response = requests.post(url, data=json.dumps(payload), headers=headers)
    
    if response.status_code == 200:
        print(f"{'Started' if start else 'Stopped'} recording successfully")
    else:
        print(f"Failed to {'start' if start else 'stop'} recording. Status code: {response.status_code}")
