import argparse
import csv
import json
import logging
import os
import sys
import time
from dataclasses import dataclass
from queue import SimpleQueue
from threading import Event, Thread
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yaml
from sklearn.linear_model import LinearRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import PolynomialFeatures

from braid_proxy import BraidProxy
from devices.lens_driver import LensDriver
from messages import Subscriber

# Configure logging with microsecond precision for better debugging
logging.basicConfig(
    level=logging.INFO,
    format="LENSCONTROLLER: %(asctime)s.%(msecs)03d - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Constants
MIN_UPDATE_INTERVAL = 1 / 100  # 100fps maximum update rate
MAX_TRACKING_DURATION = 3.0  # Maximum tracking duration in seconds
EXPECTED_UPDATES_PER_TRACKING = int(
    MAX_TRACKING_DURATION * 100 * 1.5
)  # With 50% safety margin
Z_MIN, Z_MAX = 0.1, 0.3  # Z-value range
LOOKUP_TABLE_SIZE = 1000  # Size of the lens calibration lookup table


@dataclass
class TriggerInfo:
    """Information about a tracking trigger event."""

    obj_id: str
    frame: str
    timestamp: float  # Using perf_counter for precise timing
    receive_time: float


@dataclass
class UpdateMessage:
    """Information about an object position update."""

    obj_id: str
    z: float
    trigger_time: float
    msg_receive_time: float
    frame: str


@dataclass
class DebugEntry:
    """Entry for debug data logging."""

    trigger_recv_time: float
    msg_recv_time: float
    frame: str
    lens_update_time: float
    z: float
    diopter_value: float


def validate_config(config: Dict[str, Any]) -> None:
    """
    Validate the configuration file has all required fields.

    Args:
        config: Dictionary containing configuration settings

    Raises:
        ValueError: If any required fields are missing
    """
    required_fields = {"braid": ["url", "event_port", "control_port"], "zmq": ["port"]}

    for section, fields in required_fields.items():
        if section not in config:
            raise ValueError(f"Missing required config section: {section}")
        for field in fields:
            if field not in config[section]:
                raise ValueError(f"Missing required config field: {section}.{field}")


class ConfigManager:
    """
    Singleton class for managing configuration settings with lazy loading.
    """

    _instance = None
    _config = None

    @classmethod
    def get_config(cls, config_file: str) -> Dict[str, Any]:
        """
        Get configuration settings, loading from file if necessary.

        Args:
            config_file: Path to YAML configuration file

        Returns:
            Dictionary containing configuration settings
        """
        if cls._config is None:
            with open(config_file, "r") as f:
                cls._config = yaml.safe_load(f)
                validate_config(cls._config)
        return cls._config


class LensCalibration:
    """
    Handles lens calibration and provides fast z-to-diopter conversion using a lookup table.

    This class creates a pre-computed lookup table for quick conversion between z-values
    and diopter values, using linear interpolation for values between table entries.

    Attributes:
        z_min: Minimum z-value in the calibration range
        z_max: Maximum z-value in the calibration range
        resolution: Resolution of the lookup table
        lookup_table: Pre-computed diopter values
    """

    def __init__(
        self,
        z_values: np.ndarray,
        dpt_values: np.ndarray,
        method: str = "poly",
        degree: int = 2,
    ):
        """
        Initialize the lens calibration with calibration data.

        Args:
            z_values: Array of z positions from calibration
            dpt_values: Array of corresponding diopter values
            method: Calibration method (currently only 'poly' supported)
            degree: Degree of polynomial fit

        Raises:
            ValueError: If method is not 'poly' or if z_values are outside expected range
        """
        if method != "poly":
            raise ValueError("Only polynomial calibration method is supported")

        # Validate input ranges
        # if np.min(z_values) < Z_MIN or np.max(z_values) > Z_MAX:
        #     raise ValueError(f"Calibration z-values must be between {Z_MIN} and {Z_MAX}")

        # Create and fit the polynomial model
        self.model = make_pipeline(PolynomialFeatures(degree), LinearRegression())
        self.model.fit(z_values.reshape(-1, 1), dpt_values)

        # Initialize lookup table parameters
        self.z_min = Z_MIN
        self.z_max = Z_MAX
        self.resolution = (self.z_max - self.z_min) / LOOKUP_TABLE_SIZE

        # Create lookup table
        z_points = np.linspace(self.z_min, self.z_max, LOOKUP_TABLE_SIZE)
        self.lookup_table = self.model.predict(z_points.reshape(-1, 1))

        # Calculate and log calibration metrics
        self._log_calibration_metrics(z_values, dpt_values)

    def get_dpt(self, z: float) -> float:
        """
        Get interpolated diopter value for a given z position using lookup table.

        Args:
            z: Z position value

        Returns:
            Interpolated diopter value

        Raises:
            ValueError: If z is outside calibrated range
        """
        if not self.z_min <= z <= self.z_max:
            raise ValueError(
                f"Z value {z} outside calibrated range [{self.z_min}, {self.z_max}]"
            )

        # Calculate lookup table index
        idx = int((z - self.z_min) / self.resolution)
        idx = min(LOOKUP_TABLE_SIZE - 2, max(0, idx))

        # Perform linear interpolation
        z_low = self.z_min + idx * self.resolution
        fraction = (z - z_low) / self.resolution
        return (
            self.lookup_table[idx] * (1 - fraction)
            + self.lookup_table[idx + 1] * fraction
        )

    def _log_calibration_metrics(
        self, z_values: np.ndarray, dpt_values: np.ndarray
    ) -> None:
        """
        Calculate and log calibration quality metrics.

        Args:
            z_values: Original z values used for calibration
            dpt_values: Original diopter values used for calibration
        """
        # Calculate predicted values using lookup table
        pred_values = np.array([self.get_dpt(z) for z in z_values])
        residuals = dpt_values - pred_values

        metrics = {
            "rmse": np.sqrt(np.mean(residuals**2)),
            "max_error": np.max(np.abs(residuals)),
            "mean_error": np.mean(np.abs(residuals)),
            "lookup_table_resolution": self.resolution,
        }

        logger.info("Lens calibration metrics:")
        for metric, value in metrics.items():
            logger.info(f"  {metric}: {value:.6f}")


def setup_lens_calibration(interp_file: str) -> LensCalibration:
    """
    Set up the lens calibration model from interpolation file.

    Args:
        interp_file: Path to CSV file containing calibration data

    Returns:
        Configured LensCalibration instance

    Raises:
        Exception: If there's an error reading or processing the calibration file
    """
    try:
        interp_data = pd.read_csv(interp_file)
        z_values = interp_data["z"].values
        dpt_values = interp_data["dpt"].values

        logger.info(f"Loading calibration data from {interp_file}")
        logger.info(f"Calibration points: {len(z_values)}")
        logger.info(f"Z range: [{np.min(z_values):.3f}, {np.max(z_values):.3f}]")

        return LensCalibration(z_values, dpt_values, method="poly", degree=2)

    except Exception as e:
        logger.error(f"Error setting up lens calibration: {e}")
        raise


class TriggerProcessor(Thread):
    """
    Thread responsible for processing trigger events from the tracking system.

    Listens for trigger messages via ZMQ and forwards them to the BraidStreamProcessor.
    Implements rate limiting to prevent processing triggers too frequently.
    """

    def __init__(self, config: Dict, trigger_queue: SimpleQueue, shutdown_event: Event):
        """
        Initialize the TriggerProcessor.

        Args:
            config: Application configuration dictionary
            trigger_queue: Queue for forwarding triggers to BraidStreamProcessor
            shutdown_event: Event to signal thread shutdown
        """
        super().__init__()
        self.config = config
        self.shutdown_event = shutdown_event
        self.trigger_queue = trigger_queue

        # Initialize ZMQ subscriber
        self.subscriber = Subscriber(
            address="127.0.0.1", port=config["zmq"]["port"], topics="trigger"
        )

        # Timing parameters
        self.max_tracking_time = MAX_TRACKING_DURATION
        self.min_update_interval = MIN_UPDATE_INTERVAL
        self.last_trigger_time = 0.0

    def run(self) -> None:
        """Main thread loop for processing triggers."""
        logger.info("Starting TriggerProcessor")

        try:
            self.subscriber.initialize()
            self._process_triggers()

        except Exception as e:
            logger.error(f"Error in TriggerProcessor: {e}")

        finally:
            self._cleanup()

    def _process_triggers(self) -> None:
        """
        Main trigger processing loop.

        Receives trigger messages and forwards them if they meet timing constraints.
        """
        while not self.shutdown_event.is_set():
            try:
                # Rate-limited receive with timeout
                topic, message = self.subscriber.receive(
                    blocking=True, timeout=self.min_update_interval
                )

                if not message or message == "kill":
                    continue

                current_time = time.perf_counter()

                # Rate limiting: ensure minimum time between triggers
                if (current_time - self.last_trigger_time) < self.max_tracking_time:
                    logger.debug("Skipping trigger due to rate limiting")
                    continue

                # Process valid trigger
                self._handle_trigger(message, current_time)

            except TimeoutError:
                continue

            except Exception as e:
                logger.error(f"Error processing trigger: {e}")
                if self.shutdown_event.is_set():
                    break

    def _handle_trigger(self, message: str, receive_time: float) -> None:
        """
        Process a single trigger message.

        Args:
            message: JSON-formatted trigger message
            receive_time: Time when message was received
        """
        try:
            trigger_info = json.loads(message)

            trigger = TriggerInfo(
                obj_id=trigger_info["obj_id"],
                frame=trigger_info.get("frame", "unknown"),
                timestamp=trigger_info.get("timestamp", receive_time),
                receive_time=receive_time,
            )

            self.trigger_queue.put(trigger)
            self.last_trigger_time = receive_time

            logger.info(
                f"Processed trigger for object {trigger.obj_id}, "
                f"frame {trigger.frame}, "
                f"timestamp {trigger.timestamp:.6f}"
            )

        except json.JSONDecodeError as e:
            logger.error(f"Invalid trigger message format: {e}")

        except KeyError as e:
            logger.error(f"Missing required field in trigger message: {e}")

    def _cleanup(self) -> None:
        """Clean up resources when thread is shutting down."""
        logger.info("Shutting down TriggerProcessor")
        try:
            self.subscriber.close()
        except Exception as e:
            logger.error(f"Error closing subscriber: {e}")


class TriggerRateLimiter:
    """
    Utility class for managing trigger rate limiting.
    Could be used to implement more sophisticated rate limiting if needed.
    """

    def __init__(self, max_tracking_time: float = MAX_TRACKING_DURATION):
        self.max_tracking_time = max_tracking_time
        self.last_trigger_time = 0.0

    def should_process_trigger(self, current_time: float) -> bool:
        """
        Determine if a new trigger should be processed based on timing.

        Args:
            current_time: Current time in seconds

        Returns:
            bool: True if trigger should be processed, False otherwise
        """
        if (current_time - self.last_trigger_time) < self.max_tracking_time:
            return False

        self.last_trigger_time = current_time
        return True


class BraidStreamProcessor(Thread):
    """
    Thread responsible for processing object position updates from the Braid system.

    Receives position updates from BraidProxy and forwards relevant updates to the
    LensController. Implements efficient filtering to minimize processing overhead.
    """

    def __init__(
        self,
        config: Dict,
        trigger_queue: SimpleQueue,
        update_queue: SimpleQueue,
        shutdown_event: Event,
    ):
        """
        Initialize the BraidStreamProcessor.

        Args:
            config: Application configuration dictionary
            trigger_queue: Queue for receiving triggers from TriggerProcessor
            update_queue: Queue for sending updates to LensController
            shutdown_event: Event to signal thread shutdown
        """
        super().__init__()
        self.config = config
        self.trigger_queue = trigger_queue
        self.update_queue = update_queue
        self.shutdown_event = shutdown_event

        # Initialize state
        self.current_trigger: Optional[TriggerInfo] = None
        self.braid_proxy = None
        self.tracking_start_time = None

        # Pre-calculate tracking end time offset
        self.tracking_duration = MAX_TRACKING_DURATION

    def connect_braid(self) -> bool:
        """
        Initialize or reconnect to BraidProxy.

        Returns:
            bool: True if connection successful, False otherwise
        """
        logger.info("Connecting to BraidProxy...")
        try:
            if self.braid_proxy:
                self.braid_proxy.close()

            self.braid_proxy = BraidProxy(
                base_url=self.config["braid"]["url"],
                event_port=self.config["braid"]["event_port"],
                control_port=self.config["braid"]["control_port"],
                auto_connect=True,
            )
            logger.info("Successfully connected to BraidProxy")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to BraidProxy: {e}")
            return False

    def run(self) -> None:
        """Main thread loop for processing Braid events."""
        logger.info("Starting BraidStreamProcessor...")

        while not self.shutdown_event.is_set():
            try:
                if not self.connect_braid():
                    logger.error(
                        "Failed to connect to BraidProxy, retrying in 5 seconds..."
                    )
                    time.sleep(5)
                    continue

                self._process_events()

            except Exception as e:
                if not self.shutdown_event.is_set():
                    logger.error(f"Error in event processing loop: {e}")
                    logger.error("Will attempt to reconnect...")
                    time.sleep(1)

        self._cleanup()

    def _process_events(self) -> None:
        """Process events from BraidProxy with efficient filtering."""
        logger.info("Starting event processing loop")

        for event in self.braid_proxy.iter_events():
            if self.shutdown_event.is_set():
                logger.info("Shutdown event detected, breaking event loop")
                break

            # Check for new triggers (non-blocking)
            self._check_new_triggers()

            # Skip processing if no active trigger
            if not self._should_process_events():
                continue

            # Process valid update event
            self._process_update_event(event)

    def _check_new_triggers(self) -> None:
        """Check for and process new triggers from the trigger queue."""
        try:
            while not self.trigger_queue.empty():
                self.current_trigger = self.trigger_queue.get_nowait()
                self.tracking_start_time = time.perf_counter()
                logger.info(
                    f"New trigger received for object {self.current_trigger.obj_id}"
                )
        except Exception:  # SimpleQueue.Empty cannot be caught directly
            pass

    def _should_process_events(self) -> bool:
        """
        Determine if events should be processed based on tracking state.

        Returns:
            bool: True if events should be processed, False otherwise
        """
        if not self.current_trigger:
            return False

        # Check if tracking duration exceeded
        if (
            self.tracking_start_time
            and (time.perf_counter() - self.tracking_start_time)
            >= self.tracking_duration
        ):
            self.current_trigger = None
            self.tracking_start_time = None
            return False

        return True

    def _process_update_event(self, event: Dict) -> None:
        """
        Process a single update event from BraidProxy.

        Args:
            event: Event dictionary from BraidProxy
        """
        # Early rejection for non-Update events
        if not (msg := event.get("msg", {}).get("Update")):
            return

        try:
            # Check if update is for current object
            if msg["obj_id"] != self.current_trigger.obj_id:
                return

            # Create and queue update message
            update = UpdateMessage(
                obj_id=self.current_trigger.obj_id,
                z=msg["z"],
                trigger_time=self.current_trigger.receive_time,
                msg_receive_time=time.perf_counter(),
                frame=self.current_trigger.frame,
            )

            self.update_queue.put(update)
            logger.debug(f"Processed update for object {update.obj_id}: z={update.z}")

        except KeyError as e:
            logger.error(f"Missing field in Update event: {e}, event={event}")

    def _cleanup(self) -> None:
        """Clean up resources when thread is shutting down."""
        logger.info("BraidStreamProcessor shutting down...")
        if self.braid_proxy:
            try:
                self.braid_proxy.close()
            except Exception as e:
                logger.error(f"Error during BraidProxy shutdown: {e}")


class LensController(Thread):
    """
    Thread responsible for controlling the liquid lens based on position updates.

    Handles lens position updates and maintains debug logging of lens operations.
    Optimized for minimal latency between receiving updates and adjusting the lens.
    """

    def __init__(
        self,
        lens_port: str,
        calibration: LensCalibration,
        update_queue: SimpleQueue,
        mode: str,
        debug: bool,
        video_folder_path: str,
        shutdown_event: Event,
        tracking_duration: float = MAX_TRACKING_DURATION,
    ):
        """
        Initialize the LensController.

        Args:
            lens_port: Serial port for lens communication
            calibration: LensCalibration instance for z-to-diopter conversion
            update_queue: Queue for receiving position updates
            mode: Operating mode ('current' or 'diopter')
            debug: Enable debug logging
            video_folder_path: Path for saving debug data
            shutdown_event: Event to signal thread shutdown
            tracking_duration: Maximum duration to track an object
        """
        super().__init__()
        self.update_queue = update_queue
        self.shutdown_event = shutdown_event
        self.lens_driver = LensDriver(port=lens_port, debug=debug)
        self.calibration = calibration
        self.mode = mode
        self.video_folder_path = video_folder_path
        self.tracking_duration = tracking_duration
        self.debug = debug

        # Tracking state
        self.current_obj_id: Optional[str] = None
        self.tracking_start_time: Optional[float] = None

        # Debug data handling
        self.debug_data: List[DebugEntry] = []
        self.current_csv_writer = None
        self.current_csv_file = None

        # Pre-allocate debug data buffer
        if debug:
            self.max_debug_entries = EXPECTED_UPDATES_PER_TRACKING

    def run(self) -> None:
        """Main thread loop for processing lens updates."""
        logger.info("Starting LensController")
        try:
            self.lens_driver.set_mode(self.mode)
            self._process_updates()
        finally:
            self._cleanup()

    def _process_updates(self) -> None:
        """Process lens position updates from the update queue."""
        while not self.shutdown_event.is_set():
            try:
                # Check if current tracking session should end
                self._check_tracking_timeout()

                # Wait for next update (non-blocking)
                try:
                    update = self.update_queue.get_nowait()
                except Exception:  # SimpleQueue.Empty cannot be caught directly
                    continue

                if self.shutdown_event.is_set():
                    break

                # Handle new tracking session or update
                self._handle_update(update)

            except Exception as e:
                logger.error(f"Error in lens control: {e}")
                if self.shutdown_event.is_set():
                    break

    def _check_tracking_timeout(self) -> None:
        """Check if current tracking session should end due to timeout."""
        if not self.is_tracking():
            return

        current_time = time.perf_counter()
        if self.should_stop_tracking(current_time):
            logger.info(f"Tracking session timeout for object {self.current_obj_id}")
            self.stop_tracking()

    def _handle_update(self, update: UpdateMessage) -> None:
        """
        Handle a single lens position update.

        Args:
            update: Update message containing new position information
        """
        # Start new tracking session if needed
        if not self.is_tracking() or self.current_obj_id != update.obj_id:
            self.start_new_tracking_session(update)

        # Process update if still within tracking window
        if self.is_tracking():
            self._update_lens_position(update)

    def _update_lens_position(self, update: UpdateMessage) -> None:
        """
        Update lens position and log debug data if enabled.

        Args:
            update: Update message containing new position information
        """
        start_time = time.perf_counter()
        value = self.update_lens(update.z)

        if self.debug:
            self.debug_data.append(
                DebugEntry(
                    trigger_recv_time=update.trigger_time,
                    msg_recv_time=update.msg_receive_time,
                    frame=update.frame,
                    lens_update_time=start_time,
                    z=update.z,
                    diopter_value=value,
                )
            )

    def is_tracking(self) -> bool:
        """Check if currently tracking an object."""
        return self.current_obj_id is not None and self.tracking_start_time is not None

    def should_stop_tracking(self, current_time: float) -> bool:
        """
        Check if tracking should stop based on elapsed time.

        Args:
            current_time: Current time for comparison

        Returns:
            bool: True if tracking should stop, False otherwise
        """
        if not self.is_tracking():
            return False

        elapsed_time = current_time - self.tracking_start_time
        return elapsed_time >= self.tracking_duration

    def start_new_tracking_session(self, update: UpdateMessage) -> None:
        """
        Start tracking a new object.

        Args:
            update: Update message containing new object information
        """
        logger.info(f"Starting new tracking session for object {update.obj_id}")

        # Stop current tracking if active
        if self.is_tracking():
            self.stop_tracking()

        # Initialize new tracking session
        self.current_obj_id = update.obj_id
        self.tracking_start_time = time.perf_counter()

        if self.debug:
            self._setup_debug_logging(update)

    def stop_tracking(self) -> None:
        """Stop tracking current object and save debug data if enabled."""
        if not self.is_tracking():
            return

        if self.debug and self.debug_data:
            self._save_debug_data()

        self.current_obj_id = None
        self.tracking_start_time = None
        self.debug_data = []

    def update_lens(self, z: float) -> float:
        """
        Update lens position based on z value.

        Args:
            z: Z position value

        Returns:
            float: Set diopter/current value
        """
        value = self.calibration.get_dpt(z)

        if self.mode == "current":
            self.lens_driver.set_current(value)
        else:
            self.lens_driver.set_diopter(value)

        return value

    def _setup_debug_logging(self, update: UpdateMessage) -> None:
        """
        Set up debug logging for new tracking session.

        Args:
            update: Update message containing object information
        """
        if self.current_csv_file:
            self.current_csv_file.close()

        debug_filename = (
            f"lens_controller_obj_id_{update.obj_id}_frame_{update.frame}.csv"
        )
        csv_path = os.path.join(self.video_folder_path, debug_filename)

        self.current_csv_file = open(csv_path, "w", newline="")
        self.current_csv_writer = csv.writer(self.current_csv_file)

        # Write header
        self.current_csv_writer.writerow(
            [
                "trigger_recv_time",
                "msg_recv_time",
                "frame_timestamp",
                "lens_update_time",
                "z",
                "diopter_value",
            ]
        )

        logger.info(f"Created debug log file: {csv_path}")

    def _save_debug_data(self) -> None:
        """Save accumulated debug data to CSV file."""
        if not self.current_csv_writer or not self.debug_data:
            return

        # Write all debug entries at once
        self.current_csv_writer.writerows(
            [
                [
                    entry.trigger_recv_time,
                    entry.msg_recv_time,
                    entry.frame,
                    entry.lens_update_time,
                    entry.z,
                    entry.diopter_value,
                ]
                for entry in self.debug_data
            ]
        )

        self.current_csv_file.flush()

    def _cleanup(self) -> None:
        """Clean up resources when thread is shutting down."""
        logger.info("Shutting down LensController")
        try:
            if self.is_tracking():
                self.stop_tracking()

            if self.lens_driver:
                self.lens_driver.close()

        except Exception as e:
            logger.error(f"Error during LensController cleanup: {e}")


def run_tracking(
    braid_url: str,
    lens_port: str,
    config_file: str,
    interp_file: str,
    video_folder_path: Optional[str] = None,
    mode: str = "current",
    debug: bool = False,
    lens_update_duration: float = MAX_TRACKING_DURATION,
) -> None:
    """
    Main function to run the lens tracking system.

    Args:
        braid_url: URL for the braid server
        lens_port: Serial port for lens communication
        config_file: Path to configuration YAML file
        interp_file: Path to lens calibration CSV file
        video_folder_path: Path for saving debug data (optional)
        mode: Operating mode ('current' or 'diopter')
        debug: Enable debug logging
        lens_update_duration: Maximum duration to track an object
    """
    try:
        # Load configuration
        logger.info("Initializing tracking system...")
        config = ConfigManager.get_config(config_file)

        # Validate debug path if debug mode is enabled
        if debug and not video_folder_path:
            raise ValueError(
                "video_folder_path must be provided when debug mode is enabled"
            )

        # Setup lens calibration
        calibration = setup_lens_calibration(interp_file)

        # Create communication queues and shutdown event
        trigger_queue = SimpleQueue()
        update_queue = SimpleQueue()
        shutdown_event = Event()

        # Initialize thread objects
        threads = _initialize_threads(
            config=config,
            lens_port=lens_port,
            calibration=calibration,
            trigger_queue=trigger_queue,
            update_queue=update_queue,
            shutdown_event=shutdown_event,
            mode=mode,
            debug=debug,
            video_folder_path=video_folder_path,
            lens_update_duration=lens_update_duration,
        )

        # Start tracking system
        _run_tracking_system(threads, shutdown_event)

    except Exception as e:
        logger.error(f"Error in tracking system: {e}")
        raise


def _initialize_threads(
    config: Dict,
    lens_port: str,
    calibration: LensCalibration,
    trigger_queue: SimpleQueue,
    update_queue: SimpleQueue,
    shutdown_event: Event,
    mode: str,
    debug: bool,
    video_folder_path: Optional[str],
    lens_update_duration: float,
) -> List[Thread]:
    """
    Initialize all system threads.

    Returns:
        List of initialized thread objects
    """
    trigger_processor = TriggerProcessor(
        config=config, trigger_queue=trigger_queue, shutdown_event=shutdown_event
    )

    braid_processor = BraidStreamProcessor(
        config=config,
        trigger_queue=trigger_queue,
        update_queue=update_queue,
        shutdown_event=shutdown_event,
    )

    lens_controller = LensController(
        lens_port=lens_port,
        calibration=calibration,
        update_queue=update_queue,
        mode=mode,
        debug=debug,
        video_folder_path=video_folder_path,
        shutdown_event=shutdown_event,
        tracking_duration=lens_update_duration,
    )

    return [trigger_processor, braid_processor, lens_controller]


def _run_tracking_system(threads: List[Thread], shutdown_event: Event) -> None:
    """
    Run the tracking system and handle shutdown.

    Args:
        threads: List of system threads
        shutdown_event: Event to signal system shutdown
    """
    logger.info("Starting tracking system...")

    # Start all threads
    for thread in threads:
        thread.start()
        logger.info(f"Started {thread.__class__.__name__}")

    try:
        # Wait for keyboard interrupt
        while True:
            time.sleep(0.1)

    except KeyboardInterrupt:
        logger.info("Shutdown signal received")
        shutdown_event.set()

        # Give threads time to cleanup
        time.sleep(0.5)

        # Wait for all threads to complete
        for thread in threads:
            thread.join(timeout=2.0)
            if thread.is_alive():
                logger.warning(f"{thread.__class__.__name__} did not shut down cleanly")

    finally:
        logger.info("Tracking system stopped")


def main() -> None:
    """Command-line interface for the tracking system."""
    parser = argparse.ArgumentParser(
        description="3D Object Tracking and Lens Control System",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--braid_url", default="http://127.0.0.1:8397/", help="URL for the braid server"
    )

    parser.add_argument(
        "--lens_port", default="/dev/optotune_ld", help="Port for the lens controller"
    )

    parser.add_argument(
        "--config-file",
        default="/home/buchsbaum/src/braid-opto-arena/config.yaml",
        help="YAML file defining the tracking zone",
    )

    parser.add_argument(
        "--interp-file",
        default="/home/buchsbaum/liquid_lens_calibration_20241112.csv",
        help="CSV file mapping Z values to diopter values",
    )

    parser.add_argument(
        "--mode",
        choices=["current", "diopter"],
        default="current",
        help="Mode for the lens controller",
    )

    parser.add_argument(
        "--video_folder_path",
        help="Path to save debug data (required if debug mode is enabled)",
    )

    parser.add_argument(
        "--debug", action="store_true", help="Enable debug logging and data collection"
    )

    parser.add_argument(
        "--lens-update-duration",
        type=float,
        default=MAX_TRACKING_DURATION,
        help="Maximum duration to track an object (seconds)",
    )

    args = parser.parse_args()

    try:
        run_tracking(
            braid_url=args.braid_url,
            lens_port=args.lens_port,
            config_file=args.config_file,
            interp_file=args.interp_file,
            video_folder_path=args.video_folder_path,
            mode=args.mode,
            debug=args.debug,
            lens_update_duration=args.lens_update_duration,
        )
    except Exception as e:
        logger.error(f"Error running tracking system: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
