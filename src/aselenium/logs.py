"""Package logger configured to remain silent until an application opts in."""

import logging

__all__ = ["logger"]

# Package logger
logger = logging.getLogger(__package__)
# Applications control logging levels, formatting and destinations.
logger.addHandler(logging.NullHandler())
