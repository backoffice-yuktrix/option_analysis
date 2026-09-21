from __future__ import annotations

import json
import logging
import sys
from logging.handlers import RotatingFileHandler

from app.config import LOG_FILE

_logger = logging.getLogger("live")


def setup_logging() -> None:
    if _logger.handlers:
        return
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(message)s")
    for handler in (
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(LOG_FILE, maxBytes=10_000_000, backupCount=5, encoding="utf-8"),
    ):
        handler.setFormatter(fmt)
        _logger.addHandler(handler)
    _logger.propagate = False


def log_event(event: dict) -> None:
    _logger.info(json.dumps(event, default=str))
