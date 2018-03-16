# SPDX-License-Identifier: BSD-3-Clause

from collections import defaultdict

class Spider(object):
    # TODO: Now just the first 100 are checked, it would be better to try
    #       variations of all query arguments.
    max_queries_per_page = 100

    def __init__(self, first_req):
        self._requests_to_check = set([first_req])
        self._requests_checked = set()
        self._queries_per_page = defaultdict(int)
        # Maps source request to referrers (destination).
        self._site_graph = {}
        # Maps destination page to source requests.
        self._page_referred_from = defaultdict(set)

    def __iter__(self):
        checked = self._requests_checked
        to_check = self._requests_to_check
        while to_check:
            print('checked: %d, to check: %d' % (len(checked), len(to_check)))
            request = min(to_check)
            to_check.remove(request)
            checked.add(request)
            yield request

    def add_requests(self, source_req, referrers):
        # Currently each request is only visited once, so we do not have to
        # merge data, but that might change once we start doing POSTs.
        assert source_req not in self._site_graph
        self._site_graph[source_req] = referrers

        for referrer in referrers:
            url = referrer.page_url
            self._page_referred_from[url].add(source_req)

            for request in referrer.iter_requests():
                if request in self._requests_checked \
                or request in self._requests_to_check:
                    continue
                if self._queries_per_page[url] >= self.max_queries_per_page:
                    print('maximum number of queries reached for "%s"' % url)
                    break
                self._queries_per_page[url] += 1
                self._requests_to_check.add(request)

    def iter_referring_requests(self, dest_req):
        '''Iterate through the requests that refer to the given request.
        '''
        for source_req in self._page_referred_from[dest_req]:
            for referrer in self._site_graph[source_req]:
                if referrer.has_request(dest_req):
                    yield source_req
