# SPDX-License-Identifier: BSD-3-Clause

from codecs import (
    BOM_UTF8, BOM_UTF16_BE, BOM_UTF16_LE, BOM_UTF32_BE, BOM_UTF32_LE,
    lookup as lookup_codec
    )
from collections import OrderedDict
from logging import getLogger
from os.path import isdir
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlsplit
from urllib.request import Request as URLRequest, urlopen

from ape.report import FetchFailure
from ape.version import VERSION_STRING

USER_AGENT = 'APE/%s' % VERSION_STRING

_LOG = getLogger(__name__)

class RedirectResult:
    '''Fake HTTP result object that represents a redirection.
    Only the members we use are implemented.
    '''

    def __init__(self, url):
        self.url = url

def open_page(request, accept_header='*/*'):
    """Opens a connection to retrieve a requested page.
    Returns an open input stream on success.
    Raises FetchFailure on errors.
    """
    url = str(request)
    fetch_url = url
    remove_index = False
    if url.startswith('file:'):
        # Ignore queries and fragments on local files.
        url_parts = urlsplit(url)
        fetch_url = 'file://' + url_parts.path

        # Emulate the way a web server handles directories.
        path = unquote(url_parts.path)
        if not path.endswith('/') and isdir(path):
            return RedirectResult(url + '/')
        elif path.endswith('/'):
            remove_index = True
            fetch_url += 'index.html'

    # TODO: Figure out how to do authentication, "user:password@" in
    #       the URL does not work.
    url_req = URLRequest(fetch_url)
    url_req.add_header('Accept', accept_header)
    url_req.add_header('User-Agent', USER_AGENT)
    while True:
        try:
            result = urlopen(url_req)
            if remove_index:
                result.url = url
            return result
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
            elif ex.code == 400:
                # Generic client error, could be because we submitted an
                # invalid form value.
                _LOG.info('Bad request (HTTP error 400): %s', ex.msg)
                if request.maybe_bad:
                    # Validate the error page body.
                    return ex
                else:
                    raise FetchFailure(
                        url, 'Bad request (HTTP error 400): %s' % ex.msg,
                        http_status=ex.code
                        )
            else:
                raise FetchFailure(
                    url, 'HTTP error %d: %s' % (ex.code, ex.msg),
                    http_status=ex.code
                    )
        except URLError as ex:
            raise FetchFailure(url, str(ex.reason))
        except OSError as ex:
            raise FetchFailure(url, ex.strerror)

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
