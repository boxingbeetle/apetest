# SPDX-License-Identifier: BSD-3-Clause

"""Load documents via HTTP.

`load_page` loads arbitrary resources (as `bytes`).
`load_text` loads and decodes plain text documents.
"""

from email import message_from_string
from io import BytesIO
from logging import getLogger
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import (
    FileHandler, HTTPRedirectHandler, Request as URLRequest, build_opener
)
import re

from apetest.decode import decode_and_report, encoding_from_bom
from apetest.report import FetchFailure, Report
from apetest.version import VERSION_STRING

USER_AGENT_PREFIX = 'APE-Test'
USER_AGENT = f'{USER_AGENT_PREFIX}/{VERSION_STRING}'

_LOG = getLogger(__name__)

class _CustomRedirectHandler(HTTPRedirectHandler):

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(newurl, code, msg, headers, fp)

class _CustomFileHandler(FileHandler):

    def file_open(self, req):
        path = urlsplit(req.full_url).path

        # Drop queries and fragments on local files.
        req.full_url = f'file://{path}'

        try:
            return super().file_open(req)
        except URLError as ex:
            reason = ex.reason
            if isinstance(reason, FileNotFoundError):
                # Report file-not-found as an HTTP 404 status.
                raise HTTPError(
                    req.full_url, 404, str(reason),
                    message_from_string('content-type: text/plain'),
                    BytesIO()
                    )
            elif isinstance(reason, IsADirectoryError):
                # Emulate the way a web server handles directories.
                if path.endswith('/'):
                    req.full_url = f'file://{path}index.html'
                    return self.file_open(req)
                # Redirect to add trailing slash.
                raise HTTPError(
                    req.full_url + '/', 301, 'Path is a directory',
                    message_from_string('content-type: text/plain'),
                    BytesIO()
                    )
            else:
                raise

_URL_OPENER = build_opener(_CustomRedirectHandler, _CustomFileHandler)

def open_page(url, ignore_client_error=False, accept_header='*/*'):
    """Open a connection to retrieve a resource via HTTP `GET`.

    Parameters:

    url
        The URL of the resource to request.
    ignore_client_error
        If `True`, a client error (HTTP status 400) is not reported
        as an error. This is useful to avoid false positives when
        making speculative requests.
    accept_header
        HTTP `Accept` header to use for the request.

    Returns:

    response
        An `http.client.HTTPResponse` object that contains an open
        stream that data can be read from.

    Raises:

    apetest.report.FetchFailure
        If no connection could be opened.
    """

    # TODO: Figure out how to do authentication, "user:password@" in
    #       the URL does not work.
    #       There is support for HTTP basic auth in urllib.
    url_req = URLRequest(url)
    url_req.add_header('Accept', accept_header)
    url_req.add_header('User-Agent', USER_AGENT)
    while True:
        try:
            return _URL_OPENER.open(url_req)
        except HTTPError as ex:
            if ex.code == 503:
                if 'retry-after' in ex.headers:
                    try:
                        seconds = int(ex.headers['retry-after'])
                    except ValueError:
                        # TODO: HTTP spec allows a date string here.
                        _LOG.warning('Parsing of "Retry-After" dates '
                                     'is not yet implemented')
                        seconds = 5
                else:
                    seconds = 5
                _LOG.info('Server not ready yet, trying again '
                          'in %d seconds', seconds)
                sleep(seconds)
            elif 300 <= ex.code < 400:
                # Do not treat redirects as errors.
                return ex
            elif ex.code == 400 and ignore_client_error:
                # Ignore generic client error, because we used a speculative
                # request and 400 can be the correct response to that.
                return ex
            else:
                message = f'HTTP error {ex.code:d}: {ex.msg}'
                raise FetchFailure(url, message, http_error=ex)
        except URLError as ex:
            raise FetchFailure(url, str(ex.reason))
        except OSError as ex:
            raise FetchFailure(url, ex.strerror)

def load_page(url, ignore_client_error=False, accept_header='*/*'):
    """Load the contents of a resource via HTTP `GET`.

    Parameters:

    url
        The URL of the resource to load.
    ignore_client_error
        If `True`, a client error (HTTP status 400) is not reported
        as an error. This is useful to avoid false positives when
        making speculative requests.
    accept_header
        HTTP `Accept` header to use for the request.

    Returns:

    report, response, contents
        `report` is a `apetest.report.Report` instance that may already
        have some messages logged to it.

        `response` is an `http.client.HTTPResponse` object if
        a response was received from the server, or `None` otherwise.

        `contents` is the loaded data as `bytes`, or `None` if
        the loading failed.
    """

    try:
        response = open_page(url, ignore_client_error, accept_header)
    except FetchFailure as failure:
        response = failure.http_error
        if response is None:
            return failure, None, None
        report = failure
    else:
        report = Report(url)

    try:
        content = response.read()
    except OSError as ex:
        _LOG.info('Failed to read "%s" contents: %s', url, ex)
        report.error('Failed to read contents: %s', ex)
        return report, response, None
    else:
        return report, response, content
    finally:
        response.close()

_RE_EOLN = re.compile(r'\r\n|\r|\n')

def load_text(url, accept_header='text/plain'):
    """Load a text document.

    Parameters:

    url
        The URL of the document to load.
    accept_header
        HTTP `Accept` header to use for the request.

    Returns:

    report, response, contents
        `report` is a `apetest.report.Report` instance that may already
        have some messages logged to it.

        `response` is an `http.client.HTTPResponse` object if
        a response was received from the server, or `None` otherwise.

        `contents` is the document as a list of lines, or `None` if
        the loading failed.
    """
    redirect_count = 0
    while True:
        report, response, content_bytes = load_page(
            url, accept_header=accept_header
            )
        if response is not None:
            if response.code in (200, None):
                break
            if response.code in (301, 302, 303, 307):
                redirect_count += 1
                if redirect_count <= 10:
                    # Note: The new URL could be outside our crawl root,
                    #       but since this function is not used for the
                    #       actual crawling, that is fine.
                    url = response.url
                    continue
                report.warning('Redirect limit exceeded')
        return report, response, None

    bom_encoding = encoding_from_bom(content_bytes)
    http_encoding = response.headers.get_content_charset()
    try:
        content, used_encoding_ = decode_and_report(
            content_bytes,
            ((bom_encoding, 'Byte Order Mark'),
             (http_encoding, 'HTTP header')),
            report
            )
    except ValueError as ex:
        report.error('Failed to decode text document: %s', ex)
        return report, response, None
    else:
        return report, response, _RE_EOLN.split(content)
