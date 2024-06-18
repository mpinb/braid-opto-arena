import logging
import colorlog


def setup_logging(logger_name, level="INFO", color="white"):
    numeric_level = getattr(logging, level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f"Invalid log level: {level}")

    # Create a logger with the specified name
    logger = logging.getLogger(logger_name)
    logger.setLevel(numeric_level)

    # Remove any existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Create a console handler
    ch = logging.StreamHandler()
    ch.setLevel(numeric_level)

    # Create a formatter with color
    formatter = colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        log_colors={
            "DEBUG": color,
            "INFO": color,
            "WARNING": "yellow",
            "ERROR": "red",
            "CRITICAL": "red,bg_white",
        },
    )

    ch.setFormatter(formatter)
    logger.addHandler(ch)

    return logger


# Example usage of the setup_logging function
if __name__ == "__main__":
    logger = setup_logging(logger_name="example", level="INFO", color="cyan")
    logger.debug("This is a debug message.")
    logger.info("This is an info message.")
    logger.warning("This is a warning message.")
    logger.error("This is an error message.")
    logger.critical("This is a critical message.")
