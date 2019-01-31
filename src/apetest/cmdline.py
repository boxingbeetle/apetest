# SPDX-License-Identifier: BSD-3-Clause

"""Command line interface."""

from os import getcwd
from urllib.parse import urljoin, urlparse

from apetest.checker import PageChecker
from apetest.plugin import PluginCollection
from apetest.report import Scribe
from apetest.request import Request
from apetest.spider import spider_req

def detect_url(arg):
    """Attempt to turn a command line argument into a full URL."""
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
    """Runs APE with the given arguments.

    Parameters:

    url
        Base URL of the web site or app to check.
    report_file_name
        Path to write the HTML report to.
    accept: apetest.checker.Accept
        Document types that we tell the server that we accept.
    plugins: apetest.plugin.Plugin*
        Plugins to use on this run.

    Returns:

    exit_code
        0 if successful, non-zero on errors.

    """
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
        if robots_report is not None:
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
