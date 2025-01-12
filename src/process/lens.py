from src.process.base import ProcessManager
from src.process.configs import LensControllerConfig
import signal
import sys


class LensControllerProcess(ProcessManager):
    """Process manager for the lens controller."""

    def __init__(self, config: LensControllerConfig):
        """
        Initialize the lens controller process manager.

        Args:
            config: Configuration for the lens controller
        """
        super().__init__("LensController")
        self.config = config

    def _run_process(self) -> None:
        """Run the lens controller process."""
        signal.signal(signal.SIGINT, signal.SIG_IGN)

        try:
            from src.devices.lens_controller import run_tracking

            run_tracking(
                braid_url=self.config.braid_url,
                lens_port=self.config.lens_port,
                config_file=self.config.config_file,
                interp_file=self.config.interp_file,
                video_folder_path=self.config.video_folder_path,
                mode=self.config.mode,
                debug=self.config.debug,
                lens_update_duration=self.config.lens_update_duration,
            )
        except Exception as e:
            self._logger.error(f"Lens controller failed: {e}")
            sys.exit(1)
