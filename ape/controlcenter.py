# SPDX-License-Identifier: BSD-3-Clause

import os

from plugin import Plugin

class DataChangeMonitor(Plugin):

    allowed_changes = (
        # Shadow DB has automatic cleanup.
        ('shadow', 'remove'),
        # These are singleton records that are created automatically.
        # Note that only "add" is accepted, "update" is not.
        ('project', 'add'),
        # Schedule start times will automatically update if the current time
        # is past the stored start time.
        ('scheduled', 'update'),
        )

    def __init__(self, cclog):
        Plugin.__init__(self)
        self._log_file = cclog
        self._log_fd = None
        self._partial_line = ''

    def __process_data(self, report):
        if self._log_fd is None:
            try:
                self._log_fd = os.open(
                    self._log_file, os.O_RDONLY | os.O_NONBLOCK
                    )
            except OSError as ex:
                report.add_plugin_warning(
                    'Could not open log file for reading: %s' % ex
                    )
                return
        while True:
            new_data = os.read(self._log_fd, 200)
            if new_data:
                buf = self._partial_line + new_data
                lines = buf.split('\n')
                for line in lines[ : -1]:
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
            if (db_name, change) not in self.allowed_changes:
                report.add_plugin_warning(
                    'Unexpected %s in database "%s" on record "%s"'
                    % (change, db_name, record_id)
                    )
