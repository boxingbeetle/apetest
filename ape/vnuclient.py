# SPDX-License-Identifier: BSD-3-Clause

from gzip import GzipFile
from http.client import HTTPConnection, HTTPException, UnknownProtocol
try:
    from http.client import HTTPSConnection
except ImportError:
    HTTPSConnection = None
from io import BytesIO
from urllib.parse import urlsplit

import json

class RedirectError(HTTPException):
    '''Raised when a redirect status from the server cannot be handled.
    '''

    msg = property(lambda self: self.args[0])
    url = property(lambda self: self.args[1])

    def __init__(self, msg, url):
        # pylint: disable=useless-super-delegation
        #   https://github.com/PyCQA/pylint/issues/2270
        super().__init__(msg, url)

    def __str__(self):
        return '%s at %s' % self.args

class RequestFailed(HTTPException):
    '''Raised when a response has a non-successful status code.
    '''

    msg = property(lambda self: self.args[0])
    status = property(lambda self: self.args[1])

    def __init__(self, response):
        super().__init__(response.reason, response.status)

    def __str__(self):
        return '%s (%d)' % self.args

class VNUClient:
    '''Manages a connection to the checker web service.
    A connection will be opened on demand but has to be closed explicitly,
    either by calling the `close()` method or using the client object as
    the context manager in a `with` statement.
    A client with a closed connection can be used again: the connection
    will be re-opened.
    '''

    def __init__(self, url):
        self.service_url = url
        self._connection = None
        self._remote = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()

    def __connect(self, url):
        '''Returns an HTTPConnection instance for the given URL string.
        Raises UnknownProtocol if the URL uses an unsupported scheme.
        Raises InvalidURL if the URL contains a bad port.
        '''
        url_parts = urlsplit(url)
        scheme = url_parts.scheme
        netloc = url_parts.netloc

        if self._connection:
            if self._remote == (scheme, netloc):
                # Re-use existing connection.
                return self._connection
            else:
                self.close()

        if scheme == 'http':
            connection_factory = HTTPConnection
        elif scheme == 'https' and HTTPSConnection:
            connection_factory = HTTPSConnection
        else:
            raise UnknownProtocol(scheme)

        self._connection = connection = connection_factory(netloc)
        self._remote = (scheme, netloc)

        return connection

    def close(self):
        '''Closes the current connection.
        Does nothing if there is no open connection.
        '''
        if self._connection:
            self._connection.close()
            self._connection = None
            self._remote = None

    def __request_with_retries(self, url, data, content_type):
        '''Make a request and retry if it doesn't succeed the first time.
        For example, the connection may have timed out.
        Returns a pair consisting of the closed response object (containing
        status and headers) and the response body (or None if unsuccessful).
        '''
        url_parts = urlsplit(url)
        request = url_parts.path or '/'
        if url_parts.query:
            request += '?' + url_parts.query

        headers = {
            'Content-Type': content_type,
            'User-Agent': 'vnuclient.py/1.0',
            }

        # Compression is worthwhile when using an actual network.
        if url_parts.hostname not in ('localhost', '127.0.0.1', '::1'):
            headers['Accept-Encoding'] = 'gzip'
            headers['Content-Encoding'] = 'gzip'
            with BytesIO() as buf:
                with GzipFile(None, 'wb', 6, buf) as zfile:
                    zfile.write(data)
                body = buf.getvalue()
        else:
            headers['Accept-Encoding'] = 'identity, gzip;q=0.5'
            body = data

        retry_count = 0
        while True:
            try:
                connection = self.__connect(url)
                connection.request('POST', request, body, headers)
                response = connection.getresponse()

                status = response.status
                if status == 200:
                    if response.getheader('Content-Encoding', 'identity'
                                         ).lower() in ('gzip', 'x-gzip'):
                        with GzipFile(fileobj=response) as zfile:
                            response_body = zfile.read()
                    else:
                        response_body = response.read()
                else:
                    response_body = None

                response.close()
                return response, response_body
            except (HTTPException, OSError):
                self.close()
                retry_count += 1
                if retry_count >= 3:
                    # Problem is probably not transient; give up.
                    raise

    def __request_with_redirects(self, url, data, content_type):
        '''Makes an HTTP request to the checker service.
        Returns the reply body as a string.
        '''
        redirect_count = 0
        while True:
            response, body = self.__request_with_retries(
                url, data, content_type)

            status = response.status
            if status == 200:
                charset = response.msg.get_content_charset('utf-8')
                return body.decode(charset)
            elif status in (301, 302, 307):
                # Note: RFC 7231 states that we MAY handle redirects
                #       automatically, unlike the obsolete RFC 2616.

                # Find new URL.
                new_url = response.getheader('Location')
                if new_url is None:
                    raise RedirectError(
                        'Redirect (%d) without Location' % status, url
                        )
                if new_url == url:
                    raise RedirectError('Redirect loop', url)
                url = new_url

                # Guard against infinite or excessive redirect chains.
                redirect_count += 1
                if redirect_count > 12:
                    raise RedirectError('Maximum redirect count exceeded', url)
            else:
                raise RequestFailed(response)

    def request(self, data, content_type, errors_only=False):
        '''Feeds the given data to the checker.
        Yields message dictionaries, as described in the checker's
        JSON output format.
        Raises OSError when an unrecoverable low-level I/O error occurs.
        Raises HTTPException when an unrecoverable HTTP error occurs.
        Raises ValueError when the response body could not be decoded
        or parsed.
        '''
        url = self.service_url + '?out=json'
        if errors_only:
            url += '&level=error'

        reply_str = self.__request_with_redirects(url, data, content_type)
        reply = json.loads(reply_str)
        yield from reply['messages']
