# SPDX-License-Identifier: BSD-3-Clause

"""
Client for using the web service of the Nu Html Checker (v.Nu).

L{VNUClient} can connect to the checker web service and have it process one
or more requests.

You can find the checker itself at U{https://validator.github.io/}.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from gzip import GzipFile
from http.client import HTTPConnection, HTTPException, HTTPResponse
from io import BytesIO
from logging import getLogger
from time import sleep
from types import TracebackType
from typing import Any, cast
from urllib.parse import urlsplit

https_connection_factory: type[HTTPConnection] | None
try:
    from http.client import HTTPSConnection  # pylint: disable=ungrouped-imports

    https_connection_factory = HTTPSConnection  # pylint: disable=invalid-name
except ImportError:
    https_connection_factory = None  # pylint: disable=invalid-name


_LOG = getLogger(__name__)


class RedirectError(HTTPException):
    """Raised when a redirect status from the service cannot be handled."""

    @property
    def msg(self) -> str:
        """Error message."""
        # PyLint mistakenly thinks 'args' is not subscriptable.
        #   https://github.com/PyCQA/pylint/issues/2333
        return cast(str, self.args[0])  # pylint: disable=unsubscriptable-object

    @property
    def url(self) -> str:
        """URL that we were redirected from."""
        return cast(str, self.args[1])  # pylint: disable=unsubscriptable-object

    def __init__(self, msg: str, url: str):
        # pylint: disable=useless-super-delegation
        #   https://github.com/PyCQA/pylint/issues/2270
        super().__init__(msg, url)

    def __str__(self) -> str:
        return "%s at %s" % self.args


class RequestFailed(HTTPException):
    """Raised when a response has a non-successful status code."""

    @property
    def msg(self) -> str:
        """Error message."""
        return cast(str, self.args[0])  # pylint: disable=unsubscriptable-object

    @property
    def status(self) -> int:
        """HTTP status code."""
        return cast(int, self.args[1])  # pylint: disable=unsubscriptable-object

    def __init__(self, response: HTTPResponse):
        super().__init__(response.reason, response.status)

    def __str__(self) -> str:
        return "%s (%d)" % self.args


class VNUClient:
    """
    Manages a connection to the checker web service.

    A connection will be opened on demand but has to be closed explicitly,
    either by calling the L{close} method or by using the client object
    as the context manager in a C{with} statement.
    A client with a closed connection can be used again: the connection
    will be re-opened.
    """

    def __init__(self, url: str):
        """Initializes a client that connects to the v.Nu checker at C{url}."""
        self.service_url = url
        self._connection: HTTPConnection | None = None
        self._remote: tuple[str, str] | None = None

    def __enter__(self) -> VNUClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def __connect(self, url: str) -> HTTPConnection:
        """
        Returns an HTTPConnection instance for the given URL string.
        Raises InvalidURL if the URL string cannot be parsed.
        Raises OSError if the URL uses an unsupported scheme.
        """
        url_parts = urlsplit(url)
        scheme = url_parts.scheme
        netloc = url_parts.netloc

        if self._connection:
            if self._remote == (scheme, netloc):
                # Re-use existing connection.
                return self._connection
            else:
                self.close()

        if scheme == "http":
            connection_factory = HTTPConnection
        elif scheme == "https" and https_connection_factory:
            connection_factory = https_connection_factory
        elif scheme:
            raise OSError(f"Unsupported URL scheme: {scheme}")
        else:
            raise OSError(f'URL "{url}" lacks a scheme (such as "http:")')

        self._connection = connection = connection_factory(netloc)
        self._remote = (scheme, netloc)

        return connection

    def close(self) -> None:
        """
        Closes the current connection.

        Does nothing if there is no open connection.
        """
        if self._connection:
            self._connection.close()
            self._connection = None
            self._remote = None

    def __request_with_retries(
        self, url: str, data: bytes, content_type: str
    ) -> tuple[HTTPResponse, bytes | None]:
        """
        Make a request and retry if it doesn't succeed the first time.
        For example, the connection may have timed out.
        Returns a pair consisting of the closed response object (containing
        status and headers) and the response body (or None if unsuccessful).
        """
        url_parts = urlsplit(url)
        request = url_parts.path or "/"
        if url_parts.query:
            request += "?" + url_parts.query

        headers = {
            "Content-Type": content_type,
            "User-Agent": "vnuclient.py/1.0",
        }

        # Compression is worthwhile when using an actual network.
        if url_parts.hostname not in ("localhost", "127.0.0.1", "::1"):
            headers["Accept-Encoding"] = "gzip"
            headers["Content-Encoding"] = "gzip"
            with BytesIO() as buf:
                with GzipFile(None, "wb", 6, buf) as zfile:
                    zfile.write(data)
                body = buf.getvalue()
        else:
            headers["Accept-Encoding"] = "identity, gzip;q=0.5"
            body = data

        refused_count = 0
        retry_count = 0
        while True:
            try:
                connection = self.__connect(url)
                connection.request("POST", request, body, headers)
                response = connection.getresponse()

                response_body: bytes | None
                status = response.status
                if status == 200:
                    if response.getheader("Content-Encoding", "identity").lower() in (
                        "gzip",
                        "x-gzip",
                    ):
                        with GzipFile(fileobj=response) as zfile:
                            response_body = zfile.read()
                    else:
                        response_body = response.read()
                else:
                    response_body = None

                response.close()
                return response, response_body
            except ConnectionRefusedError:
                self.close()
                refused_count += 1
                if refused_count >= 20:
                    # Service is unlikely to appear anymore; give up.
                    raise
                # Wait for service to start up.
                _LOG.info("v.Nu service refuses connection; trying again in 1 second")
                sleep(1)
            except (HTTPException, OSError):
                self.close()
                retry_count += 1
                if retry_count >= 3:
                    # Problem is probably not transient; give up.
                    raise

    def __request_with_redirects(self, url: str, data: bytes, content_type: str) -> str:
        """
        Makes an HTTP request to the checker service.
        Returns the reply body as a string.
        """
        redirect_count = 0
        while True:
            response, body = self.__request_with_retries(url, data, content_type)

            status = response.status
            if status == 200:
                charset = response.msg.get_content_charset("utf-8")
                assert body is not None
                return body.decode(charset)
            elif status in (301, 302, 307):
                # Note: RFC 7231 states that we MAY handle redirects
                #       automatically, unlike the obsolete RFC 2616.

                # Find new URL.
                new_url = response.getheader("Location")
                if new_url is None:
                    raise RedirectError(f"Redirect ({status:d}) without Location", url)
                if new_url == url:
                    raise RedirectError("Redirect loop", url)
                url = new_url

                # Guard against infinite or excessive redirect chains.
                redirect_count += 1
                if redirect_count > 12:
                    raise RedirectError("Maximum redirect count exceeded", url)
            else:
                raise RequestFailed(response)

    def request(
        self, data: bytes, content_type: str, errors_only: bool = False
    ) -> Iterator[Mapping[str, Any]]:
        """
        Feeds the given document to the checker.

        @param data:
            Document to check, as C{bytes}.
        @param content_type:
            Media type for the document.
            This string is sent as the value for the HTTP C{Content-Type}
            header, so it can also include encoding information,
            for example C{"text/html; charset=utf-8"}.
        @param errors_only:
            When C{True}, the checker returns only errors and no warnings
            or informational messages.
        @return: Yields message objects (mappings) as described in
            U{the checker's JSON output format
            <https://github.com/validator/validator/wiki/Output-»-JSON>}.
        @raise OSError:
            When an unrecoverable low-level I/O error occurs.
        @raise HTTPException:
            When an unrecoverable HTTP error occurs.
        @raise ValueError:
            When the response body could not be decoded or parsed.
        """
        url = self.service_url + "?out=json"
        if errors_only:
            url += "&level=error"

        reply_str = self.__request_with_redirects(url, data, content_type)
        reply = json.loads(reply_str)
        yield from reply["messages"]
