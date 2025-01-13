"""
Lens calibration module for efficient z-to-diopter conversion.
Uses polynomial fitting and lookup tables for real-time performance.
"""
import logging
from typing import Tuple, Optional
import numpy as np
from sklearn.linear_model import LinearRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import PolynomialFeatures

# Constants for calibration
Z_MIN, Z_MAX = 0.0, 0.35  # Z-value range in meters
LOOKUP_TABLE_SIZE = 1000   # Size of lookup table for fast conversion
DEFAULT_POLY_DEGREE = 2    # Default polynomial degree for fitting

class LensCalibration:
    """
    Handles lens calibration and provides fast z-to-diopter conversion.
    Uses a pre-computed lookup table for efficient real-time operation.
    """
    def __init__(
        self,
        z_values: np.ndarray,
        dpt_values: np.ndarray,
        z_range: Optional[Tuple[float, float]] = None,
        poly_degree: int = DEFAULT_POLY_DEGREE,
    ):
        """
        Initialize calibration with measurement data.

        Args:
            z_values: Array of z positions from calibration
            dpt_values: Array of corresponding diopter values
            z_range: Optional override for z-value range (min, max)
            poly_degree: Degree of polynomial fit
        """
        self.logger = logging.getLogger("LensCalibration")
        
        # Set z-value range
        self.z_min = Z_MIN if z_range is None else z_range[0]
        self.z_max = Z_MAX if z_range is None else z_range[1]
        
        # Validate input data
        self._validate_input_data(z_values, dpt_values)
        
        # Create and fit polynomial model
        self.model = self._create_model(z_values, dpt_values, poly_degree)
        
        # Create lookup table for fast conversion
        self.resolution = (self.z_max - self.z_min) / LOOKUP_TABLE_SIZE
        self.lookup_table = self._create_lookup_table()
        
        # Calculate and log calibration metrics
        self._log_calibration_metrics(z_values, dpt_values)

    def _validate_input_data(self, z_values: np.ndarray, dpt_values: np.ndarray) -> None:
        """Validate calibration input data."""
        if len(z_values) != len(dpt_values):
            raise ValueError("z_values and dpt_values must have the same length")
        
        if len(z_values) < 3:
            raise ValueError("At least 3 calibration points are required")
        
        # Warning if input data is outside range
        z_min, z_max = np.min(z_values), np.max(z_values)
        if z_min < self.z_min or z_max > self.z_max:
            self.logger.warning(
                f"Calibration data range ({z_min:.3f}, {z_max:.3f}) "
                f"outside expected range ({self.z_min:.3f}, {self.z_max:.3f})"
            )

    def _create_model(
        self, 
        z_values: np.ndarray, 
        dpt_values: np.ndarray, 
        degree: int
    ) -> make_pipeline:
        """Create and fit polynomial model."""
        model = make_pipeline(
            PolynomialFeatures(degree=degree),
            LinearRegression()
        )
        model.fit(z_values.reshape(-1, 1), dpt_values)
        return model

    def _create_lookup_table(self) -> np.ndarray:
        """Create lookup table for fast conversion."""
        z_points = np.linspace(self.z_min, self.z_max, LOOKUP_TABLE_SIZE)
        return self.model.predict(z_points.reshape(-1, 1))

    def get_dpt(self, z: float) -> float:
        """
        Get interpolated diopter value for a given z position.
        Uses fast lookup table with linear interpolation.

        Args:
            z: Z position value in meters

        Returns:
            Interpolated diopter value

        Raises:
            ValueError: If z is outside calibrated range
        """
        if not self.z_min <= z <= self.z_max:
            raise ValueError(
                f"Z value {z:.3f} outside calibrated range "
                f"[{self.z_min:.3f}, {self.z_max:.3f}]"
            )

        # Calculate lookup table index
        idx = int((z - self.z_min) / self.resolution)
        idx = min(LOOKUP_TABLE_SIZE - 2, max(0, idx))

        # Linear interpolation between table entries
        z_low = self.z_min + idx * self.resolution
        fraction = (z - z_low) / self.resolution
        
        return (
            self.lookup_table[idx] * (1 - fraction) +
            self.lookup_table[idx + 1] * fraction
        )

    def _log_calibration_metrics(
        self, 
        z_values: np.ndarray, 
        dpt_values: np.ndarray
    ) -> None:
        """Calculate and log calibration quality metrics."""
        # Get predicted values using lookup table
        pred_values = np.array([self.get_dpt(z) for z in z_values])
        residuals = dpt_values - pred_values

        metrics = {
            "rmse": np.sqrt(np.mean(residuals**2)),
            "max_error": np.max(np.abs(residuals)),
            "mean_error": np.mean(np.abs(residuals)),
            "points": len(z_values),
            "z_range": f"[{np.min(z_values):.3f}, {np.max(z_values):.3f}]",
            "dpt_range": f"[{np.min(dpt_values):.3f}, {np.max(dpt_values):.3f}]",
        }

        self.logger.info("Lens calibration metrics:")
        for metric, value in metrics.items():
            self.logger.info(f"  {metric}: {value}")

def load_calibration(
    filepath: str,
    z_range: Optional[Tuple[float, float]] = None,
    poly_degree: int = DEFAULT_POLY_DEGREE,
) -> LensCalibration:
    """
    Load calibration data from CSV file.

    Args:
        filepath: Path to CSV file with 'z' and 'dpt' columns
        z_range: Optional override for z-value range
        poly_degree: Degree of polynomial fit

    Returns:
        Configured LensCalibration instance
    """
    try:
        data = np.loadtxt(filepath, delimiter=",", skiprows=1)
        z_values = data[:, 0]  # First column: z values
        dpt_values = data[:, 1]  # Second column: diopter values
        
        return LensCalibration(
            z_values=z_values,
            dpt_values=dpt_values,
            z_range=z_range,
            poly_degree=poly_degree
        )
    
    except Exception as e:
        raise ValueError(f"Error loading calibration data: {e}")