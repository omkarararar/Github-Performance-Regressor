import logging
import sys

def get_logger(name: str) -> logging.Logger:
    """Create a structured logger for a pipeline node."""
    logger = logging.getLogger(f"perf-regressor.{name}")

    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(
            "[%(asctime)s] %(name)s | %(levelname)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

    return logger
