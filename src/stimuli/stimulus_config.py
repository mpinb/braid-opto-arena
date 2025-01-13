"""
Stimulus Configuration Module

This module defines the configuration dataclasses for different types of visual stimuli.
Each stimulus type has its own configuration class inheriting from a base StimulusConfig.
"""

from dataclasses import dataclass
from typing import Union, Tuple, Dict, Any, Optional

@dataclass
class StimulusConfig:
    """Base configuration class for all stimulus types."""
    type: str
    enabled: bool = True
    
    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> "StimulusConfig":
        """Create appropriate config instance from dictionary."""
        stimulus_type = config.get("type")
        config_class = STIMULUS_CONFIG_TYPES.get(stimulus_type, cls)
        return config_class(**config)

@dataclass
class StaticImageStimulusConfig(StimulusConfig):
    """Configuration for static image stimuli."""
    image: str = "random"
    def __init__(self, type: str, enabled: bool = True, **kwargs):
        super().__init__(type=type, enabled=enabled)
        self.iamge = kwargs.get("image", "random")

@dataclass
class LoomingStimulusConfig(StimulusConfig):
    """Configuration for looming stimuli."""
    color: Union[str, Tuple[int, int, int]] = "black"
    position_type: str = "random"
    expansion_type: str = "exponential"
    end_radius: Union[int, str] = 64
    duration: Union[int, str] = 150

    def __init__(self, type: str, enabled: bool = True, **kwargs):
        super().__init__(type=type, enabled=enabled)
        self.color = kwargs.get("color", "black")
        self.position_type = kwargs.get("position_type", "random")
        self.expansion_type = kwargs.get("expansion_type", "exponential")
        self.end_radius = kwargs.get("end_radius", 64)
        self.duration = kwargs.get("duration", 150)

@dataclass
class GratingStimulusConfig(StimulusConfig):
    """Configuration for grating stimuli."""
    color: Union[str, Tuple[int, int, int]] = "black"
    frequency: float = 1.0
    direction: float = 0.0

    def __init__(self, type: str, enabled: bool = True, **kwargs):
        super().__init__(type=type, enabled=enabled)
        self.color = kwargs.get("color", "black")
        self.frequency = kwargs.get("frequency", 1.0)
        self.direction = kwargs.get("direction", 0.0)

# Register stimulus types with their config classes
STIMULUS_CONFIG_TYPES = {
    "static": StaticImageStimulusConfig,
    "looming": LoomingStimulusConfig,
    "grating": GratingStimulusConfig
}