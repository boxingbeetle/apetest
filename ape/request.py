# SPDX-License-Identifier: BSD-3-Clause

from urllib.parse import quote_plus, unquote_plus, urlsplit, urlunsplit

class Request(object):
    '''A page and arguments combination.
    '''

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
        '''For constructed requests that are not guaranteed to be correct,
        set "maybe_bad" to True. For requests that originate from the user
        or the web app under test, leave "maybe_bad" as False.
        '''
        self.page_url = page_url
        self.query = tuple(sorted(query))
        self.maybe_bad = bool(maybe_bad)

    def __cmp__(self, other):
        if hasattr(other, 'page_url'):
            url_compare = cmp(self.page_url, other.page_url)
            if url_compare:
                return url_compare
            if hasattr(other, 'query'):
                return cmp(self.query, other.query)
        # Uncomparable, return any non-equal.
        return -1

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
