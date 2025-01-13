"""
Process management for the lens controller.
Handles initialization, monitoring, and graceful shutdown of the lens control system.
"""
import signal
import sys
from typing import Optional
from multiprocessing import Event, Process

from src.process.base import ProcessManager
from src.process.configs import LensControllerConfig
from src.calibration.lens_calibration import load_calibration
from src.devices.lens_controller import LensController
from queue import SimpleQueue


class LensControllerProcess(ProcessManager):
    """Process manager for the lens controller system."""

    def __init__(self, config: LensControllerConfig):
        """
        Initialize the lens controller process manager.

        Args:
            config: Configuration for the lens controller
        """
        super().__init__("LensController")
        self.config = config
        self.controller: Optional[LensController] = None

    def _run_process(self) -> None:
        """Run the lens controller process with proper signal handling."""
        # Ignore SIGINT in subprocess (parent process handles shutdown)
        signal.signal(signal.SIGINT, signal.SIG_IGN)

        try:
            # Initialize communication queue
            update_queue = SimpleQueue()

            # Load calibration
            calibration = load_calibration(
                filepath=self.config.interp_file,
                poly_degree=2  # Can be made configurable if needed
            )

            # Initialize controller
            self.controller = LensController(
                lens_port=self.config.lens_port,
                calibration=calibration,
                update_queue=update_queue,
                mode=self.config.mode,
                debug=self.config.debug
            )

            # Start controller thread
            self.controller.start()

            # Monitor for shutdown event
            while not self.shutdown_event.is_set():
                # Process can be interrupted by shutdown_event
                self.shutdown_event.wait(timeout=0.1)

        except Exception as e:
            self._logger.error(f"Lens controller failed: {e}")
            sys.exit(1)

        finally:
            if self.controller:
                self._logger.info("Shutting down lens controller...")
                self.controller.stop()
                self.controller.join(timeout=2.0)
                if self.controller.is_alive():
                    self._logger.warning("Lens controller thread didn't shut down cleanly")

    def stop(self) -> None:
        """Stop the process with graceful shutdown."""
        if not self.process:
            return

        if self.is_alive():
            self._logger.debug(f"Stopping {self.name} process...")

            # Signal the process to shut down
            self.shutdown_event.set()
            self.process.join(timeout=3.0)  # Shorter initial timeout

            # Force termination if still alive
            if self.process.is_alive():
                self._logger.warning(f"{self.name} process didn't terminate, forcing...")
                self.process.terminate()
                self.process.join(timeout=2.0)

                if self.process.is_alive():
                    self._logger.warning(f"Force-killing {self.name} process...")
                    self.process.kill()
                    self.process.join(timeout=1.0)

        self.process = None
        self._logger.info(f"{self.name} process stopped")