# SPDX-License-Identifier: BSD-3-Clause

from os import getcwd
from urllib.parse import urljoin, urlparse

from ape.checker import PageChecker
from ape.plugin import PluginCollection
from ape.report import Scribe
from ape.request import Request
from ape.spider import spider_req

def detect_url(arg):
    """Attempts to turn a command line argument into a full URL.
    """
    url = urlparse(arg)
    if url.scheme:
        return arg

    if arg.startswith('/'):
        # Assume absolute file path.
        return urljoin('file://', arg)

    idx = arg.find(':')
    if idx != -1 and arg[idx + 1:].isdigit():
        # Host and port without scheme, assume HTTP.
        return 'http://' + arg

    # Assume relative file path.
    return urljoin('file://%s/' % getcwd(), arg)

def run(url, report_file_name, accept, plugins=()):
    plugins = PluginCollection(plugins)
    try:
        try:
            first_req = Request.from_url(detect_url(url))
        except ValueError as ex:
            print('Bad URL:', ex)
            return 1

        spider, robots_report = spider_req(first_req)
        base_url = first_req.page_url
        scribe = Scribe(base_url, spider, plugins)
        scribe.add_report(robots_report)
        checker = PageChecker(base_url, accept, scribe, plugins)

        print('Checking "%s" and below...' % base_url)
        for request in spider:
            referrers = checker.check(request)
            spider.add_requests(request, referrers)
        print('Done checking')

        print('Writing report to "%s"...' % report_file_name)
        with open(report_file_name, 'w',
                encoding='ascii', errors='xmlcharrefreplace') as out:
            for node in scribe.present():
                out.write(node.flatten())
        print('Done reporting')

        scribe.postprocess()
        print('Done post processing')

        return 0
    finally:
        plugins.close()
