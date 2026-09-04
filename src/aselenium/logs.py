# -*- coding: UTF-8 -*-
"""Aselenium logs implementation and supporting types."""

import logging

__all__ = ["logger"]

# Package logger
logger = logging.getLogger(__package__)
# Applications control logging levels, formatting and destinations.
logger.addHandler(logging.NullHandler())
