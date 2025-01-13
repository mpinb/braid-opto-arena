from typing import List, Optional
from src.process.base import ProcessManager
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

    def _cleanup_process(self) -> None:
        """Clean up the subprocess resources."""
        if not self._process:
            return

        try:
            if self._process.poll() is None:  # Process is still running
                print(f"Stopping {self.name} process...")
                self._process.terminate()
                try:
                    self._process.wait(timeout=5.0)
                except subprocess.TimeoutExpired:
                    print(f"Force-killing {self.name} process...")
                    self._process.kill()
                    self._process.wait(timeout=3.0)

        except Exception as e:
            print(f"Error stopping {self.name} process: {e}")
        finally:
            if self._process.stdout:
                self._process.stdout.close()
            self._process = None

    def _run_process(self) -> None:
        """Run the Rust process."""
        try:
            command = self._build_command()
            print(f"Starting {self.name} process: {' '.join(command)}")

            # Start the Rust process
            self._process = subprocess.Popen(
                command,
                cwd=self.config.working_dir,
                env={**os.environ, **(self.config.env or {})},
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,  # Redirect stderr to stdout
                text=True,
                bufsize=0,  # Unbuffered
            )

            # Monitor the process output
            while self._process and self._process.poll() is None and not self.shutdown_event.is_set():
                try:
                    line = self._process.stdout.readline()
                    if line:
                        print(f"{self.name}: {line.strip()}")
                except KeyboardInterrupt:
                    print(f"\nGracefully shutting down {self.name}...")
                    break
                except Exception as e:
                    print(f"Error reading output from {self.name}: {e}")
                    break

            # Only check return code if process wasn't stopped intentionally
            if (self._process and 
                not self.shutdown_event.is_set() and 
                self._process.returncode is not None and  # Add this check
                self._process.returncode != 0):
                raise subprocess.CalledProcessError(self._process.returncode or 1, command)  # Provide default


        except KeyboardInterrupt:
            print(f"\nGracefully shutting down {self.name}...")
            return  # Add explicit return to avoid raising error
        except Exception as e:
            print(f"{self.name} process failed: {str(e)}")  # Use str() to avoid formatting issues
            raise
        finally:
            self._cleanup_process()

    def stop(self) -> None:
        """Stop the Rust process with proper cleanup."""
        # Signal the process to shut down gracefully
        self.shutdown_event.set()
        super().stop()


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