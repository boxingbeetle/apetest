#!/usr/bin/env python
#
# SPDX-License-Identifier: BSD-3-Clause

import sys

from checker import PageChecker
from plugin import PluginError, loadPlugins
from report import Scribe
from request import Request
from spider import Spider

def run(url, reportFileName, *pluginSpecs):
    try:
        firstRequest = Request.fromURL(url)
    except ValueError, ex:
        print 'Bad URL:', ex
        return 1
    plugins = []
    for spec in pluginSpecs:
        try:
            for plugin in loadPlugins(spec):
                plugins.append(plugin)
        except PluginError, ex:
            print ex
            return 1

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

    return 0

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print 'Usage:'
        print '  %s <URL> <report> (<plugin>(#<name>=<value>)*)*' % sys.argv[0]
        sys.exit(2)
    else:
        sys.exit(run(*sys.argv[1:])) # pylint: disable=no-value-for-parameter
