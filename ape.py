#!/usr/bin/env python3
#
# SPDX-License-Identifier: BSD-3-Clause

from argparse import ArgumentParser
import logging
import sys

from apetest.checker import Accept
from apetest.cmdline import run
from apetest.plugin import add_plugin_arguments, create_plugins, load_plugins
from apetest.version import VERSION_STRING

def main():
    # Register core arguments.
    parser = ArgumentParser(
        description='Automated Page Exerciser: '
                    'smarter-than-monkey testing for web apps',
        epilog='This is a test tool; do not use on production sites.'
        )
    parser.add_argument(
        'url', metavar='URL|PATH',
        help='web app/site to check'
        )
    parser.add_argument(
        '--accept', type=str, choices=('any', 'html'), default='any',
        help='accept serialization: any (HTML or XHTML; default) or HTML only'
        )
    parser.add_argument(
        'report', metavar='REPORT',
        help='file to write the HTML report to'
        )
    parser.add_argument(
        '-v', '--verbose', action='count', default=0,
        help='increase amount of logging, can be passed multiple times'
        )
    parser.add_argument(
        '-V', '--version', action='version', version='APE %s' % VERSION_STRING
        )

    # Let plugins register their arguments.
    plugin_modules = tuple(load_plugins())
    for module in plugin_modules:
        add_plugin_arguments(module, parser)

    args = parser.parse_args()

    level_map = {0: logging.WARNING, 1: logging.INFO, 2: logging.DEBUG}
    level = level_map.get(args.verbose, logging.DEBUG)
    logging.basicConfig(level=level, format='%(levelname)s: %(message)s')

    # Instantiate plugins.
    plugins = []
    for module in plugin_modules:
        try:
            plugins += create_plugins(module, args)
        except Exception: # pylint: disable=broad-except
            sys.exit(1)

    accept = Accept[args.accept.upper()]
    sys.exit(run(args.url, args.report, accept, plugins))

if __name__ == '__main__':
    main()
