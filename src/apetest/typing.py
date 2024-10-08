# SPDX-License-Identifier: BSD-3-Clause

"""
Various helpers for static type checking.
"""

from __future__ import annotations

from logging import Logger, LoggerAdapter
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # pylint: disable=unsubscriptable-object
    LoggerT = Logger | LoggerAdapter[Any]
    LoggerBase = LoggerAdapter[Logger]
else:
    LoggerT = LoggerAdapter
    LoggerBase = LoggerAdapter
