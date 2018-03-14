#!/usr/bin/env python
#
# SPDX-License-Identifier: BSD-3-Clause

import sys

from checker import PageChecker
from plugin import PluginError, loadPlugins
from report import Scribe
from request import Request
from spider import Spider

if len(sys.argv) < 3:
    print 'Usage:'
    print '  ' + sys.argv[0] + ' <URL> <report> (<plugin>(#<name>=<value>)*)*'
    sys.exit(2)

try:
    firstRequest = Request.fromURL(sys.argv[1])
except ValueError, ex:
    print 'Bad URL:', ex
    sys.exit(1)
reportFileName = sys.argv[2]
plugins = []
for pluginSpec in sys.argv[3 : ]:
    try:
        for plugin in loadPlugins(pluginSpec):
            plugins.append(plugin)
    except PluginError, ex:
        print ex
        sys.exit(1)

spider = Spider(firstRequest)
baseURL = firstRequest.pageURL
scribe = Scribe(baseURL, spider, plugins)
checker = PageChecker(baseURL, scribe)

print 'Checking "%s" and below...' % baseURL
for request in spider:
    referrers = checker.check(request)
    spider.addRequests(request, referrers)
print 'Done checking'

print 'Writing report to "%s"...' % reportFileName
out = file(reportFileName, 'w')
for node in scribe.present():
    out.write(node.flatten())
out.close()
print 'Done reporting'

scribe.postProcess()
print 'Done post processing'
