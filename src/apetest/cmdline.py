# SPDX-License-Identifier: BSD-3-Clause

"""Command line interface."""

from argparse import ArgumentParser
import logging
from os import getcwd
from urllib.parse import urljoin, urlparse

from apetest.checker import Accept, PageChecker
from apetest.plugin import (
    PluginCollection, add_plugin_arguments, create_plugins, load_plugins
    )
from apetest.report import Scribe
from apetest.request import Request
from apetest.spider import spider_req
from apetest.version import VERSION_STRING

def detect_url(arg):
    """Attempt to turn a command line argument into a full URL."""
    url = urlparse(arg)
    if url.scheme in ('http', 'https'):
        return arg

    if arg.startswith('/'):
        # Assume absolute file path.
        return urljoin('file://', arg)

    url = urlparse('http://' + arg)
    idx = url.netloc.find(':')
    if idx != -1 and url.netloc[idx + 1:].isdigit():
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

def main():
    """Parse command line arguments and call `run` with the results.

    This is the entry point that gets called by the wrapper script.
    """

    # Register core arguments.
    parser = ArgumentParser(
        description='Automated Page Exerciser: '
                    'smarter-than-monkey testing for web apps',
        epilog='This is a test tool; do not use on production sites.'
        )
    parser.add_argument(
        'url', metavar='URL|PATH',
        help='web app/site to check'
        )
    parser.add_argument(
        '--accept', type=str, choices=('any', 'html'), default='any',
        help='accept serialization: any (HTML or XHTML; default) or HTML only'
        )
    parser.add_argument(
        'report', metavar='REPORT',
        help='file to write the HTML report to'
        )
    parser.add_argument(
        '-v', '--verbose', action='count', default=0,
        help='increase amount of logging, can be passed multiple times'
        )
    parser.add_argument(
        '-V', '--version', action='version', version='APE %s' % VERSION_STRING
        )

    # Let plugins register their arguments.
    plugin_modules = tuple(load_plugins())
    for module in plugin_modules:
        add_plugin_arguments(module, parser)

    args = parser.parse_args()

    level_map = {0: logging.WARNING, 1: logging.INFO, 2: logging.DEBUG}
    level = level_map.get(args.verbose, logging.DEBUG)
    logging.basicConfig(level=level, format='%(levelname)s: %(message)s')

    # Instantiate plugins.
    plugins = []
    for module in plugin_modules:
        try:
            plugins += create_plugins(module, args)
        except Exception: # pylint: disable=broad-except
            return 1

    accept = Accept[args.accept.upper()]
    return run(args.url, args.report, accept, plugins)
