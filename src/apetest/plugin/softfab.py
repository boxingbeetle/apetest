# SPDX-License-Identifier: BSD-3-Clause

"""Plugin that creates a properties file summarizing the test results.

This properties file can be used as-is by SoftFab, but should be easy
to use with other tools as well. The format is of a Java C{.properties}
file, similar to a Windows C{.ini} file. It is a text with with one
key-value pair per line, with C{=} as the separator.
"""

from argparse import ArgumentParser, Namespace
from typing import Iterator

from apetest.plugin import Plugin
from apetest.report import Scribe


def plugin_arguments(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--result", help="properties file (SoftFab compatible) to write results to"
    )


def plugin_create(args: Namespace) -> Iterator[Plugin]:
    if args.result is not None:
        yield PropertiesPlugin(args.result)


class PropertiesPlugin(Plugin):
    """Plugin that creates a SoftFab-compatible results properties file."""

    def __init__(self, properties_file: str):
        """Initialize the plugin to write C{properties_file}."""
        self.properties_file = properties_file

    def postprocess(self, scribe: Scribe) -> None:
        total = len(scribe.get_pages())
        num_failed_pages = len(scribe.get_failed_pages())
        data = {
            "result": "ok" if num_failed_pages == 0 else "warning",
            "summary": scribe.get_summary(),
            "data.pages_total": total,
            "data.pages_pass": total - num_failed_pages,
            "data.pages_fail": num_failed_pages,
        }
        path = self.properties_file
        print(f'Writing metadata to "{path}"...')
        with open(path, "w") as out:
            for key in sorted(data.keys()):
                print(f"{key}={data[key]}", file=out)
