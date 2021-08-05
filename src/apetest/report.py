# SPDX-License-Identifier: BSD-3-Clause

"""Gathers and presents checker results in a report.

If a page was loaded, the results of checking it can be stored
in a L{Report} instance. If a page fails to load, the problems
in trying to fetch it can be stored in a L{FetchFailure} report.

Reports are L{logging.LoggerAdapter} implementations, so you can call
the usual L{info<logging.Logger.info>}, L{warning<logging.Logger.warning>}
and L{error<logging.Logger.error>} logging methods on them to store
checker results.

L{Scribe} collects reports for multiple pages and can generate
a combined report from them.
"""

from collections import defaultdict
from datetime import datetime, timezone
from enum import Enum, auto
from logging import INFO, Handler, LogRecord, LoggerAdapter, getLogger
from typing import (
    TYPE_CHECKING,
    Any,
    Collection,
    DefaultDict,
    Dict,
    List,
    MutableMapping,
    Optional,
    Tuple,
)
from urllib.parse import unquote_plus, urlsplit
from urllib.response import addinfourl

from apetest.plugin import PluginCollection
from apetest.request import Request
from apetest.xmlgen import XMLContent, raw, xml

if TYPE_CHECKING:
    # pylint: disable=cyclic-import
    from apetest.spider import Spider
else:
    Spider = object


_STYLE_SHEET = raw(
    """
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
"""
)


class StoreHandler(Handler):
    """A log handler that stores all logged records in a list.

    Used internally to store messages logged to reports.

    Log records handled by this handler must have a C{url} property
    that contains the URL that the record applies to.
    """

    def __init__(self) -> None:
        super().__init__()
        self.records: DefaultDict[str, List[LogRecord]] = defaultdict(list)
        """Maps a URL to a collection of reports for that URL."""

    def emit(self, record: LogRecord) -> None:
        """Store a log record in our L{records}."""
        self.format(record)
        # The 'url' attribute is defined via the 'extra' mechanism.
        url: str = record.url  # type: ignore[attr-defined]
        self.records[url].append(record)


_LOG = getLogger(__name__)
_LOG.setLevel(INFO)
_HANDLER = StoreHandler()
_LOG.addHandler(_HANDLER)
_LOG.propagate = False


class Checked(Enum):
    """The content check status of a document."""

    NOT_CHECKED = auto()
    """The content has not been checked yet."""

    NO_CONTENT = auto()
    """No content was available for checking."""

    HTTP_STATUS_SKIP = auto()
    """Content check was skipped because of HTTP status code."""

    CHECKED = auto()
    """The content has been checked by at least one checker."""


class Report(LoggerAdapter):
    """Gathers check results for a document produced by one request."""

    def __init__(self, url: str):
        """Initialize a report that will be collecting results
        for the document at C{url}.
        """
        super().__init__(_LOG, dict(url=url))

        self.url = url
        """The request URL to which this report applies."""

        self.ok = True  # pylint: disable=invalid-name
        """C{True} iff no warnings or errors were reported.

        This is initialized to C{True} and will be set to C{False}
        when a message with a level higher than C{INFO} (such as
        a warning or error) is logged on this report.
        """

        self.checked = Checked.NOT_CHECKED
        """The content check status of the document.

        This is initialized to L{NOT_CHECKED}. A checker should set it to
        L{CHECKED} when it has checked the document.
        """

    def log(self, level: int, msg: Any, *args: Any, **kwargs: Any) -> None:
        if level > INFO:
            self.ok = False
        super().log(level, msg, *args, **kwargs)

    def process(
        self, msg: Any, kwargs: MutableMapping[str, Any]
    ) -> Tuple[Any, MutableMapping[str, Any]]:
        """Process contextual information for a logged message.

        Our C{url} will be inserted into the log record.
        """

        extra = kwargs.get("extra")
        if extra is None:
            extra = self.extra
        else:
            extra.update(self.extra)
        kwargs["extra"] = extra

        return msg, kwargs

    def present(self, scribe: "Scribe") -> XMLContent:
        """Yield an XHTML rendering of this report."""

        present_record = self.present_record
        yield xml.ul[(present_record(record) for record in _HANDLER.records[self.url])]

        if self.checked is Checked.NOT_CHECKED:
            yield xml.p["No content checks were performed"]
        if not self.ok:
            yield xml.p["Referenced by:"]
            # TODO: Store Request object instead of recreating it.
            request = Request.from_url(self.url)
            yield xml.ul[
                # pylint: disable=protected-access
                scribe._present_referrers(request)
            ]

    @staticmethod
    def present_record(record: LogRecord) -> XMLContent:
        """Return an XHTML rendering of one log record."""

        level = record.levelname.lower()
        html = getattr(record, "html", record.message)
        return xml.li(class_=level)[html]


class FetchFailure(Report, Exception):
    """Records the details of a request that failed.

    This is an L{Exception}, so it can be raised instead of returned,
    where that is appropriate.
    """

    def __init__(self, url: str, message: str, http_error: Optional[addinfourl] = None):
        """Initialize the report and log C{message} as an error."""
        Report.__init__(self, url)
        Exception.__init__(self, message)

        self.http_error = http_error
        """Optional error that caused this fetch failure."""

        self.error("Failed to fetch: %s", message)


