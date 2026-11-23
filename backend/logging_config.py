import logging
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent
LOG_DIR = BACKEND_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

LOG_FILE = LOG_DIR / "logger.log"


def configure_logging():
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    has_file_handler = any(
        isinstance(handler, logging.FileHandler)
        and Path(handler.baseFilename).resolve() == LOG_FILE.resolve()
        for handler in root_logger.handlers
    )

    if not has_file_handler:
        file_handler = logging.FileHandler(
            LOG_FILE,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)

    has_console_handler = any(
        isinstance(handler, logging.StreamHandler)
        and not isinstance(handler, logging.FileHandler)
        for handler in root_logger.handlers
    )

    if not has_console_handler:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)

    logging.getLogger(__name__).info(
        "Logging configured. log_file=%s level=INFO",
        LOG_FILE,
    )