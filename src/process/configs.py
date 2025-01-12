from dataclasses import dataclass
from typing import Optional, List


@dataclass
class LensControllerConfig:
    """Configuration for the lens controller process."""

    braid_url: str
    lens_port: str
    config_file: str
    interp_file: str
    video_folder_path: Optional[str] = None
    mode: str = "current"
    debug: bool = False
    lens_update_duration: float = 300.0  # MAX_TRACKING_DURATION


@dataclass
class DisplayControllerConfig:
    """Configuration for the display controller process."""

    config_path: str
    braid_folder: str = ""
    standalone: bool = False

@dataclass
class RustProcessConfig:
    """Configuration for Rust process execution."""

    executable_path: str
    args: List[str]
    working_dir: Optional[str] = None
    env: Optional[dict] = None
