# SPDX-License-Identifier: BSD-3-Clause

from codecs import lookup as lookup_codec
from collections import defaultdict
from enum import Enum
from logging import getLogger
import re
from urllib.parse import urljoin, urlsplit, urlunsplit

from lxml import etree

from ape.control import (
    Checkbox, FileInput, HiddenInput, RadioButton, RadioButtonGroup,
    SelectSingle, SelectMultiple, SubmitButton, SubmitButtons,
    TextArea, TextField
    )
from ape.fetch import (
    encoding_from_bom, open_page, standard_codec_name, try_decode
    )
from ape.referrer import Form, LinkSet, Redirect
from ape.report import FetchFailure, IncrementalReport
from ape.request import Request

Accept = Enum('Accept', 'ANY HTML')

_LOG = getLogger(__name__)

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

def parse_document(content, is_xml, report):
    '''Parse `content` as XML (if `is_xlm` is true) or HTML (otherwise).
    Parse errors are added to `report`.
    Return a document etree, or None if the document is too broken
    to be parsed at all.
    '''
    parser_factory = etree.XMLParser if is_xml else etree.HTMLParser
    parser = parser_factory(recover=True)
    if is_xml:
        # The lxml parser does not accept encoding in XML declarations
        # when parsing strings.
        content = strip_xml_decl(content)
    root = etree.fromstring(content, parser)
    # The lxml HTML parser is an HTML4 parser. HTML5 is similar enough
    # that it will still be able to produce a document tree, but it will
    # report errors on for example inline SVG.
    if is_xml:
        for error in parser.error_log:
            report.add_error(error)
    return None if root is None else root.getroottree()

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

    def __init__(self, base_url, accept, scribe, plugins):
        self.base_url = normalize_url(base_url)
        self.accept = accept
        self.scribe = scribe
        self.plugins = plugins

    def short_url(self, page_url):
        assert page_url.startswith(self.base_url), page_url
        return page_url[self.base_url.rindex('/') + 1 : ]

    def check(self, req):
        page_url = str(req)
        _LOG.info('Checking page: %s', self.short_url(page_url))

        accept = self.accept
        accept_header = {
            # Prefer XHTML to HTML because it is stricter.
            Accept.ANY: 'text/html; q=0.8, application/xhtml+xml; q=1.0',
            Accept.HTML: 'text/html; q=1.0'
            }[accept]
        try:
            inp = open_page(req, accept_header)
        except FetchFailure as report:
            _LOG.info('Failed to open page')
            self.scribe.add_report(report)
            return []

        content_url = normalize_url(inp.url)
        if content_url != page_url:
            report = IncrementalReport(page_url)
            report.checked = True
            referrers = []
            if content_url.startswith(self.base_url):
                report.add_info(
                    'Redirected to: %s' % self.short_url(content_url)
                    )
                try:
                    referrers = [Redirect(Request.from_url(content_url))]
                except ValueError as ex:
                    report.add_warning(str(ex))
            else:
                report.add_info('Redirected outside: %s' % content_url)
            if not content_url.startswith('file:'):
                self.scribe.add_report(report)
                inp.close()
            return referrers

        try:
            content_bytes = inp.read()
        except IOError as ex:
            _LOG.info('Failed to fetch: %s', ex)
            self.scribe.add_report(FetchFailure(page_url, str(ex)))
            return []
        finally:
            inp.close()

        report = IncrementalReport(page_url)

        headers = inp.headers
        content_type_header = headers['Content-Type']
        if content_type_header is None:
            message = 'Missing Content-Type header'
            _LOG.error(message)
            self.scribe.add_report(FetchFailure(page_url, message))
            return []

        content_type = headers.get_content_type()
        is_html = content_type in ('text/html', 'application/xhtml+xml')
        is_xml = content_type.endswith('/xml') or content_type.endswith('+xml')
        http_encoding = headers.get_content_charset()

        # Speculatively decode the first 1024 bytes, so we can look inside
        # the document for encoding clues.
        bom_encoding = encoding_from_bom(content_bytes)
        content_head = content_bytes[:1024].decode(
            bom_encoding or 'ascii', 'replace'
            )

        if not is_xml and content_head.startswith('<?xml'):
            is_xml = True
            if page_url.startswith('file:'):
                # Silently correct content-type detection for local files.
                # This is not something the user can easily fix, so issuing
                # a warning would not be helpful.
                if content_type == 'text/html':
                    content_type = 'application/xhtml+xml'
            else:
                report.add_warning(
                    'Document is served with content type "%s" '
                    'but starts with an XML declaration'
                    % content_type
                    )

        if not is_xml and not content_type.startswith('text/'):
            self.plugins.resource_loaded(
                content_bytes, content_type_header, report
                )
            _LOG.info(
                'Document of type "%s" is probably not text; skipping.',
                content_type
                )
            return []

        if is_html and is_xml and accept is Accept.HTML:
            report.add_warning(
                'HTML document is serialized as XML, while the HTTP Accept '
                'header did not include "application/xhtml+xml"'
                )

        # Look for encoding in XML declaration.
        decl_encoding = encoding_from_xml_decl(content_head)

        # TODO: Also look at HTML <meta> tags.

        # Try possible encodings in order of precedence.
        # W3C recommends giving the BOM, if present, precedence over HTTP.
        #   http://www.w3.org/International/questions/qa-byte-order-mark
        try:
            content, used_encoding = try_decode(
                content_bytes,
                (bom_encoding, decl_encoding, http_encoding, 'utf-8')
                )
        except UnicodeDecodeError as ex:
            # All likely encodings failed.
            self.scribe.add_report(FetchFailure(page_url, str(ex)))
            return []

        # Report differences between suggested encodings and the one we
        # settled on.
        for encoding, source in ((bom_encoding, 'Byte Order Mark'),
                                 (decl_encoding, 'XML declaration'),
                                 (http_encoding, 'HTTP header')):
            if encoding is None:
                continue
            try:
                codec = lookup_codec(encoding)
            except LookupError:
                report.add_warning(
                    '%s specifies encoding "%s", which is unknown to Python'
                    % (source, encoding)
                    )
                continue
            std_name = standard_codec_name(codec)
            if std_name != used_encoding:
                report.add_warning(
                    '%s specifies encoding "%s", '
                    'while actual encoding seems to be "%s"'
                    % (source, encoding, used_encoding)
                    )
            elif std_name != encoding:
                report.add_info(
                    '%s specifies encoding "%s", '
                    'which is not the standard name "%s"'
                    % (source, encoding, used_encoding)
                    )

        if page_url.startswith('file:'):
            # Construct a new header that is likely more accurate.
            content_type_header = '%s; charset=%s' % (
                content_type, used_encoding
                )
        self.plugins.resource_loaded(content_bytes, content_type_header, report)

        referrers = []
        if is_html or is_xml:
            tree = parse_document(content, is_xml, report)
            if tree is not None:
                # Find links to other documents.
                links = defaultdict(LinkSet)
                for url in self.find_urls(tree):
                    _LOG.debug(' Found URL: %s', url)
                    if url.startswith('?'):
                        url = urlsplit(page_url).path + url
                    url = urljoin(page_url, url)
                    if url.startswith(self.base_url):
                        try:
                            request = Request.from_url(url)
                        except ValueError as ex:
                            report.add_warning(str(ex))
                        else:
                            links[request.page_url].add(request)
                referrers += links.values()

                # Find other referrers.
                if is_html:
                    referrers += self.find_referrers_in_html(tree, page_url)

        self.scribe.add_report(report)
        return referrers

    _htmlLinkElements = {
        'a': 'href',
        'link': 'href',
        'img': 'src',
        'script': 'src',
        }
    _xmlLinkElements = {
        '{http://www.w3.org/1999/xhtml}' + tag_name: attr_name
        for tag_name, attr_name in _htmlLinkElements.items()
        }
    # SVG 1.1 uses XLink, but SVG 2 has native 'href' attributes.
    # We're only interested in elements that can link to external
    # resources, not all elements that support 'href'.
    _xmlLinkElements.update({
        '{http://www.w3.org/2000/svg}' + tag_name: 'href'
        for tag_name in ('a', 'image', 'script')
        })
    _xmlLinkElements.update({
        '{http://www.w3.org/2005/Atom}link': 'href'
        })
    # Insert HTML elements without namespace for HTML trees and
    # with namespace for XHTML trees.
    _linkElements = dict(_htmlLinkElements)
    _linkElements.update(_xmlLinkElements)

    def find_urls(self, tree):
        """Yields URLs found in the document `tree`.
        """
        get_attr_name = self._linkElements.__getitem__
        for node in tree.getroot().iter():
            try:
                yield node.attrib[get_attr_name(node.tag)]
            except KeyError:
                pass
            try:
                yield node.attrib['{http://www.w3.org/1999/xlink}href']
            except KeyError:
                pass

    def find_referrers_in_html(self, tree, page_url):
        """Yields referrers found in HTML tags in the document `tree`.
        """
        root = tree.getroot()
        ns_prefix = '{%s}' % root.nsmap[None] if None in root.nsmap else ''

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

            yield Form(submit_url, method, controls)