class Page:
    """Information collected by L{Scribe} about a single page.

    A page is identified by a URL minus query.
    """

    def __init__(self, name: str):
        """Initialize page with no reports."""

        self._name = name

        self.query_to_report: Dict[str, Report] = {}
        """Maps a query string to the report for that query."""

        self.failures = 0
        """Number of reports that contain warnings or errors."""

    @property
    def name(self) -> str:
        """The name (slug) of this page."""
        return self._name

    def add_report(self, report: Report) -> None:
        """Add a L{Report} for this page.

        For each unique query, only one report can be added.
        Reports should only be added once final: after all checks
        for them are done.
        """

        scheme_, host_, path_, query, fragment_ = urlsplit(report.url)
        assert query not in self.query_to_report
        self.query_to_report[query] = report
        if not report.ok:
            self.failures += 1

    def present(self, scribe: "Scribe") -> XMLContent:
        """Yield an XHTML rendering of all reports for this page."""

        # Use more compact presentation for local files.
        if len(self.query_to_report) == 1:
            ((query, report),) = self.query_to_report.items()
            if query == "" and report.url.startswith("file:"):
                verdict = "pass" if report.ok else "fail"
                yield xml.h3(class_=verdict)[verdict]
                yield report.present(scribe)
                return

        # Use detailed presentation for pages served over HTTP.
        total = len(self.query_to_report)
        failures = self.failures
        yield xml.p[
            f"{total:d} queries checked, "
            f"{total - failures:d} passed, "
            f"{failures:d} failed"
        ]
        for query, report in sorted(self.query_to_report.items()):
            yield xml.h3(class_="pass" if report.ok else "fail")[
                xml.a(href=report.url)[
                    " | ".join(
                        "%s = %s" % tuple(unquote_plus(s) for s in elem.split("="))
                        for elem in query.split("&")
                    )
                    if query
                    else "(no query)"
                ]
            ]
            yield report.present(scribe)


def now_local() -> datetime:
    """@return: The current time, in the local time zone."""
    return datetime.now(timezone.utc).astimezone()


class Scribe:
    """Collects reports for multiple pages."""

    def __init__(self, base_url: str, spider: Spider, plugins: PluginCollection):
        """Initialize scribe.

        @param base_url:
            Page URL at the base of the app or site that is being checked.
            The root URL will be computed from this by dropping the path
            element after the last directory level, if any.
        @param spider:
            Spider from which links between pages can be looked up.
        @param plugins:
            Plugins that will receive notifications from this scribe.
        """

        scheme_, host_, base_path, query, fragment = urlsplit(base_url)
        assert query == ""
        assert fragment == ""
        # HTTP requires empty URL path to be mapped to "/".
        #   https://tools.ietf.org/html/rfc7230#section-5.3.1
        base_path = base_path or "/"
        self._base_path = base_path[: base_path.rindex("/") + 1]

        self._spider = spider
        self._plugins = plugins
        self._pages: Dict[str, Page] = {}
        self._start_time = now_local()
        self._end_time: Optional[datetime] = None

    @property
    def start_time(self) -> datetime:
        """The local time at which this test run started."""
        return self._start_time

    @property
    def end_time(self) -> Optional[datetime]:
        """The local time at which this test run ended,
        or None if it did not end yet.
        """
        return self._end_time

    def __url_to_name(self, url: str) -> str:
        path = urlsplit(url).path or "/"
        assert path.startswith(self._base_path)
        return path[len(self._base_path) :]

    def add_report(self, report: Report) -> None:
        """Add a report to this scribe.

        Plugins are notified of the new report.
        """
        self._plugins.report_added(report)

        url = report.url
        name = self.__url_to_name(url)
        page = self._pages.get(name)
        if page is None:
            page = Page(name)
            self._pages[name] = page
        page.add_report(report)

    def get_pages(self) -> Collection[Page]:
        """Return the pages for which reports were added to this scribe."""
        return self._pages.values()

    def get_failed_pages(self) -> Collection[Page]:
        """Like L{get_pages}, but only pages for which warnings or errors
        were reported are returned.
        """
        return [page for page in self._pages.values() if page.failures != 0]

    def get_summary(self) -> str:
        """Return a short string summarizing the check results."""
        total = len(self._pages)
        num_failed_pages = len(self.get_failed_pages())
        return (
            f"{total:d} pages checked, "
            f"{total - num_failed_pages:d} passed, "
            f"{num_failed_pages:d} failed"
        )

    def postprocess(self) -> None:
        """Instruct the plugins to do their final processing."""
        self._end_time = now_local()
        self._plugins.postprocess(self)

    def present(self) -> XMLContent:
        """Yield an XHTML rendering of a combined report for all
        checked pages.
        """
        title = "APE - Automated Page Exerciser"
        yield xml.html[
            xml.head[xml.title[title], xml.style(type="text/css")[_STYLE_SHEET]],
            xml.body[
                xml.h1[title],
                xml.p[self.get_summary()],
                self._present_failed_index(),
                (
                    (
                        xml.h2[xml.a(name=name or "base")[name or "(base)"]],
                        page.present(self),
                    )
                    for name, page in sorted(self._pages.items())
                ),
            ],
        ]

    def _present_failed_index(self) -> XMLContent:
        failed_page_names = [
            name for name, page in self._pages.items() if page.failures != 0
        ]
        if failed_page_names:
            yield xml.p["Failed pages:"]
            yield xml.ul[
                (
                    xml.li[xml.a(href="#" + (name or "base"))[name or "(base)"]]
                    for name in sorted(failed_page_names)
                )
            ]

    def _present_referrers(self, req: Request) -> XMLContent:
        # Note: Currently we only list the pages a request is referred from,
        #       but we know the exact requests.
        page_names = {
            self.__url_to_name(source_req.page_url)
            for source_req in self._spider.iter_referring_requests(req)
        }
        for name in sorted(page_names):
            yield xml.li[xml.a(href="#" + (name or "base"))[name or "(base)"]]
