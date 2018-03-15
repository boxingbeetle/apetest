#!/usr/bin/env python
#
# SPDX-License-Identifier: BSD-3-Clause

from __future__ import print_function
import sys

from checker import PageChecker
from plugin import PluginError, load_plugins
from report import Scribe
from request import Request
from spider import Spider

def run(url, report_file_name, *plugin_specs):
    try:
        first_req = Request.from_url(url)
    except ValueError as ex:
        print('Bad URL:', ex)
        return 1
    plugins = []
    for spec in plugin_specs:
        try:
            for plugin in load_plugins(spec):
                plugins.append(plugin)
        except PluginError as ex:
            print(ex)
            return 1

    spider = Spider(first_req)
    base_url = first_req.page_url
    scribe = Scribe(base_url, spider, plugins)
    checker = PageChecker(base_url, scribe)

    print('Checking "%s" and below...' % base_url)
    for request in spider:
        referrers = checker.check(request)
        spider.add_requests(request, referrers)
    print('Done checking')

    print('Writing report to "%s"...' % report_file_name)
    with open(report_file_name, 'w') as out:
        for node in scribe.present():
            out.write(node.flatten())
    print('Done reporting')

    scribe.postprocess()
    print('Done post processing')

    return 0

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('Usage:')
        print('  %s <URL> <report> (<plugin>(#<name>=<value>)*)*' % sys.argv[0])
        sys.exit(2)
    else:
        sys.exit(run(*sys.argv[1:])) # pylint: disable=no-value-for-parameter
