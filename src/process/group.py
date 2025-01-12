import logging
from typing import Any

logger = logging.getLogger(name="ProcessGroup")


class ProcessGroup:
    """Manages a group of processes together."""

    def __init__(self):
        self.processes = {}

    def add_process(self, name: str, process: Any) -> None:
        """Add a process to the group."""
        self.processes[name] = process

    def start_all(self) -> None:
        """Start all processes."""
        for name, process in self.processes.items():
            logger.info(f"Starting {name} process...")
            process.start()

    def stop_all(self) -> None:
        """Stop all processes."""
        for name, process in reversed(self.processes.items()):
            logger.info(f"Stopping {name} process...")
            process.stop()

    def check_all_alive(self) -> bool:
        """Check if all processes are alive."""
        return all(process.is_alive() for process in self.processes.values())

    def __enter__(self):
        """Context manager entry."""
        self.start_all()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.stop_all()
