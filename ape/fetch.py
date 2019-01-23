# SPDX-License-Identifier: BSD-3-Clause

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

from ape.report import FetchFailure, IncrementalReport
from ape.version import VERSION_STRING

USER_AGENT_PREFIX = 'APE-Test'
USER_AGENT = '%s/%s' % (USER_AGENT_PREFIX, VERSION_STRING)

_LOG = getLogger(__name__)

class CustomRedirectHandler(HTTPRedirectHandler):

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HTTPError(newurl, code, msg, headers, fp)

class CustomFileHandler(FileHandler):

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
        return super().open_local_file(req)

_URL_OPENER = build_opener(CustomRedirectHandler, CustomFileHandler)

def open_page(url, ignore_client_error=False, accept_header='*/*'):
    """Opens a connection to retrieve a requested page.
    Returns a response object wrapping an open input stream on success.
    Raises FetchFailure on errors.
    """
    # TODO: Figure out how to do authentication, "user:password@" in
    #       the URL does not work.
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
    """Loads the contents of a resource.
    Returns a report, the response object and the contents (bytes),
    or None instead of the response object and/or the contents
    if the resource could not be retrieved; in this case errors were
    logged to the report.
    """
    try:
        response = open_page(url, ignore_client_error, accept_header)
    except FetchFailure as failure:
        response = failure.http_error
        if response is None:
            return failure, None, None
        report = failure
    else:
        report = IncrementalReport(url)

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
    """Loads a text document.
    Returns a report and the contents (list with one string per line),
    or None instead of contents if the resource could not be retrieved.
    """
    report, response, content_bytes = load_page(
        url, accept_header=accept_header
        )
    if content_bytes is None:
        return report, None

    bom_encoding = encoding_from_bom(content_bytes)
    http_encoding = response.headers.get_content_charset()
    content, used_encoding_ = decode_and_report(
        content_bytes,
        ((bom_encoding, 'Byte Order Mark'),
         (http_encoding, 'HTTP header')),
        report
        )

    return report, _RE_EOLN.split(content)

def encoding_from_bom(data):
    """Looks for a byte-order-marker at the start of the given bytes.
    If found, return the encoding matching that BOM, otherwise return None.
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
    """Maps codec name to the preferred standardized version.
    """
    name = codec.name
    return {
        # IANA prefers "US-ASCII".
        #   http://www.iana.org/assignments/character-sets/character-sets.xhtml
        'ascii': 'us-ascii',
        }.get(name, name)

def try_decode(data, encodings):
    """Attempts to decode the given bytes using the given encodings in order.
    Duplicate and None encoding elements are skipped.
    Returns a pair of the decoded string and the used encoding if successful,
    otherwise raises UnicodeDecodeError.
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
    """Attempts to decode the given bytes using the given encoding options
    in order. Each option is a pair of encoding name or None and a description
    of where this encoding suggestion originated.
    Returns the decoded string and the encoding used to decode it.
    Raises UnicodeDecodeError if the data could not be decoded.
    Non-fatal problems are added to the report.
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
