#!/usr/bin/env python3
#
# SPDX-License-Identifier: BSD-3-Clause

from argparse import ArgumentParser
import sys

from ape.cmdline import run

def main():
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
    parser.add_argument(
        'plugin', nargs='*',
        help='name(#arg=value)*'
        )
    args = parser.parse_args()
    sys.exit(run(args.url, args.report, *args.plugin))

if __name__ == '__main__':
    main()
