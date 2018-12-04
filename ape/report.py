# SPDX-License-Identifier: BSD-3-Clause

from collections import defaultdict
from urllib.parse import unquote_plus, urlsplit

from ape.request import Request
from ape.xmlgen import concat, xml

_STYLE_SHEET = '''
body {
    margin: 0;
    padding: 0;
    background-color: #FFFFFF;
    color: black;
    font-family: vera, arial, sans-serif;
}
a {
    color: black;
}
h1, h2 {
    border-top: 1px solid #808080;
    border-bottom: 1px solid #808080;
}
h1 {
    margin: 0 0 12pt 0;
    padding: 3pt 12pt;
    background-color: #E0E0E0;
}
h2 {
    padding: 2pt 12pt;
    background-color: #F0F0F0;
}
h3, p, dl {
    padding: 1pt 12pt;
}
h3.pass {
    background-color: #90FF90;
}
h3.fail {
    background-color: #FF9090;
}
li {
    line-height: 125%;
}
li.error {
    color: #C00000;
}
li.warning {
    color: #006680;
}
li.info {
    color: #202020;
}
span.extract {
    background: #FFFFB0;
}
code {
    background: #F0F0F0;
    color: #000000;
}
'''

class Report:
    ok = True # ...until proven otherwise
    checked = False

    def __init__(self, url):
        self.url = url
        self._plugin_warnings = []

    def add_plugin_warning(self, message):
        self._plugin_warnings.append(message)
        self.ok = False # pylint: disable=invalid-name

    def present(self, scribe):
        if not self.checked:
            yield xml.p['No content checks were performed']
        if self._plugin_warnings:
            yield xml.p['Problems reported by plugins:']
            yield xml.ul[(
                xml.li[warning]
                for warning in self._plugin_warnings
                )]
        if not self.ok:
            yield xml.p['Referenced by:']
            # TODO: Store Request object instead of recreating it.
            request = Request.from_url(self.url)
            yield xml.ul[scribe.present_referrers(request)]

class FetchFailure(Report, Exception):
    ok = False
    description = 'Failed to fetch'

    def __init__(self, url, message):
        Report.__init__(self, url)
        Exception.__init__(self, message)

    def present(self, scribe):
        yield xml.p[self.description, ': ', str(self)]
        yield Report.present(self, scribe)

class IncrementalReport(Report):

    @staticmethod
    def __present_message(data):
        if isinstance(data, str):
            return data

        if hasattr(data, 'message'):
            message = data.message
        else:
            message = concat(data)

        if hasattr(data, 'line'):
            line = data.line
        elif hasattr(data, 'position'):
            line = data.position[0]
        else:
            line = None
        if line is not None:
            message += ' (line %d)' % line

        return message

    def __init__(self, url):
        Report.__init__(self, url)
        self._messages = []

    def add_message(self, level, message):
        self._messages.append((level, message))
        if level != 'info':
            self.ok = False

    def add_info(self, message):
        self.add_message('info', message)

    def add_warning(self, message):
        self.add_message('warning', message)

    def add_error(self, message):
        self.add_message('error', message)

    def present(self, scribe):
        yield xml.ul[(
            xml.li(class_=level)[
                level + ': ', self.__present_message(data)
                ]
            for level, data in self._messages
            )]
        yield Report.present(self, scribe)

class Page:

    def __init__(self):
        self.query_to_report = {}
        self.failures = 0

    def add_report(self, report):
        scheme_, host_, path_, query, fragment_ = urlsplit(report.url)
        assert query not in self.query_to_report
        self.query_to_report[query] = report
        if not report.ok:
            self.failures += 1

    def present(self, scribe):
        # Use more compact presentation for local files.
        if len(self.query_to_report) == 1:
            (query, report), = self.query_to_report.items()
            if query == '' and report.url.startswith('file:'):
                verdict = 'pass' if report.ok else 'fail'
                yield xml.h3(class_=verdict)[verdict]
                yield report.present(scribe)
                return

        # Use detailed presentation for pages served over HTTP.
        total = len(self.query_to_report)
        yield xml.p[
            '%d queries checked, %d passed, %d failed'
            % (total, total - self.failures, self.failures)
            ]
        for query, report in sorted(self.query_to_report.items()):
            yield xml.h3(class_='pass' if report.ok else 'fail')[
                xml.a(href=report.url)[
                    ' | '.join(
                        '%s = %s' % tuple(
                            unquote_plus(s) for s in elem.split('=')
                            )
                        for elem in query.split('&')
                        ) if query else '(no query)'
                    ]
                ]
            yield report.present(scribe)

class Scribe:

    def __init__(self, base_url, spider, plugins):
        self.base_url = base_url
        self.spider = spider
        scheme_, host_, base_path, query, fragment = urlsplit(base_url)
        assert query == ''
        assert fragment == ''
        # HTTP requires empty URL path to be mapped to "/".
        #   https://tools.ietf.org/html/rfc7230#section-5.3.1
        base_path = base_path or '/'
        self.base_path = base_path = base_path[ : base_path.rindex('/') + 1]

        self.plugins = plugins

        self.reports = {}
        self._pages = defaultdict(Page)
        self.reports_by_page = {}

    def __url_to_name(self, url):
        path = urlsplit(url).path or '/'
        assert path.startswith(self.base_path)
        return path[len(self.base_path) : ]

    def add_report(self, report):
        self.plugins.report_added(report)

        url = report.url
        # Note: Currently, each URL is only visited once.
        #       Since we do not modify the database, a second fetch would
        #       not lead to different results than the first.
        assert url not in self.reports
        self.reports[url] = report

        page = self._pages[self.__url_to_name(url)]
        page.add_report(report)

    def get_pages(self):
        return self._pages.values()

    def get_failed_pages(self):
        return [
            page for page in self._pages.values() if page.failures != 0
            ]

    def get_summary(self):
        total = len(self._pages)
        num_failed_pages = len(self.get_failed_pages())
        return '%d pages checked, %d passed, %d failed' % (
            total, total - num_failed_pages, num_failed_pages
            )

    def postprocess(self):
        self.plugins.postprocess(self)

    def present(self):
        title = 'APE - Automated Page Exerciser'
        yield xml.html[
            xml.head[
                xml.title[title],
                xml.style(type='text/css')[_STYLE_SHEET]
                ],
            xml.body[
                xml.h1[title],
                xml.p[self.get_summary()],
                self.present_failed_index(),
                ((xml.h2[xml.a(name=name or 'base')[name or '(base)']],
                  page.present(self))
                 for name, page in sorted(self._pages.items()))
                ]
            ]

    def present_failed_index(self):
        failed_page_names = [
            name for name, page in self._pages.items() if page.failures != 0
            ]
        if failed_page_names:
            yield xml.p['Failed pages:']
            yield xml.ul[(
                xml.li[
                    xml.a(href='#' + (name or 'base'))[name or '(base)']
                    ]
                for name in sorted(failed_page_names)
                )]

    def present_referrers(self, req):
        # Note: Currently we only list the pages a request is referred from,
        #       but we know the exact requests.
        page_names = set(
            self.__url_to_name(source_req.page_url)
            for source_req in self.spider.iter_referring_requests(req)
            )
        for name in sorted(page_names):
            yield xml.li[xml.a(href='#' + (name or 'base'))[name or '(base)']]
