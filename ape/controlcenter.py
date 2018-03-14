# SPDX-License-Identifier: BSD-3-Clause

import os

from plugin import Plugin

class DataChangeMonitor(Plugin):

    allowedChanges = (
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
        self.logFile = cclog
        self.logFD = None
        self.partialLine = ''

    def __processData(self):
        if self.logFD is None:
            self.logFD = os.open(self.logFile, os.O_RDONLY | os.O_NONBLOCK)
        while True:
            newData = os.read(self.logFD, 200)
            if newData:
                buf = self.partialLine + newData
                lines = buf.split('\n')
                for line in lines[ : -1]:
                    index = line.find('> datachange/')
                    if index >= 0:
                        marker_, dbName, change, recordId = \
                            line[index + 2 : ].split('/')
                        yield change, dbName, recordId
                self.partialLine = lines[-1]
            else:
                break

    def reportAdded(self, report):
        for change, dbName, recordId in self.__processData():
            if (dbName, change) not in self.allowedChanges:
                report.addPluginWarning(
                    'Unexpected %s in database "%s" on record "%s"'
                    % (change, dbName, recordId)
                    )
