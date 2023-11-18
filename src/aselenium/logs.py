# -*- coding: UTF-8 -*-
import logging

__all__ = ["logger"]

# Package logger
logger = logging.getLogger(__package__)
_log_format = logging.Formatter(
    "%(asctime)s %(levelname)s - %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)
logger.setLevel(logging.INFO)
_handler = logging.StreamHandler()
_handler.setFormatter(_log_format)
logger.addHandler(_handler)
