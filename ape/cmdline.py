# SPDX-License-Identifier: BSD-3-Clause

from ape.checker import PageChecker
from ape.report import Scribe
from ape.request import Request
from ape.spider import Spider
from ape.validator import HTMLValidator

def run(url, report_file_name, plugins=()):
    try:
        first_req = Request.from_url(url)
    except ValueError as ex:
        print('Bad URL:', ex)
        return 1

    htmlValidator = HTMLValidator()

    spider = Spider(first_req)
    base_url = first_req.page_url
    scribe = Scribe(base_url, spider, plugins)
    checker = PageChecker(base_url, scribe, htmlValidator)

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
