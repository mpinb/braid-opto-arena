from typing import List, Optional
from base import ProcessManager
import subprocess
import os
from src.process.configs import RustProcessConfig


class RustProcessManager(ProcessManager):
    """
    Process manager specifically designed for Rust executables.
    Handles process lifecycle, logging, and cleanup.
    """

    def __init__(self, name: str, config: RustProcessConfig):
        """
        Initialize the Rust process manager.

        Args:
            name: Identifier for this process
            config: Configuration for the Rust process
        """
        super().__init__(name)
        self.config = config
        self._process: Optional[subprocess.Popen] = None

    def _build_command(self) -> List[str]:
        """Build the command list for subprocess execution."""
        if not os.path.isfile(self.config.executable_path):
            raise FileNotFoundError(
                f"Rust executable not found at: {self.config.executable_path}"
            )

        return [self.config.executable_path] + self.config.args

    def _run_process(self) -> None:
        """Run the Rust process."""
        try:
            command = self._build_command()
            self._logger.info(f"Starting Rust process: {' '.join(command)}")

            # Start the Rust process
            self._process = subprocess.Popen(
                command,
                cwd=self.config.working_dir,
                env={**os.environ, **(self.config.env or {})},
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,  # Line buffered
            )

            # Monitor the process output
            while self._process.poll() is None and not self.shutdown_event.is_set():
                # Read output and error streams
                stdout_line = (
                    self._process.stdout.readline() if self._process.stdout else ""
                )
                stderr_line = (
                    self._process.stderr.readline() if self._process.stderr else ""
                )

                if stdout_line:
                    self._logger.info(f"{self.name} output: {stdout_line.strip()}")
                if stderr_line:
                    self._logger.error(f"{self.name} error: {stderr_line.strip()}")

            # Process terminated
            if self._process.returncode != 0 and not self.shutdown_event.is_set():
                raise subprocess.CalledProcessError(self._process.returncode, command)

        except Exception as e:
            self._logger.error(f"Rust process failed: {e}")
            raise
        finally:
            if self._process:
                self._process.stdout.close()
                self._process.stderr.close()

    def stop(self) -> None:
        """Stop the Rust process with proper cleanup."""
        if not self._process:
            return

        if self._process.poll() is None:  # Process is still running
            self._logger.info(f"Stopping {self.name} process...")

            # Signal the process to shut down gracefully
            self.shutdown_event.set()

            try:
                # Send SIGTERM
                self._process.terminate()
                try:
                    self._process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    self._logger.warning(f"Force-killing {self.name} process...")
                    self._process.kill()
                    self._process.wait(timeout=3.0)
            except Exception as e:
                self._logger.error(f"Error stopping process: {e}")
            finally:
                self._process = None
                super().stop()

    def is_alive(self) -> bool:
        """Check if the Rust process is currently running."""
        return bool(self._process and self._process.poll() is None)


class XimeaCameraProcess(RustProcessManager):
    """Specific implementation for the Ximea camera Rust process."""

    def __init__(self, videos_folder: str):
        """
        Initialize the Ximea camera process manager.

        Args:
            videos_folder: Folder where videos will be saved
        """
        # Ensure the videos folder exists
        os.makedirs(videos_folder, exist_ok=True)

        config = RustProcessConfig(
            executable_path="libs/ximea_camera/target/release/ximea_camera",
            args=["--save-folder", videos_folder],
            env={
                "RUST_LOG": "info",  # Enable logging if your Rust app uses env_logger
            },
        )

        super().__init__("XimeaCamera", config)
