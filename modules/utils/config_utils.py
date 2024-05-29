# config_utils.py
import tomllib


def read_parameters_file(params_file: str) -> dict:
    """
    Read parameters from a file.

    Args:
        params_file (str): The path to the parameters file.

    Returns:
        dict: A dictionary containing the parameters read from the file.
    """
    with open(params_file, "rb") as f:
        params = tomllib.load(f)
    return params
