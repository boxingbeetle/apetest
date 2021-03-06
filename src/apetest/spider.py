# SPDX-License-Identifier: BSD-3-Clause

"""Keeps track of links between pages.

Use L{spider_req} to create a L{Spider}, then iterate through it to receive
new requests to check and call the L{add_requests} method to add links you found
while checking.

At any point during or after the crawling, the L{iter_referring_requests}
method can be used to ask which other requests linked to a given request.
"""

from collections import defaultdict
from typing import (
    DefaultDict, Dict, Iterable, Iterator, List, Optional, Set, Tuple
)
from urllib.parse import urljoin, urlsplit

from apetest.fetch import USER_AGENT_PREFIX, load_text
from apetest.referrer import Referrer
from apetest.report import Checked, Report
from apetest.request import Request
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

    def __init__(self, first_req: Request, rules: Iterable[Tuple[bool, str]]):
        """Initializes a spider that starts at C{first_req} and follows
        the given exclusion rules.

        In most cases, you should use L{spider_req()} instead.
        """
        self._base_url = first_req.page_url
        self._rules = rules
        self._requests_to_check = {first_req}
        self._requests_checked: Set[Request] = set()
        self._queries_per_page: DefaultDict[str, int] = defaultdict(int)
        # Maps source request to referrers (destination).
        self._site_graph: Dict[Request, List[Referrer]] = {}
        # Maps destination page to source requests.
        self._page_referred_from: DefaultDict[str, Set[Request]] \
                                = defaultdict(set)

    def __iter__(self) -> Iterator[Request]:
        checked = self._requests_checked
        to_check = self._requests_to_check
        while to_check:
            print(f'checked: {len(checked):d}, to check: {len(to_check):d}')
            request = min(to_check)
            to_check.remove(request)
            checked.add(request)
            yield request

    def referrer_allowed(self, referrer: Referrer) -> bool:
        """Returns C{True} iff this spider is allowed to visit the resources
        referenced by C{referrer}.
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

    def add_requests(
            self,
            source_req: Request,
            referrers: Iterable[Referrer]
        ) -> None:
        """Adds the requests from C{referrers}, which were discovered
        in C{source_req}.

        Added requests that were not discovered before are registered
        as to be checked. The spider also remembers that C{source_req}
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
                    print(f'maximum number of queries reached for "{url}"')
                    break
                self._queries_per_page[url] += 1
                self._requests_to_check.add(request)

    def iter_referring_requests(self, dest_req: Request) -> Iterator[Request]:
        """Iterates through the requests that refer to the given request."""
        for source_req in self._page_referred_from[dest_req.page_url]:
            for referrer in self._site_graph[source_req]:
                if referrer.has_request(dest_req):
                    yield source_req

def spider_req(first_req: Request) -> Tuple[Spider, Optional[Report]]:
    """Creates a L{Spider} that starts at the given L{Request}.

    This function will attempt to read C{robots.txt} from the server
    or base directory contained in C{first_req}. Any rules found there
    that apply to APE will be passed on to the new L{Spider}.
    """
    base_url = first_req.page_url
    if base_url.startswith('file:'):
        robots_url = urljoin(base_url, 'robots.txt')
    else:
        robots_url = urljoin(base_url, '/robots.txt')

    print('fetching "robots.txt"...')
    report: Optional[Report]
    rules: Iterable[Tuple[bool, str]]
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
        report.checked = Checked.CHECKED

    return Spider(first_req, rules), report
