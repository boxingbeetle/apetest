# SPDX-License-Identifier: BSD-3-Clause

"""Plugin that monitors the SoftFab Control Center's log
while it is being tested.

This plugin is only useful as-is for people working on SoftFab, but it
can serve as an example for implementing a custom plugin that checks the
log of a web app under test.
"""

import os

from apetest.plugin import Plugin

def plugin_arguments(parser):
    parser.add_argument(
        '--cclog',
        help='log file to monitor for Control Center database changes'
        )

def plugin_create(args):
    if args.cclog is not None:
        yield DataChangeMonitor(args.cclog)

class DataChangeMonitor(Plugin):
    """Monitors the log file for reported database changes.

    HTTP `GET` requests must be idempotent, so any database activity
    resulting from them is suspect.
    """

    def __init__(self, cclog):
        """Initialize a monitor for the log at file path `cclog`."""
        self._log_file = cclog
        self._log_fd = None
        self._partial_line = b''

    def __process_data(self, report):
        if self._log_fd is None:
            try:
                self._log_fd = os.open(
                    self._log_file, os.O_RDONLY | os.O_NONBLOCK
                    )
            except OSError as ex:
                report.warning('Could not open log file for reading: %s', ex)
                return
        while True:
            new_data = os.read(self._log_fd, 200)
            if new_data:
                buf = self._partial_line + new_data
                lines = buf.split(b'\n')
                for line in lines[ : -1]:
                    line = line.decode('ascii')
                    index = line.find('> datachange/')
                    if index >= 0:
                        marker_, db_name, change, record_id = \
                            line[index + 2 : ].split('/')
                        yield change, db_name, record_id
                self._partial_line = lines[-1]
            else:
                break

    def report_added(self, report):
        for change, db_name, record_id in self.__process_data(report):
            if (db_name, change) in (
                    # Shadow DB has automatic cleanup.
                    ('shadow', 'remove'),
                    # These are singleton records that are created
                    # automatically.
                    # Note that only "add" is accepted, "update" is not.
                    ('project', 'add'),
                    # Schedule start times will automatically update if the
                    # current time is past the stored start time.
                    ('scheduled', 'update'),
                    # Reserved resource types are created automatically.
                    # The code below checks whether the type was indeed
                    # reserved.
                    ('restypes', 'add')):
                if db_name != 'restypes' or record_id.startswith('sf.'):
                    continue
            report.warning(
                'Unexpected %s in database "%s" on record "%s"',
                change, db_name, record_id
                )
