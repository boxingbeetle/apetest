# SPDX-License-Identifier: BSD-3-Clause

from functools import total_ordering

from urllib.parse import quote_plus, unquote_plus, urlsplit, urlunsplit

@total_ordering
class Request:
    """A page and arguments combination.
    """

    @staticmethod
    def from_url(url):
        scheme, host, path, query_str, fragment_ = urlsplit(url)
        page_url = urlunsplit((scheme, host, path, '', ''))
        query = []
        if query_str:
            for elem in query_str.split('&'):
                if '=' in elem:
                    key, value = elem.split('=', 1)
                    query.append((unquote_plus(key), unquote_plus(value)))
                else:
                    # Note: This might be valid as a URL, but it does not
                    #       correspond to application/x-www-form-urlencoded,
                    #       which is what a typical web framework will expect
                    #       to receive.
                    raise ValueError(
                        'Query of URL "%s" contains invalid part "%s"'
                        % (url, elem)
                        )
        return Request(page_url, query)

    def __init__(self, page_url, query, maybe_bad=False):
        """For constructed requests that are not guaranteed to be correct,
        set "maybe_bad" to True. For requests that originate from the user
        or the web app under test, leave "maybe_bad" as False.
        """
        self.page_url = page_url
        self.query = tuple(sorted(query))
        self.maybe_bad = bool(maybe_bad)

    def __eq__(self, other):
        if isinstance(other, Request):
            return self.page_url == other.page_url and self.query == other.query
        else:
            return NotImplemented

    def __lt__(self, other):
        if isinstance(other, Request):
            return (self.page_url, self.query) < (other.page_url, other.query)
        else:
            return NotImplemented

    def __hash__(self):
        return hash(self.page_url) ^ hash(self.query)

    def __str__(self):
        if self.query:
            return self.page_url + '?' + '&'.join(
                '%s=%s' % (quote_plus(key), quote_plus(value))
                for key, value in self.query
                )
        else:
            return self.page_url
