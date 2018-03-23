#!/usr/bin/env python3
#
# SPDX-License-Identifier: BSD-3-Clause

from argparse import ArgumentParser
import sys

from ape.cmdline import run
from ape.plugin import add_plugin_arguments, create_plugins, load_plugins

def main():
    # Register core arguments.
    parser = ArgumentParser(
        description='Automated Page Exerciser: '
                    'smarter-than-monkey testing for web apps',
        epilog='This is a test tool; do not use on production sites.'
        )
    parser.add_argument(
        'url',
        help='web app/site to check'
        )
    parser.add_argument(
        'report',
        help='file to write the HTML report to'
        )

    # Let plugins register their arguments.
    plugin_modules = tuple(load_plugins())
    for module in plugin_modules:
        add_plugin_arguments(module, parser)

    args = parser.parse_args()

    # Instantiate plugins.
    plugins = []
    for module in plugin_modules:
        try:
            plugins += create_plugins(module, args)
        except Exception: # pylint: disable=broad-except
            sys.exit(1)

    sys.exit(run(args.url, args.report, plugins))

if __name__ == '__main__':
    main()
