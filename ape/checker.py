# SPDX-License-Identifier: BSD-3-Clause

from codecs import (
    BOM_UTF8, BOM_UTF16_BE, BOM_UTF16_LE, BOM_UTF32_BE, BOM_UTF32_LE,
    getdecoder
    )
from collections import defaultdict
from copy import deepcopy
from logging import getLogger
from os.path import isdir
import re
from time import sleep
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit
from urllib.request import Request as URLRequest, urlopen

from lxml import etree

from ape.control import (
    Checkbox, FileInput, HiddenInput, RadioButton, RadioButtonGroup,
    SelectSingle, SelectMultiple, SubmitButton, SubmitButtons,
    TextArea, TextField
    )
from ape.referrer import Form, LinkSet, Redirect
from ape.report import FetchFailure, IncrementalReport
from ape.request import Request

_LOG = getLogger(__name__)

def encoding_from_bom(data):
    '''Looks for a byte-order-marker at the start of the given bytes.
    If found, return the encoding matching that BOM, otherwise return None.
    '''
    if data.startswith(BOM_UTF8):
        return 'utf-8'
    elif data.startswith(BOM_UTF16_LE) or data.startswith(BOM_UTF16_BE):
        return 'utf-16'
    elif data.startswith(BOM_UTF32_LE) or data.startswith(BOM_UTF32_BE):
        return 'utf-32'
    else:
        return None

def strict_decode(data, encoding):
    '''Attempts to decode the given bytes using the given encoding name.
    Returns the decoded string if it decoded flawlessly, None otherwise.
    '''
    try:
        decoder = getdecoder(encoding)
    except LookupError:
        return None
    try:
        text, consumed = decoder(data, 'strict')
    except UnicodeDecodeError:
        return None
    if consumed == len(data):
        return text
    else:
        return None

_RE_XML_DECL = re.compile(
    r'<\?xml([ \t\r\n\'"\w.\-=]*).*\?>'
    )
_RE_XML_DECL_ATTR = re.compile(
    r'[ \t\r\n]+([a-z]+)[ \t\r\n]*=[ \t\r\n]*'
    r'(?P<quote>[\'"])([\w.\-]*)(?P=quote)'
    )

def strip_xml_decl(text):
    '''Strips the XML declaration from the start of the given text.
    Returns the given text without XML declaration, or the unmodified text if
    no XML declaration was found.
    '''
    match = _RE_XML_DECL.match(text)
    return text if match is None else text[match.end():]

def encoding_from_xml_decl(text):
    '''Looks for an XML declaration with an "encoding" attribute at the start
    of the given text.
    If found, the attribute value is converted to lower case and then returned,
    otherwise None is returned.
    '''
    match = _RE_XML_DECL.match(text)
    if match is not None:
        decl = match.group(1)
        for match in _RE_XML_DECL_ATTR.finditer(decl):
            name, quote_, value = match.groups()
            if name == 'encoding':
                return value.lower()
    return None

def normalize_url(url):
    '''Returns a unique string for the given URL.
    This is required in some places, since different libs have different
    opinions whether local URLs should start with "file:/" or "file:///".
    '''
    return urlunsplit(urlsplit(url))

class RedirectResult:
    '''Fake HTTP result object that represents a redirection.
    Only the members we use are implemented.
    '''

    def __init__(self, url):
        self.url = url

# Namespaces can be used for inlined content and that are not included in the
# XHTML DTDs. Because DTDs are not namespace aware, anything from an unknown
# namespace is flagged as an error; we must compensate for that.
_UNVALIDATABLE_NAMESPACES = {
    'http://www.w3.org/2000/svg': 'SVG',
    }

# Namespaces of which the elements and attributes are mosty likely included in
# the XHTML DTDs.
_VALIDATABLE_NAMESPACES = {
    'http://www.w3.org/XML/1998/namespace': 'XML',
    }

def _get_foreign_namespaces(root):
    main_ns = root.nsmap[None]
    accepted_ns_prefixes = [
        '{%s}' % namespace
        for namespace in [main_ns] + list(_VALIDATABLE_NAMESPACES)
        ]
    foreign_elem_namespaces = set()
    foreign_attr_namespaces = set()
    for elem in root.iter(etree.Element):
        tag = elem.tag
        if not any(tag.startswith(prefix) for prefix in accepted_ns_prefixes):
            if tag.startswith('{'):
                index = tag.find('}')
                if index != -1:
                    foreign_elem_namespaces.add(tag[1 : index])
        for name in elem.attrib.keys():
            if name.startswith('{'):
                if not any(name.startswith(prefix)
                           for prefix in accepted_ns_prefixes):
                    index = name.find('}')
                    if index != -1:
                        foreign_attr_namespaces.add(name[1 : index])
    return foreign_elem_namespaces, foreign_attr_namespaces

