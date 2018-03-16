#!/usr/bin/env python3
#
# SPDX-License-Identifier: BSD-3-Clause

import sys

from ape.cmdline import run

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('Usage:')
        print('  %s <URL> <report> (<plugin>(#<name>=<value>)*)*' % sys.argv[0])
        sys.exit(2)
    else:
        sys.exit(run(*sys.argv[1:])) # pylint: disable=no-value-for-parameter
