# SPDX-License-Identifier: BSD-3-Clause

from urllib import quote_plus, unquote_plus
from urlparse import urlsplit, urlunsplit

class Request(object):
    '''A page and arguments combination.
    '''

    @staticmethod
    def fromURL(url):
        scheme, host, path, queryStr, fragment_ = urlsplit(url)
        pageURL = urlunsplit((scheme, host, path, '', ''))
        query = []
        if queryStr:
            for elem in queryStr.split('&'):
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
        return Request(pageURL, query)

    def __init__(self, pageURL, query, maybeBad=False):
        '''For constructed requests that are not guaranteed to be correct,
        set "maybeBad" to True. For requests that originate from the user
        or the web app under test, leave "maybeBad" as False.
        '''
        self.pageURL = pageURL
        self.query = tuple(sorted(query))
        self.maybeBad = maybeBad

    def __cmp__(self, other):
        if hasattr(other, 'pageURL'):
            urlCompare = cmp(self.pageURL, other.pageURL)
            if urlCompare:
                return urlCompare
            if hasattr(other, 'query'):
                return cmp(self.query, other.query)
        # Uncomparable, return any non-equal.
        return -1

    def __hash__(self):
        return hash(self.pageURL) ^ hash(self.query)

    def __str__(self):
        if self.query:
            return self.pageURL + '?' + '&'.join(
                '%s=%s' % (quote_plus(key), quote_plus(value))
                for key, value in self.query
                )
        else:
            return self.pageURL
