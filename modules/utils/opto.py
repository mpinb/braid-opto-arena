# opto_utils.py
import random
import logging
import serial

from utils.log_config import setup_logging

setup_logging(level="INFO")
logger = logging.getLogger(__name__)


def _get_opto_trigger_params(trigger_params: dict):
    """
    Get the opto trigger parameters based on the given trigger_params dictionary.

    Args:
        trigger_params (dict): A dictionary containing the trigger parameters.

    Returns:
        tuple: A tuple containing the opto trigger parameters. If the random number is less than
        the sham percentage, it returns (0, 0, 0). Otherwise, it returns the stim_duration,
        stim_intensity, and stim_frequency from the trigger_params dictionary.
    """
    if random.random() < trigger_params["sham_perc"]:
        logger.debug("Sham opto.")
        return 0, 0, 0
    else:
        return (
            trigger_params["stim_duration"],
            trigger_params["stim_intensity"],
            trigger_params["stim_frequency"],
        )


def trigger_opto(opto_trigger_board: serial.Serial, trigger_params: dict, pos: dict):
    """
    Triggers the opto stimulus on the opto trigger board.

    Args:
        opto_trigger_board (serial.Serial): The serial connection to the opto trigger board.
        trigger_params (dict): A dictionary containing the trigger parameters.
        pos (dict): A dictionary to store the position information.

    Returns:
        dict: The updated position dictionary with the stimulus duration, intensity, and frequency.

    """

    stim_duration, stim_intensity, stim_frequency = _get_opto_trigger_params(
        trigger_params
    )

    opto_trigger_board.write(
        f"<{stim_duration},{stim_intensity},{stim_frequency}>".encode()
    )
    pos["stim_duration"] = stim_duration
    pos["stim_intensity"] = stim_intensity
    pos["stim_frequency"] = stim_frequency

    logger.debug(
        f"Trigger opto with stim_duration: {stim_duration}, stim_intensity: {stim_intensity}, stim_frequency: {stim_frequency}"
    )
    return pos


def check_position(pos, trigger_params):
    """
    Check if the given position satisfies the trigger conditions.

    Args:
        pos (dict): A dictionary containing the x, y, and z coordinates of the position.
        trigger_params (dict): A dictionary containing the trigger parameters.

    Returns:
        bool: True if the position satisfies the trigger conditions, False otherwise.
    """

    # calculate x position corrected for the center of the arena
    radius = (
        (pos["x"] - trigger_params["center_x"]) ** 2
        + (pos["y"] - trigger_params["center_y"]) ** 2
    ) ** 0.5
    if trigger_params["type"] == "radius":
        in_position = (
            radius < trigger_params["min_radius"]
            and trigger_params["zmin"] <= pos["z"] <= trigger_params["zmax"]
        )
    elif trigger_params["type"] == "zone":
        in_position = (
            trigger_params["zmin"] <= pos["z"] <= trigger_params["zmax"]
            and trigger_params["xmin"] <= pos["x"] <= trigger_params["xmax"]
            and trigger_params["ymin"] <= pos["y"] <= trigger_params["ymax"]
        )

    return in_position