def fetch_page(request):
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
    url_req.add_header(
        'Accept',
        'text/html; q=0.8, application/xhtml+xml; q=1.0'
        )
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
                        url, 'Bad request (HTTP error 400): %s' % ex.msg
                        )
            else:
                raise FetchFailure(
                    url, 'HTTP error %d: %s' % (ex.code, ex.msg)
                    )
        except URLError as ex:
            raise FetchFailure(url, str(ex.reason))
        except OSError as ex:
            raise FetchFailure(url, ex.strerror)

def parse_document(content, is_xml, report):
    '''Parse `content` as XML (if `is_xlm` is true) or HTML (otherwise).
    Parse errors are added to `report`.
    Return a document etree, or None if the document is too broken
    to be parsed at all.
    '''
    parser_factory = etree.XMLParser if is_xml else etree.HTMLParser
    parser = parser_factory(recover=True)
    root = etree.fromstring(content, parser)
    for error in parser.error_log:
        report.add_error(error)
    return None if root is None else root.getroottree()

_RE_PUBLIC_ID = re.compile(r'([ \n\ra-zA-z0-9\-\'\(\)+,./:=?;!*#@$_%])*')
_DTD_CACHE = {}

def get_dtd(public_id):
    '''Returns a DTD for `public_id`.
    DTD instances will be cached.
    Raises ValueError if the ID string contains invalid characters.
    Raises lxml.etree.DTDParseError if the DTD failed to parse.
    '''
    try:
        return _DTD_CACHE[public_id]
    except KeyError:
        match = _RE_PUBLIC_ID.match(public_id)
        if match.end() != len(public_id):
            raise ValueError(
                'Invalid character in public ID "%s": "%s" (position %d)'
                % (public_id, public_id[match.end()], match.end() + 1)
                )
        # lxml wants ID as bytes, for some reason. All valid characters are
        # in ASCII, so that's a safe conversion.
        dtd = etree.DTD(external_id=public_id.encode('ascii'))
        _DTD_CACHE[public_id] = dtd
        return dtd

def validate_document(tree, report):
    '''Perform validation on the document `tree`.
    Any problems found are added to `report`.
    '''

    public_id = tree.docinfo.public_id
    if public_id is None:
        report.add_error(
            'Cannot validate document because public ID is unknown'
            )
        return

    try:
        dtd = get_dtd(public_id)
    except ValueError as ex:
        report.add_error(str(ex))
        return
    except etree.DTDParseError as ex:
        # TODO: Report DTD parse failures at a global level and don't try to
        #       parse them over and over.
        #       Do report the inability to verify.
        report.add_error('Failed to parse DTD for public ID "%s"' % public_id)
        return

    # Remove inline content we cannot validate, for example SVG.
    # TODO: Can't we validate SVG using a separate DTD?
    pruned_tree = None
    root = tree.getroot()
    if None in root.nsmap:
        foreign_elem_namespaces, foreign_attr_namespaces = \
            _get_foreign_namespaces(root)
        namespaces_to_remove = \
            foreign_elem_namespaces & set(_UNVALIDATABLE_NAMESPACES)

        if namespaces_to_remove:
            pruned_tree = deepcopy(tree)
            pruned_root = pruned_tree.getroot()
            for namespace in sorted(namespaces_to_remove):
                _LOG.info('Removing inline content from namespace "%s"',
                          namespace)
                report.add_info(
                    'Page contains inline %s content; '
                    'this will not be validated.'
                    % _UNVALIDATABLE_NAMESPACES[namespace]
                    )
                nodes_to_remove = list(pruned_root.iter('{%s}*' % namespace))
                for elem in nodes_to_remove:
                    #report.add_info('Remove inline element: %s' % elem)
                    elem.getparent().remove(elem)
            # Recompute remaining foreign namespaces.
            foreign_elem_namespaces, foreign_attr_namespaces = \
                _get_foreign_namespaces(pruned_root)

        for namespace in sorted(foreign_elem_namespaces
                                | foreign_attr_namespaces):
            report.add_info(
                'Page contains %s from XML namespace "%s"; '
                'these might be wrongly reported as invalid.'
                % (
                    ' and '.join(
                        description
                        for description, category in (
                            ('elements', foreign_elem_namespaces),
                            ('attributes', foreign_attr_namespaces),
                            )
                        if namespace in category
                        ),
                    namespace,
                    )
                )

    if pruned_tree is None:
        dtd.validate(tree)
    else:
        dtd.validate(pruned_tree)
        if dtd.error_log:
            report.add_info('Line numbers may be inexact because '
                            'unvalidatable content was pruned.')

    for error in dtd.error_log:
        report.add_error(error)

