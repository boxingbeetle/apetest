# SPDX-License-Identifier: BSD-3-Clause

from request import Request
from xmlgen import xml

from urllib import unquote_plus
from urlparse import urlsplit

styleSheet = '''
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
'''

class Report(object):
    ok = True # ...until proven otherwise

    def __init__(self, url):
        self.url = url
        self.pluginWarnings = []

    def addPluginWarning(self, message):
        self.pluginWarnings.append(message)
        self.ok = False

    def present(self, scribe):
        if self.pluginWarnings:
            yield xml.p[ 'Problems reported by plugins:' ]
            yield xml.ul[(
                xml.li[ warning ]
                for warning in self.pluginWarnings
                )]
        if not self.ok:
            yield xml.p[ 'Referenced by:' ]
            # TODO: Store Request object instead of recreating it.
            request = Request.fromURL(self.url)
            yield xml.ul[ scribe.presentReferrers(request) ]

class FetchFailure(Report, Exception):
    ok = False
    description = 'Failed to fetch'

    def __init__(self, url, message):
        Report.__init__(self, url)
        Exception.__init__(self, message)

    def present(self, scribe):
        yield xml.p[ self.description, ': ', str(self) ]
        yield Report.present(self, scribe)

class IncrementalReport(Report):

    @staticmethod
    def __presentValidationFailure(failure):
        if hasattr(failure, 'line'):
            line = failure.line
        elif hasattr(failure, 'position'):
            line = failure.position[0]
        else:
            line = None
        if line is None:
            description = 'Problem:'
        else:
            description = 'Problem found on line %d:' % line
        return xml.dt[ description ], xml.dd[ str(failure) ]

    def __init__(self, url):
        Report.__init__(self, url)
        self.notes = []
        self.validationFailures = []
        self.queryWarnings = []

    def addNote(self, message):
        self.notes.append(message)

    def addValidationFailure(self, failure):
        self.validationFailures.append(failure)
        self.ok = False

    def addQueryWarning(self, message):
        self.queryWarnings.append(message)
        self.ok = False

    def present(self, scribe):
        if self.notes:
            yield xml.p[xml.br.join(
                'Note: ' + note
                for note in self.notes
                )]
        if self.validationFailures:
            yield xml.dl[(
                self.__presentValidationFailure(failure)
                for failure in self.validationFailures
                )]
        if self.queryWarnings:
            yield xml.p[ 'Bad queries:' ]
            yield xml.ul[(
                xml.li[ warning ]
                for warning in self.queryWarnings
                )]
        yield Report.present(self, scribe)

class Page(object):

    def __init__(self):
        self.queryToReport = {}
        self.failures = 0

    def addReport(self, report):
        scheme_, host_, path_, query, fragment_ = urlsplit(report.url)
        assert query not in self.queryToReport
        self.queryToReport[query] = report
        if not report.ok:
            self.failures += 1

    def present(self, scribe):
        total = len(self.queryToReport)
        yield xml.p[
            '%d queries checked, %d passed, %d failed'
            % ( total, total - self.failures, self.failures )
            ]
        for query in sorted(self.queryToReport.iterkeys()):
            if query:
                queryStrElem = []
                for queryElem in query.split('&'):
                    key, value = queryElem.split('=')
                    key = unquote_plus(key)
                    value = unquote_plus(value)
                    queryStrElem.append('%s = %s' % (key, value))
                queryStr = ' | '.join(queryStrElem)
            else:
                queryStr = '(no query)'
            report = self.queryToReport[query]
            yield xml.h3(class_ = 'pass' if report.ok else 'fail')[
                xml.a(href = report.url)[ queryStr ]
                ]
            yield report.present(scribe)

class Scribe(object):

    def __init__(self, baseURL, spider, plugins):
        self.baseURL = baseURL
        self.spider = spider
        scheme_, host_, basePath, query, fragment = urlsplit(baseURL)
        assert query == ''
        assert fragment == ''
        self.basePath = basePath = basePath[ : basePath.rindex('/') + 1]

        self.plugins = plugins

        self.reports = {}
        self.pages = {}
        self.reportsByPage = {}

    def __urlToName(self, url):
        path = urlsplit(url).path
        assert path.startswith(self.basePath)
        return path[len(self.basePath) : ]

    def addReport(self, report):
        for plugin in self.plugins:
            plugin.reportAdded(report)

        url = report.url
        # Note: Currently, each URL is only visited once.
        #       Since we do not modify the database, a second fetch would
        #       not lead to different results than the first.
        assert url not in self.reports
        self.reports[url] = report

        pageName = self.__urlToName(url)
        page = self.pages.get(pageName)
        if page is None:
            self.pages[pageName] = page = Page()
        page.addReport(report)

    def getFailedPages(self):
        return [
            page for page in self.pages.itervalues() if page.failures != 0
            ]

    def getSummary(self):
        total = len(self.pages)
        numFailedPages = len(self.getFailedPages())
        return '%d pages checked, %d passed, %d failed' % (
            total, total - numFailedPages, numFailedPages
            )

    def postProcess(self):
        for plugin in self.plugins:
            plugin.postProcess(self)

    def present(self):
        title = 'APE - Automated Page Exerciser'
        yield xml.html[
            xml.head[
                xml.title[ title ],
                xml.style(type = 'text/css')[ styleSheet ]
                ],
            xml.body[
                xml.h1[ title ],
                xml.p[ self.getSummary() ],
                self.presentFailedIndex(),
                ( ( xml.h2[ xml.a(name = name or 'base')[ name or '(base)' ] ],
                    page.present(self) )
                  for name, page in sorted(self.pages.iteritems()) )
                ]
            ]

    def presentFailedIndex(self):
        failedPageNames = [
            name for name, page in self.pages.iteritems() if page.failures != 0
            ]
        if failedPageNames:
            yield xml.p[ 'Failed pages:' ]
            yield xml.ul[(
                xml.li[
                    xml.a(href = '#' + (name or 'base'))[ name or '(base)' ]
                    ]
                for name in sorted(failedPageNames)
                )]

    def presentReferrers(self, request):
        # Note: Currently we only list the pages a request is referred from,
        #       but we know the exact requests.
        pageNames = set()
        for sourceRequest in self.spider.iterReferringRequests(request):
            pageNames.add(self.__urlToName(sourceRequest.pageURL))
        for pageName in sorted(pageNames):
            yield xml.li[ xml.a(href = '#' + pageName)[ pageName ] ]
