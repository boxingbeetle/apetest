# SPDX-License-Identifier: BSD-3-Clause

"""Keeps track of links between pages.

Use `spider_req` to create a `Spider`, then iterate through it to receive
new requests to check and call `Spider.add_requests` to add links you found
while checking.

At any point during or after the crawling, `Spider.iter_referring_requests`
can be used to ask which other requests linked to a given request.
"""

from collections import defaultdict
from urllib.parse import urljoin, urlsplit

from apetest.fetch import USER_AGENT_PREFIX, load_text
from apetest.robots import (
    lookup_robots_rules, parse_robots_txt, path_allowed, scan_robots_txt
    )

class Spider:
    """Web crawler that remembers which requests have been discovered,
    which have been checked and the links between them.

    Instances of this class are iterable. Every request yielded is
    automatically marked as visited. It is valid to add new requests
    while iterating.
    """

    max_queries_per_page = 100
    """Maximum number of queries to generate with the same path.

    For pages with many arguments, the number of possible queries can
    become so large that it not feasible to check them all.
    """
    # TODO: Currently just the first 100 are checked, it would be better
    #       to try variations of all query arguments.

    def __init__(self, first_req, rules):
        """Initializes a spider that starts at `first_req` and follows
        the given exclusion rules.

        In most cases, you should use `spider_req` instead.
        """
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
        """Returns `True` iff this spider is allowed to visit the resources
        referenced by `referrer`.
        """
        # TODO: Currently the 'checker' module rejects out-of-scope URLs,
        #       but it would be cleaner to do that at the spider level,
        #       in case we ever want to support crawling multiple roots
        #       or want to report all external links.
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
        """Adds the requests from `referrers`, which were discovered
        in `source_req`.

        Added requests that were not discovered before are registered
        as to be checked. The spider also remembers that `source_req`
        links to the added requests.
        """

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
        """Iterates through the requests that refer to the given request.
        """
        for source_req in self._page_referred_from[dest_req.page_url]:
            for referrer in self._site_graph[source_req]:
                if referrer.has_request(dest_req):
                    yield source_req

def spider_req(first_req):
    """Creates a `Spider` that starts at the given `apetest.request.Request`.

    This function will attempt to read `robots.txt` from the server
    or base directory contained in `first_req`. Any rules found there
    that apply to APE will be passed on to the new `Spider`.
    """
    base_url = first_req.page_url
    if base_url.startswith('file:'):
        robots_url = urljoin(base_url, 'robots.txt')
    else:
        robots_url = urljoin(base_url, '/robots.txt')

    print('fetching "robots.txt"...')
    report, response, robots_lines = load_text(robots_url)
    if robots_lines is None:
        if response is not None and response.code == 404:
            # It is not an error if "robots.txt" does not exist.
            print('no "robots.txt" was found')
            report = None
        rules = []
    else:
        robots_records = scan_robots_txt(robots_lines, report)
        rules_map = parse_robots_txt(robots_records, report)
        rules = lookup_robots_rules(rules_map, USER_AGENT_PREFIX)
        report.checked = True

    return Spider(first_req, rules), report