def parse_input_control(attrib):
    _LOG.debug('input: %s', attrib)
    disabled = 'disabled' in attrib
    if disabled:
        return None
    # TODO: Support readonly controls?
    name = attrib.get('name')
    ctype = attrib.get('type')
    value = attrib.get('value')
    if ctype == 'text' or ctype == 'password':
        return TextField(name, value)
    elif ctype == 'checkbox':
        return Checkbox(name, value)
    elif ctype == 'radio':
        return RadioButton(name, value)
    elif ctype == 'file':
        return FileInput(name, value)
    elif ctype == 'hidden':
        return HiddenInput(name, value)
    elif ctype == 'submit' or ctype == 'image':
        return SubmitButton(name, value)
    elif ctype == 'button' or ctype == 'reset':
        # Type "button" is used by JavaScript, "reset" by the browser.
        return None
    else:
        # Invalid control type, will already be flagged by the DTD.
        return None

class PageChecker:
    '''Retrieves a page, validates the XML and parses the contents to find
    references to other pages.
    '''

    def __init__(self, base_url, scribe):
        self.base_url = normalize_url(base_url)
        self.scribe = scribe

    def short_url(self, page_url):
        assert page_url.startswith(self.base_url), page_url
        return page_url[self.base_url.rindex('/') + 1 : ]

    def check(self, req):
        page_url = str(req)
        _LOG.info('Checking page: %s', self.short_url(page_url))

        try:
            inp = fetch_page(req)
        except FetchFailure as report:
            _LOG.info('Failed to open page')
            self.scribe.add_report(report)
            return []

        content_url = normalize_url(inp.url)
        if content_url != page_url:
            report = IncrementalReport(page_url)
            referrers = []
            if content_url.startswith(self.base_url):
                _LOG.info('Redirected to: %s', self.short_url(content_url))
                try:
                    referrers = [Redirect(Request.from_url(content_url))]
                except ValueError as ex:
                    report.add_warning(str(ex))
            else:
                _LOG.info('Redirected outside: %s', content_url)
            if not content_url.startswith('file:'):
                self.scribe.add_report(report)
                inp.close()
            return referrers

        content_type = inp.info().get_content_type()
        try:
            is_xml = {
                'text/html': False,
                'application/xhtml+xml': True,
                }[content_type]
        except KeyError:
            _LOG.info(
                'Skipping. Document type is not HTML or XHTML, but [%s].',
                content_type
                )
            inp.close()
            return []

        try:
            content_bytes = inp.read()
        except IOError as ex:
            _LOG.info('Failed to fetch: %s', ex)
            self.scribe.add_report(FetchFailure(page_url, str(ex)))
            return []
        finally:
            inp.close()

        report = IncrementalReport(page_url)

        # Build a list of possible encodings.
        # W3C recommends giving the BOM, if present, precedence over HTTP.
        #   http://www.w3.org/International/questions/qa-byte-order-mark
        bom_encoding = encoding_from_bom(content_bytes)
        http_encoding = inp.info().get_content_charset()
        encodings = []
        if bom_encoding is not None:
            encodings.append(bom_encoding)
        if http_encoding is not None and http_encoding != bom_encoding:
            encodings.append(http_encoding)
        if 'utf-8' not in encodings:
            encodings.append('utf-8')

        # Try to decode the document.
        for encoding in encodings:
            content = strict_decode(content_bytes, encoding)
            if content is not None:
                used_encoding = encoding
                break
        else:
            # All likely encodings failed; ignore all non-ASCII bytes so
            # we can look inside the document for clues.
            content = content_bytes.decode('ascii', 'ignore')
            used_encoding = None

        # Look for encoding in XML declaration.
        if is_xml:
            decl_encoding = encoding_from_xml_decl(content)
            if used_encoding is None and decl_encoding is not None:
                new_content = strict_decode(content_bytes, decl_encoding)
                if new_content is not None:
                    content = new_content
                    used_encoding = decl_encoding
        else:
            decl_encoding = None

        # TODO: Also look at HTML <meta> tags.

        if used_encoding is None:
            # TODO: Do the decoding again to capture the error messages.
            #       Actually, also try non-strict decoding with the first
            #       encoding from the list.
            self.scribe.add_report(FetchFailure(
                page_url, 'Unable to determine document encoding'
                ))
            return []

        # Report differences between suggested encodings and the one we
        # settled on.
        if bom_encoding not in (None, used_encoding):
            report.add_warning(
                'Byte order marker suggests encoding "%s", '
                'while actual encoding seems to be "%s"'
                % (bom_encoding, used_encoding)
                )
        if http_encoding not in (None, used_encoding):
            report.add_warning(
                'HTTP header specifies encoding "%s", '
                'while actual encoding seems to be "%s"'
                % (http_encoding, used_encoding)
                )
        if decl_encoding not in (None, used_encoding):
            report.add_warning(
                'XML declaration specifies encoding "%s", '
                'while actual encoding seems to be "%s"'
                % (decl_encoding, used_encoding)
                )

        if is_xml:
            # The lxml parser does not accept encoding in XML declarations
            # when parsing strings.
            content = strip_xml_decl(content)

        tree = parse_document(content, is_xml, report)
        if tree is None:
            self.scribe.add_report(report)
            return []
        validate_document(tree, report)

        root = tree.getroot()
        ns_prefix = '{%s}' % root.nsmap[None] if None in root.nsmap else ''

        links = defaultdict(LinkSet)
        for anchor in root.iter(ns_prefix + 'a'):
            try:
                href = anchor.attrib['href']
            except KeyError:
                # Not a hyperlink anchor.
                continue
            if href.startswith('?'):
                href = urlsplit(page_url).path + href
            url = urljoin(page_url, href)
            if url.startswith(self.base_url):
                try:
                    request = Request.from_url(url)
                except ValueError as ex:
                    report.add_warning(str(ex))
                else:
                    links[request.page_url].add(request)
        referrers = list(links.values())

        for link in root.iter(ns_prefix + 'link'):
            try:
                linkhref = link.attrib['href']
            except KeyError:
                # Not containing a hyperlink link
                continue
            _LOG.debug(' Found link href: %s', linkhref)

        for image in root.iter(ns_prefix + 'img'):
            try:
                imgsrc = image.attrib['src']
            except KeyError:
                # Not containing a src attribute
                continue
            _LOG.debug(' Found image src: %s', imgsrc)

        for script in root.iter(ns_prefix + 'script'):
            try:
                scriptsrc = script.attrib['src']
            except KeyError:
                # Not containing a src attribute
                continue
            _LOG.debug(' Found script src: %s', scriptsrc)

        for form_node in root.getiterator(ns_prefix + 'form'):
            # TODO: How to handle an empty action?
            #       1. take current path, erase query (current impl)
            #       2. take current path, merge query
            #       3. flag as error (not clearly specced)
            #       I think either flag as error, or mimic the browsers.
            try:
                action = form_node.attrib['action'] or urlsplit(page_url).path
                method = form_node.attrib['method'].lower()
            except KeyError:
                continue
            if method == 'post':
                # TODO: Support POST (with flag to enable/disable).
                continue
            if method != 'get':
                # The DTD will already have flagged this as a violation.
                continue
            submit_url = urljoin(page_url, action)
            if not submit_url.startswith(self.base_url):
                continue

            # Note: Disabled controls should not be submitted, so we pretend
            #       they do not even exist.
            controls = []
            radio_buttons = defaultdict(list)
            submit_buttons = []
            for inp in form_node.getiterator(ns_prefix + 'input'):
                control = parse_input_control(inp.attrib)
                if control is None:
                    pass
                elif isinstance(control, RadioButton):
                    radio_buttons[control.name].append(control)
                elif isinstance(control, SubmitButton):
                    submit_buttons.append(control)
                else:
                    controls.append(control)
            for control in form_node.getiterator(ns_prefix + 'select'):
                name = control.attrib.get('name')
                multiple = control.attrib.get('multiple')
                disabled = 'disabled' in control.attrib
                if disabled:
                    continue
                options = [
                    option.attrib.get('value', option.text)
                    for option in control.getiterator(ns_prefix + 'option')
                    ]
                if multiple:
                    for option in options:
                        controls.append(SelectMultiple(name, option))
                else:
                    controls.append(SelectSingle(name, options))
            for control in form_node.getiterator(ns_prefix + 'textarea'):
                name = control.attrib.get('name')
                value = control.text
                disabled = 'disabled' in control.attrib
                if disabled:
                    continue
                _LOG.debug('textarea "%s": %s', name, value)
                controls.append(TextArea(name, value))

            # Merge exclusive controls.
            for buttons in radio_buttons.values():
                controls.append(RadioButtonGroup(buttons))
            if submit_buttons:
                controls.append(SubmitButtons(submit_buttons))
            # If the form contains no submit buttons, assume it can be
            # submitted using JavaScript, so continue.

            form = Form(submit_url, method, controls)
            referrers.append(form)

        self.scribe.add_report(report)
        return referrers
