from base import ProcessManager
from configs import DisplayControllerConfig
import signal
import sys


class DisplayProcess(ProcessManager):
    """Process manager for the display controller."""

    def __init__(self, config: DisplayControllerConfig):
        """
        Initialize the display process manager.

        Args:
            config: Configuration for the display controller
        """
        super().__init__("DisplayController")
        self.config = config

    def _run_process(self) -> None:
        """Run the display controller process."""
        signal.signal(signal.SIGINT, signal.SIG_IGN)

        try:
            from stimuli.visual_controller import DisplayController

            controller = DisplayController(
                config_path=self.config.config_path,
                braid_folder=self.config.braid_folder,
                standalone=self.config.standalone,
            )
            controller.run()
        except Exception as e:
            self._logger.error(f"Display controller failed: {e}")
            sys.exit(1)
