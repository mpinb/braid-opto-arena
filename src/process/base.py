"""
Process management utilities for controlling separate processes in the tracking system.
Provides a unified interface for managing different types of processes including
Python multiprocessing and Rust subprocess management.
"""

from abc import ABC, abstractmethod

from multiprocessing import Event, Process
from typing import Optional
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ProcessManager(ABC):
    """
    Abstract base class for process management.
    Provides a standard interface for starting, stopping, and monitoring processes.
    """

    def __init__(self, name: str):
        """
        Initialize the process manager.

        Args:
            name: Name of the process for logging and identification
        """
        self.name = name
        self.process: Optional[Process] = None
        self.shutdown_event = Event()
        self._logger = logging.getLogger(f"{self.name}Manager")

    @abstractmethod
    def _run_process(self) -> None:
        """
        Implementation of the process's main run loop.
        Must be implemented by child classes.
        """
        pass

    def start(self) -> None:
        """
        Start the managed process if it's not already running.

        Raises:
            RuntimeError: If the process is already running
        """
        if self.is_alive():
            self._logger.warning(f"{self.name} process is already running")
            return

        self.shutdown_event.clear()
        self.process = Process(target=self._run_process, name=self.name)
        self.process.start()
        self._logger.info(f"Started {self.name} process (PID: {self.process.pid})")

    def stop(self) -> None:
        """Stop the managed process with graceful shutdown."""
        if not self.process:
            return

        if self.is_alive():
            self._logger.info(f"Stopping {self.name} process...")

            # Signal the process to shut down gracefully
            self.shutdown_event.set()
            self.process.join(timeout=5.0)

            # Force termination if still alive
            if self.process.is_alive():
                self._logger.warning(
                    f"{self.name} process didn't terminate, forcing..."
                )
                self.process.terminate()
                self.process.join(timeout=3.0)

                if self.process.is_alive():
                    self._logger.warning(f"Force-killing {self.name} process...")
                    self.process.kill()
                    self.process.join()

        self.process = None
        self._logger.info(f"{self.name} process stopped")

    def is_alive(self) -> bool:
        """Check if the managed process is currently running."""
        return bool(self.process and self.process.is_alive())

    def __enter__(self):
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop()
