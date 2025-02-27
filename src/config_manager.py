# ./src/config_manager.py
import argparse
import ast
from typing import Any, Dict, List, Union

import yaml


class ConfigManager:
    def __init__(self, config_path: str):
        self.config_path = config_path
        with open(config_path, "r") as config_file:
            self.config = yaml.safe_load(config_file)

    def get(self, *keys: str) -> Any:
        """
        Retrieve a value from the config using dot notation.
        Example: config.get('stimuli', 'static', 0, 'name')
        """
        value = self.config
        for key in keys:
            if isinstance(value, list) and key.isdigit():
                value = value[int(key)]
            elif isinstance(value, dict):
                value = value.get(key)
            else:
                return None
        return value

    def get_serial(self, device: str) -> str:
        return self.get("serial", device)

    def get_trigger_params(self) -> Dict[str, Any]:
        return self.get("trigger")

    def get_optogenetic_params(self) -> Dict[str, float]:
        return self.get("optogenetic_light")

    def get_static_stimuli(self) -> List[Dict[str, Any]]:
        return self.get("stimuli", "static")

    def get_looming_stimulus(self) -> Dict[str, Any]:
        return self.get("stimuli", "looming")

    def get_camera_params(self) -> Dict[str, Union[str, float]]:
        return self.get("high_speed_camera")

    def update_config(self, *keys: str, value: Any) -> None:
        """
        Update a value in the config using dot notation.
        Example: config.update_config('stimuli', 'static', 0, 'name', value='new_background')
        """
        config = self.config
        for key in keys[:-1]:
            if isinstance(config, list) and key.isdigit():
                config = config[int(key)]
            elif isinstance(config, dict):
                config = config.setdefault(key, {})
        if isinstance(config, list) and keys[-1].isdigit():
            config[int(keys[-1])] = value
        elif isinstance(config, dict):
            config[keys[-1]] = value

    def save_config(self, config_path: str) -> None:
        """Save the current configuration to a file."""
        with open(config_path, "w") as config_file:
            yaml.dump(self.config, config_file, default_flow_style=False)


def parse_value(value: str) -> Any:
    """
    Parse string value into appropriate Python type.
    Handles integers, floats, booleans, None, lists, and strings.
    """
    try:
        # Try to evaluate as literal (handles lists, numbers, booleans, None)
        return ast.literal_eval(value)
    except (ValueError, SyntaxError):
        # If not a literal, return as string
        return value


def update_nested_dict(d: Dict, key_path: str, value: Any) -> None:
    """
    Update a nested dictionary using a dot-separated key path.
    Example: update_nested_dict(config, "hardware.arduino.port", "/dev/ttyUSB0")
    """
    keys = key_path.split(".")
    current = d
    for key in keys[:-1]:
        if key not in current:
            current[key] = {}
        current = current[key]
    current[keys[-1]] = value


def setup_config_with_cli_overrides(default_config_path: str) -> Dict:
    """
    Load configuration from YAML file and allow CLI overrides for any value.

    Usage example:
    python script.py --config config.yaml --set hardware.arduino.port=/dev/ttyUSB0
                    --set experiment.time_limit=48
                    --set trigger.radius.distance=0.03

    Returns:
        Dict: Final configuration with CLI overrides applied
    """
    # Create parser
    parser = argparse.ArgumentParser(description="Run experiment with config overrides")
    parser.add_argument(
        "--config", default=default_config_path, help="Path to the configuration file"
    )
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        help="Override config values. Format: key.subkey=value",
    )
    parser.add_argument(
        "--debug", action="store_true", help="Run without active Braid tracking"
    )

    args = parser.parse_args()

    # Load base configuration
    with open(args.config, "r") as f:
        config = yaml.safe_load(f)

    # Process overrides
    for override in args.set:
        try:
            key_path, value_str = override.split("=", 1)
            value = parse_value(value_str)
            update_nested_dict(config, key_path, value)
        except ValueError as e:
            parser.error(f"Invalid override format '{override}'. Use key.subkey=value")

    return config, args.debug


# Example usage in main.py:
if __name__ == "__main__":
    # This is just for demonstration
    config, debug_mode = setup_config_with_cli_overrides("config.yaml")
    print(f"Loaded config with overrides: {config}")
    print(f"Debug mode: {debug_mode}")
