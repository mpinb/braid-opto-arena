import logging
import colorlog


def setup_logging(level="INFO", color="white"):
    numeric_level = getattr(logging, level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f"Invalid log level: {level}")

    # Create a logger
    logger = logging.getLogger()
    logger.setLevel(numeric_level)

    # Remove any existing handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    # Create a console handler
    ch = logging.StreamHandler()
    ch.setLevel(numeric_level)

    # Create a formatter with color
    formatter = colorlog.ColoredFormatter(
        "%(log_color)s%(asctime)s - %(filename)s - %(levelname)s - %(message)s",
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

    # Additional configurations can be added here, such as handlers, file logging, etc.


# Example of how to call setup_logging from a different script
if __name__ == "__main__":
    setup_logging(level="DEBUG", color="cyan")
    logging.debug("This is a debug message.")
    logging.info("This is an info message.")
    logging.warning("This is a warning message.")
    logging.error("This is an error message.")
    logging.critical("This is a critical message.")
