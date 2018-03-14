# SPDX-License-Identifier: BSD-3-Clause

class Spider(object):
    # TODO: Now just the first 100 are checked, it would be better to try
    #       variations of all query arguments.
    maxQueriesPerPage = 100

    def __init__(self, firstRequest):
        self.requestsToCheck = set([firstRequest])
        self.requestsChecked = set()
        self.queriesPerPage = {}
        # Maps source request to referrers (destination).
        self.siteGraph = {}
        # Maps destination page to source requests.
        self.pageReferredFrom = {}

    def __iter__(self):
        while self.requestsToCheck:
            print 'checked: %d, to check: %d' % (
                len(self.requestsChecked), len(self.requestsToCheck)
                )
            request = min(self.requestsToCheck)
            self.requestsToCheck.remove(request)
            self.requestsChecked.add(request)
            yield request

    def addRequests(self, sourceRequest, referrers):
        # Currently each request is only visited once, so we do not have to
        # merge data, but that might change once we start doing POSTs.
        assert sourceRequest not in self.siteGraph
        self.siteGraph[sourceRequest] = referrers

        for referrer in referrers:
            pageURL = referrer.pageURL

            sources = self.pageReferredFrom.get(pageURL)
            if sources is None:
                self.pageReferredFrom[pageURL] = sources = set()
            sources.add(sourceRequest)

            count = self.queriesPerPage.get(pageURL, 0)
            maxQueriesPerPage = self.maxQueriesPerPage
            for request in referrer.iterRequests():
                if request in self.requestsChecked \
                or request in self.requestsToCheck:
                    continue
                if count >= maxQueriesPerPage:
                    print 'maximum number of queries reached for "%s"' % (
                        pageURL
                        )
                    break
                count += 1
                self.requestsToCheck.add(request)
            self.queriesPerPage[pageURL] = count

    def iterReferringRequests(self, destRequest):
        '''Iterate through the requests that refer to the given request.
        '''
        for sourceRequest in self.pageReferredFrom.get(destRequest.pageURL, ()):
            for referrer in self.siteGraph[sourceRequest]:
                if referrer.hasRequest(destRequest):
                    yield sourceRequest
