# SPDX-License-Identifier: BSD-3-Clause

"""Home of the L{Request} class."""

from functools import total_ordering
from typing import Iterable, Tuple
from urllib.parse import quote_plus, unquote_plus, urlsplit, urlunsplit


@total_ordering
class Request:
    """
    A resource request consisting of a page URL plus arguments.

    To get the full URL including query, use C{str(request)}.
    """

    @staticmethod
    def from_url(url: str) -> "Request":
        """
        Creates a L{Request} from a URL.

        @raise ValueError:
            If C{url} cannot be represented by a L{Request}
            object because it uses non-standard query syntax.
        """

        scheme, host, path, query_str, fragment_ = urlsplit(url)
        if not path:
            path = "/"
        page_url = urlunsplit((scheme, host, path, "", ""))
        query = []
        if query_str:
            for elem in query_str.split("&"):
                if "=" in elem:
                    key, value = elem.split("=", 1)
                    query.append((unquote_plus(key), unquote_plus(value)))
                else:
                    # Note: This might be valid as a URL, but it does not
                    #       correspond to application/x-www-form-urlencoded,
                    #       which is what a typical web framework will expect
                    #       to receive.
                    raise ValueError(
                        f'Query of URL "{url}" contains invalid part "{elem}"'
                    )
        return Request(page_url, query)

    def __init__(
        self, page_url: str, query: Iterable[Tuple[str, str]], maybe_bad: bool = False
    ):
        """
        Initializes a request object from a split URL.

        @param page_url:
            URL without the query.
        @param query:
            C{(key, value)*}
            The query part of the URL, as a sequence of key-value pairs.
        @param maybe_bad:
            For speculative requests that are not guaranteed to be correct,
            pass C{True}.
            For requests that originate from the user or the web app under
            test, use the C{False} default.
        """

        self.page_url = page_url
        """URL without the query."""

        self.query = tuple(sorted(query))
        """The query part of the URL, as a sequence of key-value pairs."""

        self.maybe_bad = bool(maybe_bad)
        """
        C{True} iff this request is speculative.

        Client errors returned when making speculative requests should not
        be reported as problems of a web app.
        """

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Request):
            return self.page_url == other.page_url and self.query == other.query
        else:
            return NotImplemented

    def __lt__(self, other: object) -> bool:
        if isinstance(other, Request):
            return (self.page_url, self.query) < (other.page_url, other.query)
        else:
            return NotImplemented

    def __hash__(self) -> int:
        return hash(self.page_url) ^ hash(self.query)

    def __str__(self) -> str:
        if self.query:
            return (
                self.page_url
                + "?"
                + "&".join(
                    f"{quote_plus(key)}={quote_plus(value)}"
                    for key, value in self.query
                )
            )
        else:
            return self.page_url
