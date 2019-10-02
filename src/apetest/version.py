# SPDX-License-Identifier: BSD-3-Clause

"""Package version info."""

from typing import TYPE_CHECKING

# On Python 3.8+, use importlib.metadata from the standard library.
# On older versions, a compatibility package can be installed from PyPI.
try:
    if not TYPE_CHECKING:
        import importlib.metadata as importlib_metadata
except ImportError:
    import importlib_metadata

VERSION_STRING = importlib_metadata.version('apetest')
