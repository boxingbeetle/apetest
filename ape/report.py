# SPDX-License-Identifier: BSD-3-Clause

from collections import defaultdict
import logging
from urllib.parse import unquote_plus, urlsplit

from ape.request import Request
from ape.xmlgen import raw, xml

_STYLE_SHEET = raw('''
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
    list-style-image: url('data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="1em" height="1em" viewBox="0 0 10 10" version="1.1"><path fill="%23e00" d="M0,5 a5,5 0 0 0 10,0 5,5 0 0 0 -10,0 Z M5,3.75 6.75,2 8,3.25 6.25,5 8,6.75 6.75,8 5,6.25 3.25,8 2,6.75 3.75,5 2,3.25 3.35,2 Z"/></svg>');
}
li.warning {
    list-style-image: url('data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="1em" height="1em" viewBox="0 0 10 10" version="1.1"><path fill="%23f70" d="M1,10 h8 a1,1 0 0 0 0.866,-1.5 l-4,-7 a1,1 0 0 0 -1.732,0 l-4,7 a1,1 0 0 0 0.866,1.5 Z M4.5,3 h1 v4 h-1 Z M5,7.75 a0.75,0.75 0 0 1 0,1.5 0.75,0.75 0 0 1 0,-1.5 Z"/></svg>');
}
li.info {
    list-style-image: url('data:image/svg+xml,<svg xmlns="http://www.w3.org/2000/svg" width="1em" height="1em" viewBox="0 0 10 10" version="1.1"><path fill="%2333f" d="M0,5 a5,5 0 0 0 10,0 5,5 0 0 0 -10,0 Z M5,1.25 a1,1 0 0 1 0,2 1,1 0 0 1 0,-2 Z M3.5,4.25 h2 v3 h1 v1 h-3 v-1 h1 v-2 h-1 Z"/></svg>');
}
span.extract {
    background: #FFFFB0;
}
code {
    background: #F0F0F0;
    color: #000000;
}
''')

class StoreHandler(logging.Handler):
    """A log handler that stores all logged records in a list.
    """

    def __init__(self):
        logging.Handler.__init__(self)
        self.records = defaultdict(list)

    def emit(self, record):
        self.format(record)
        self.records[record.url].append(record)

_LOG = logging.getLogger(__name__)
_LOG.setLevel(logging.INFO)
_HANDLER = StoreHandler()
_LOG.addHandler(_HANDLER)
_LOG.propagate = False

class Report(logging.LoggerAdapter):
    ok = True # ...until proven otherwise
    checked = False

    def __init__(self, url):
        logging.LoggerAdapter.__init__(self, _LOG, dict(url=url))
        self.url = url

    def log(self, level, msg, *args, **kwargs):
        if level > logging.INFO:
            self.ok = False # pylint: disable=invalid-name
        super().log(level, msg, *args, **kwargs)

    def present(self, scribe):
        present_record = self.present_record
        yield xml.ul[(
            present_record(record)
            for record in _HANDLER.records[self.url]
            )]

        if not self.checked:
            yield xml.p['No content checks were performed']
        if not self.ok:
            yield xml.p['Referenced by:']
            # TODO: Store Request object instead of recreating it.
            request = Request.from_url(self.url)
            yield xml.ul[scribe.present_referrers(request)]

    @staticmethod
    def present_record(record):
        level = record.levelname.lower()
        html = getattr(record, 'html', record.message)
        return xml.li(class_=level)[html]

class FetchFailure(Report, Exception):
    ok = False

    def __init__(self, url, message, http_error=None):
        Report.__init__(self, url)
        Exception.__init__(self, message)
        self.http_error = http_error
        self.error('Failed to fetch: %s', message)

class IncrementalReport(Report):

    def process(self, msg, kwargs):
        if isinstance(msg, str):
            message = msg
        else:
            if hasattr(msg, 'line'):
                line = msg.line
            elif hasattr(msg, 'position'):
                line = msg.position[0]
            else:
                line = None

            message = msg.message
            if line is not None:
                message += ' (line %d)' % line

        extra = kwargs.get('extra')
        if extra is None:
            extra = self.extra
        else:
            extra.update(self.extra)
        kwargs['extra'] = extra

        return message, kwargs

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
        scheme_, host_, base_path, query, fragment = urlsplit(base_url)
        assert query == ''
        assert fragment == ''
        # HTTP requires empty URL path to be mapped to "/".
        #   https://tools.ietf.org/html/rfc7230#section-5.3.1
        base_path = base_path or '/'
        self._base_path = base_path = base_path[ : base_path.rindex('/') + 1]

        self._spider = spider
        self._plugins = plugins
        self._pages = defaultdict(Page)

    def __url_to_name(self, url):
        path = urlsplit(url).path or '/'
        assert path.startswith(self._base_path)
        return path[len(self._base_path) : ]

    def add_report(self, report):
        self._plugins.report_added(report)

        url = report.url
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
        self._plugins.postprocess(self)

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
            for source_req in self._spider.iter_referring_requests(req)
            )
        for name in sorted(page_names):
            yield xml.li[xml.a(href='#' + (name or 'base'))[name or '(base)']]
