"""
Real-time lens controller for tracking system.
Handles high-frequency updates while maintaining clean shutdown capability.
"""
import logging
import time
from dataclasses import dataclass
from queue import SimpleQueue
from threading import Event, Thread
from typing import Optional

from src.devices.lens_driver import LensDriver
from src.devices.lens_calibration import LensCalibration  # Moved to separate module

# Constants
UPDATE_TIMEOUT = 0.01  # 10ms timeout for update checks
SHUTDOWN_TIMEOUT = 2.0  # Maximum shutdown time

@dataclass
class UpdateMessage:
    """Position update message."""
    obj_id: str
    z: float
    trigger_time: float
    frame: str

class LensController(Thread):
    """
    Thread-safe lens controller handling real-time position updates.
    Optimized for minimal latency while maintaining safe operation.
    """
    def __init__(
        self,
        lens_port: str,
        calibration: LensCalibration,
        update_queue: SimpleQueue,
        mode: str = "current",
        debug: bool = False,
    ):
        super().__init__()
        self.update_queue = update_queue
        self.shutdown_event = Event()
        
        # Initialize lens hardware
        self.lens_driver = LensDriver(port=lens_port, debug=debug)
        self.lens_driver.set_mode(mode)
        
        self.calibration = calibration
        self.debug = debug
        self.logger = self._setup_logger()
        
        # State tracking
        self.current_obj_id: Optional[str] = None
        self._last_update_time: Optional[float] = None

    def _setup_logger(self) -> logging.Logger:
        logger = logging.getLogger("LensController")
        logger.setLevel(logging.DEBUG if self.debug else logging.INFO)
        return logger

    def run(self) -> None:
        """Main processing loop with proper exception handling."""
        self.logger.info("Starting LensController")
        try:
            self._process_updates()
        except Exception as e:
            self.logger.error(f"Error in lens control loop: {e}")
        finally:
            self._cleanup()

    def _process_updates(self) -> None:
        """Process lens updates with timeout-based checking."""
        while not self.shutdown_event.is_set():
            try:
                # Use timeout to regularly check shutdown event
                update = self.update_queue.get(timeout=UPDATE_TIMEOUT)
                self._handle_update(update)
            except Exception:  # Queue.Empty or other errors
                continue

    def _handle_update(self, update: UpdateMessage) -> None:
        """Handle a single position update."""
        try:
            # New tracking session if object ID changes
            if update.obj_id != self.current_obj_id:
                self.current_obj_id = update.obj_id
                self.logger.debug(f"New tracking session: {self.current_obj_id}")

            # Update lens position
            diopter_value = self.calibration.get_dpt(update.z)
            self.lens_driver.set_value(diopter_value)
            
            self._last_update_time = time.perf_counter()
            
            if self.debug:
                self.logger.debug(
                    f"Updated lens for {self.current_obj_id}: "
                    f"z={update.z:.3f}, dpt={diopter_value:.3f}"
                )

        except Exception as e:
            self.logger.error(f"Error handling update: {e}")

    def stop(self) -> None:
        """Signal thread to stop processing."""
        self.shutdown_event.set()

    def _cleanup(self) -> None:
        """Clean up resources with proper timeouts."""
        self.logger.info("Shutting down LensController")
        
        cleanup_start = time.perf_counter()
        try:
            # Give lens driver remaining time for shutdown
            remaining_time = max(0.0, SHUTDOWN_TIMEOUT - (time.perf_counter() - cleanup_start))
            if remaining_time > 0:
                self.lens_driver.safe_shutdown(timeout=remaining_time)
            else:
                self.lens_driver.close()

        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")
            # Ensure driver is closed even if shutdown fails
            try:
                self.lens_driver.close()
            except Exception:
                pass

    def __enter__(self):
        """Context manager support for resource cleanup."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Ensure clean shutdown when used as context manager."""
        self.stop()
        if self.is_alive():
            self.join(timeout=SHUTDOWN_TIMEOUT)