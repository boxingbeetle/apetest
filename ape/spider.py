# SPDX-License-Identifier: BSD-3-Clause

from collections import defaultdict
from urllib.parse import urljoin, urlsplit

from ape.fetch import USER_AGENT_PREFIX, load_text
from ape.robots import (
    lookup_robots_rules, parse_robots_txt, path_allowed, scan_robots_txt
    )

class Spider:
    # TODO: Now just the first 100 are checked, it would be better to try
    #       variations of all query arguments.
    max_queries_per_page = 100

    def __init__(self, first_req, rules):
        self._base_url = first_req.page_url
        self._rules = rules
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

    def referrer_allowed(self, referrer):
        """Returns True iff this spider is allowed to visit the resources
        referenced by `referrer`.
        TODO: Currently the `checker` module rejects out-of-scope URLs,
              but it would be cleaner to do that at the spider level,
              in case we ever want to support crawling multiple roots
              or want to report all external links.
        """
        path = urlsplit(referrer.page_url).path or '/'
        base_url = self._base_url
        if base_url.startswith('file:'):
            base_path = urlsplit(base_url).path or '/'
            if not path.startswith(base_path):
                # Path is outside the tree rooted at our base URL.
                return False
            path = path[base_path.rindex('/'):]

        return path_allowed(path, self._rules)

    def add_requests(self, source_req, referrers):
        # Filter referrers according to rules.
        allowed_referrers = [
            referrer
            for referrer in referrers
            if self.referrer_allowed(referrer)
            ]

        # Currently each request is only visited once, so we do not have to
        # merge data, but that might change once we start doing POSTs.
        assert source_req not in self._site_graph
        self._site_graph[source_req] = allowed_referrers

        for referrer in allowed_referrers:
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
        for source_req in self._page_referred_from[dest_req.page_url]:
            for referrer in self._site_graph[source_req]:
                if referrer.has_request(dest_req):
                    yield source_req

def spider_req(first_req):
    """Creates a spider for the given request.
    Will use information from robots.txt if available.
    """
    base_url = first_req.page_url
    if base_url.startswith('file:'):
        robots_url = urljoin(base_url, 'robots.txt')
    else:
        robots_url = urljoin(base_url, '/robots.txt')

    print('fetching "robots.txt"...')
    report, robots_lines = load_text(robots_url)
    if robots_lines is None:
        rules = []
    else:
        robots_records = scan_robots_txt(robots_lines, report)
        rules_map = parse_robots_txt(robots_records, report)
        rules = lookup_robots_rules(rules_map, USER_AGENT_PREFIX)
        report.checked = True

    return Spider(first_req, rules), report
