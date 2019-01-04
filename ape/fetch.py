# SPDX-License-Identifier: BSD-3-Clause

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
        # Emulate the way a web server handles directories.
        path = unquote(urlsplit(url).path)
        if not path.endswith('/') and isdir(path):
            return RedirectResult(url + '/')
        elif path.endswith('/'):
            remove_index = True
            fetch_url = url + 'index.html'
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
