# SPDX-License-Identifier: BSD-3-Clause

"""Load documents via HTTP.

`load_page` loads arbitrary resources (as `bytes`).
`load_text` loads and decodes plain text documents.

Various functions to decode text are also available,
in particular `decode_and_report` to attempt to decode text using
several encoding options and `encoding_from_bom` to auto-detect
a document's encoding by looking for a Unicode byte-order-marker.
"""

from codecs import (
    BOM_UTF8, BOM_UTF16_BE, BOM_UTF16_LE, BOM_UTF32_BE, BOM_UTF32_LE,
    lookup as lookup_codec
    )
from collections import OrderedDict
from email import message_from_string
from io import BytesIO
from logging import getLogger
from os.path import isdir
import re
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import (
    FileHandler, HTTPRedirectHandler, Request as URLRequest,
    build_opener, url2pathname
    )

from apetest.report import FetchFailure, Report
from apetest.version import VERSION_STRING

USER_AGENT_PREFIX = 'APE-Test'
USER_AGENT = '%s/%s' % (USER_AGENT_PREFIX, VERSION_STRING)

_LOG = getLogger(__name__)

class _CustomRedirectHandler(HTTPRedirectHandler):

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(newurl, code, msg, headers, fp)

class _CustomFileHandler(FileHandler):

    def open_local_file(self, req):
        local_path = url2pathname(urlsplit(req.full_url).path)

        # Emulate the way a web server handles directories.
        if isdir(local_path):
            if local_path.endswith('/'):
                local_path += 'index.html'
            else:
                raise HTTPError(
                    'file://%s/' % local_path, 301, 'Path is a directory',
                    message_from_string('content-type: text/plain'), BytesIO()
                    )

        # Ignore queries and fragments on local files.
        req.full_url = 'file://' + local_path

        try:
            return super().open_local_file(req)
        except URLError as ex:
            # Report file-not-found as an HTTP 404 status.
            reason = ex.reason
            if isinstance(reason, FileNotFoundError):
                raise HTTPError(
                    req.full_url, 404, str(reason),
                    message_from_string('content-type: text/plain'), BytesIO()
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
                message = 'HTTP error %d: %s' % (ex.code, ex.msg)
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
    except IOError as ex:
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
    content, used_encoding_ = decode_and_report(
        content_bytes,
        ((bom_encoding, 'Byte Order Mark'),
         (http_encoding, 'HTTP header')),
        report
        )

    return report, response, _RE_EOLN.split(content)

def encoding_from_bom(data):
    """Look for a byte-order-marker at the start of the given `bytes`.
    If found, return the encoding matching that BOM, otherwise return `None`.
    """
    if data.startswith(BOM_UTF8):
        return 'utf-8'
    elif data.startswith(BOM_UTF16_LE) or data.startswith(BOM_UTF16_BE):
        return 'utf-16'
    elif data.startswith(BOM_UTF32_LE) or data.startswith(BOM_UTF32_BE):
        return 'utf-32'
    else:
        return None

def standard_codec_name(codec):
    """Map a codec name to the preferred standardized version."""
    name = codec.name
    return {
        # IANA prefers "US-ASCII".
        #   http://www.iana.org/assignments/character-sets/character-sets.xhtml
        'ascii': 'us-ascii',
        }.get(name, name)

def try_decode(data, encodings):
    """Attempt to decode text using the given encodings in order.

    Parameters:

    data: bytes
        Encoded version of the text.
    encodings: (encoding | None)*
        Names of the encodings to try.
        Duplicate and `None` entries are skipped.

    Returns:

    text, encoding
        The decoded string and the encoding used to decode it.

    Raises:

    UnicodeDecodeError
        If the text could not be decoded.
    """

    # Build sequence of codecs to try.
    codecs = OrderedDict()
    for encoding in encodings:
        if encoding is not None:
            try:
                codec = lookup_codec(encoding)
            except LookupError:
                pass
            else:
                codecs[standard_codec_name(codec)] = codec

    # Apply decoders to the document.
    for name, codec in codecs.items():
        try:
            text, consumed = codec.decode(data, 'strict')
        except UnicodeDecodeError:
            continue
        if consumed == len(data):
            return text, name
    raise UnicodeDecodeError(
        'Unable to determine document encoding; tried: '
        + ', '.join(codecs.keys())
        )

def decode_and_report(data, encoding_options, report):
    """Attempt to decode text using several encoding options in order.

    Parameters:

    data: bytes
        Encoded version of the text.
    encoding_options: (encoding | None, source)*
        Each option is a pair of encoding name and a description of
        where this encoding suggestion originated.
        If the encoding name is `None`, the option is skipped.
    report
        Non-fatal problems are logged here.
        Such problems include an unknown or differing encodings
        among the options.

    Returns:

    text, encoding
        The decoded string and the encoding used to decode it.

    Raises:

    UnicodeDecodeError
        If the text could not be decoded.
    """

    encodings = [encoding for encoding, source in encoding_options]
    # Always try to decode as UTF-8, since that is the most common encoding
    # these days, plus it's a superset of ASCII so it also works for old or
    # simple documents.
    encodings.append('utf-8')
    text, used_encoding = try_decode(data, encodings)

    # Report differences between suggested encodings and the one we
    # settled on.
    for encoding, source in encoding_options:
        if encoding is None:
            continue

        try:
            codec = lookup_codec(encoding)
        except LookupError:
            report.warning(
                '%s specifies encoding "%s", which is unknown to Python',
                source, encoding
                )
            continue

        std_name = standard_codec_name(codec)
        if std_name != used_encoding:
            report.warning(
                '%s specifies encoding "%s", '
                'while actual encoding seems to be "%s"',
                source, encoding, used_encoding
                )
        elif std_name != encoding:
            report.info(
                '%s specifies encoding "%s", '
                'which is not the standard name "%s"',
                source, encoding, used_encoding
                )

    return text, used_encoding
