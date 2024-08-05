import yaml
from typing import Any, Dict, List, Union

class ConfigManager:
    def __init__(self, config_path: str):
        self.config_path = config_path
        with open(config_path, 'r') as config_file:
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
        return self.get('serial', device)

    def get_trigger_params(self) -> Dict[str, Any]:
        return self.get('trigger')

    def get_optogenetic_params(self) -> Dict[str, float]:
        return self.get('optogenetic_light')

    def get_static_stimuli(self) -> List[Dict[str, Any]]:
        return self.get('stimuli', 'static')

    def get_looming_stimulus(self) -> Dict[str, Any]:
        return self.get('stimuli', 'looming')

    def get_camera_params(self) -> Dict[str, Union[str, float]]:
        return self.get('high_speed_camera')

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
        with open(config_path, 'w') as config_file:
            yaml.dump(self.config, config_file, default_flow_style=False)