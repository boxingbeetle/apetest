# SPDX-License-Identifier: BSD-3-Clause

"""Checks a document for problems and finds links to other documents.

The `PageChecker` class is where the work is done.
"""

from collections import defaultdict
from email.message import Message
from enum import Enum
from logging import getLogger
from typing import (
    DefaultDict, Iterable, Iterator, List, Optional, cast
)
from urllib.parse import urljoin, urlsplit, urlunsplit
import re

from lxml import etree

from apetest.control import (
    Checkbox, Control, FileInput, HiddenInput, RadioButton, RadioButtonGroup,
    SelectMultiple, SelectSingle, SubmitButton, SubmitButtons, TextArea,
    TextField
)
from apetest.decode import decode_and_report, encoding_from_bom
from apetest.fetch import load_page
from apetest.plugin import PluginCollection
from apetest.referrer import Form, LinkSet, Redirect, Referrer
from apetest.report import Report, Scribe
from apetest.request import Request


class Accept(Enum):
    """The types of documents that we tell the server we accept."""

    ANY = 1
    """Accept both HTML and XHTML."""

    HTML = 2
    """Accept only HTML."""

_LOG = getLogger(__name__)

_RE_XML_DECL = re.compile(
    r'<\?xml([ \t\r\n\'"\w.\-=]*).*\?>'
    )
_RE_XML_DECL_ATTR = re.compile(
    r'[ \t\r\n]+([a-z]+)[ \t\r\n]*=[ \t\r\n]*'
    r'(?P<quote>[\'"])([\w.\-]*)(?P=quote)'
    )

def strip_xml_decl(text: str) -> str:
    """Strip the XML declaration from the start of the given text.

    Returns the given text without XML declaration, or the unmodified text if
    no XML declaration was found.
    """
    match = _RE_XML_DECL.match(text)
    return text if match is None else text[match.end():]

def encoding_from_xml_decl(text: str) -> Optional[str]:
    """Look for an XML declaration with an `encoding` attribute at the start
    of the given text.

    Returns:

    encoding
        The attribute value, converted to lower case.
    None
        If no attribute was found.
    """

    match = _RE_XML_DECL.match(text)
    if match is not None:
        decl = match.group(1)
        for match in _RE_XML_DECL_ATTR.finditer(decl):
            name, quote_, value = match.groups()
            if name == 'encoding':
                return value.lower()
    return None

def normalize_url(url: str) -> str:
    """Returns a unique string for the given URL.

    This is required in some places, since different libraries
    have different opinions whether local URLs should start with
    `file:/` or `file:///`.
    """
    return urlunsplit(urlsplit(url))

def parse_document(
        content: str,
        is_xml: bool,
        report: Report
    ) -> Optional[etree._ElementTree]:
    """Parse the given XML or HTML document.

    Parameters:

    content
        Text to be parsed.
    is_xlm
        If `True`, parse as XML, otherwise parse as HTML.
    report: apetest.report.Report
        Parse errors are logged here.

    Returns:

    tree
        A document `etree`.
    None
        If the document is too broken to be parsed.
    """
    parser_factory = etree.XMLParser if is_xml else etree.HTMLParser
    parser = parser_factory(recover=True)

    if is_xml:
        # The lxml parser does not accept encoding in XML declarations
        # when parsing strings.
        content = strip_xml_decl(content)
    try:
        root = etree.fromstring(content, parser)
    except etree.XMLSyntaxError:
        report.error(
            'Failed to parse document as %s; '
            'cannot gather references to other documents.',
            'XML' if is_xml else 'HTML'
            )
        return None

    # The lxml HTML parser is an HTML4 parser. HTML5 is similar enough
    # that it will still be able to produce a document tree, but it will
    # report errors on for example inline SVG.
    if is_xml:
        for error in parser.error_log:
            if hasattr(error, 'line'):
                line = error.line
            elif hasattr(error, 'position'):
                line = error.position[0]
            else:
                line = None

            message = error.message
            if line is not None:
                message += f' (line {line:d})'

            report.error(message)

    return None if root is None else root.getroottree()

def _parse_input_control(attrib: etree._Attrib) -> Optional[Control]:
    _LOG.debug('input: %s', attrib)
    disabled = 'disabled' in attrib
    if disabled:
        return None
    # TODO: Support readonly controls?
    name = attrib.get('name')
    ctype = attrib.get('type')
    value = attrib.get('value')
    if ctype in ('text', 'password'):
        return TextField(name, value)
    elif ctype == 'checkbox':
        return Checkbox(name, value)
    elif ctype == 'radio':
        return RadioButton(name, value)
    elif ctype == 'file':
        return FileInput(name, value)
    elif ctype == 'hidden':
        return HiddenInput(name, value)
    elif ctype in ('submit', 'image'):
        return SubmitButton(name, value)
    elif ctype in ('button', 'reset'):
        # Type "button" is used by JavaScript, "reset" by the browser.
        return None
    else:
        # Invalid control type, will already be flagged by the DTD.
        return None

class PageChecker:
    """Retrieves a page, checks its contents and finds references
    to other pages.
    """

    def __init__(
            self,
            base_url: str,
            accept: Accept,
            scribe: Scribe,
            plugins: PluginCollection
        ):
        """Initialize page checker.

        Parameters:

        base_url
            Base URL for the web site or app under test.
        accept: Accept
            The types of documents that we tell the server we accept.
        scribe: apetest.report.Scribe
            Reports will be added here.
        plugins: apetest.plugin.PluginCollection
            Plugins to notify of loaded documents.
        """

        self.base_url = normalize_url(base_url)
        self.accept = accept
        self.scribe = scribe
        self.plugins = plugins

    def short_url(self, url: str) -> str:
        """Return a shortened version of `url`.

        This drops the part of the URL that all pages share.
        """

        assert url.startswith(self.base_url), url
        return url[self.base_url.rindex('/') + 1 : ]

    def check(self, req: Request) -> Iterable[Referrer]:
        """Check a single `apetest.request.Request`."""

        req_url = str(req)
        _LOG.info('Checking page: %s', self.short_url(req_url))

        accept = self.accept
        accept_header = {
            # Prefer XHTML to HTML because it is stricter.
            Accept.ANY: 'text/html; q=0.8, application/xhtml+xml; q=1.0',
            Accept.HTML: 'text/html; q=1.0'
            }[accept]

        report, response, content_bytes = load_page(
            req_url, req.maybe_bad, accept_header
            )
        referrers: List[Referrer] = []

        code = None if response is None else response.code
        if code is not None and 300 <= code < 400:
            assert response is not None
            content_url = normalize_url(response.url)
            if content_url != req_url:
                if content_url.startswith(self.base_url):
                    if not content_url.startswith('file:'):
                        report.info(
                            'Redirected to: %s', self.short_url(content_url)
                            )
                    try:
                        referrers.append(
                            Redirect(Request.from_url(content_url))
                            )
                    except ValueError as ex:
                        report.warning('%s', ex)
                else:
                    report.info('Redirected outside: %s', content_url)

        if content_bytes is None:
            report.info('Could not get any content to check')
            skip_content = True
        elif code in (200, None):
            skip_content = False
        else:
            # TODO: This should probably be user-selectable.
            #       A lot of web servers produce error and redirection
            #       notices that are not HTML5 compliant. Checking the
            #       content is likely only useful if the application
            #       under test is producing the content instead.
            report.info(
                'Skipping content check because of HTTP status %d', code
                )
            skip_content = True

        if skip_content:
            report.checked = True
            self.scribe.add_report(report)
            return referrers
        # If content_bytes is None, skip_content is True, so we don't get here.
        assert content_bytes is not None
        # If response is None, content_bytes is also None.
        assert response is not None

        # This type has been fixed in typeshed; the workaround can be removed
        # once mypy updates (0.730 stil has the problem).
        #   https://github.com/python/typeshed/issues/3344
        headers = cast(Message, response.headers)
        content_type_header = headers['Content-Type']
        if content_type_header is None:
            message = 'Missing Content-Type header'
            _LOG.error(message)
            report.error(message)
            self.scribe.add_report(report)
            return referrers

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
            if req_url.startswith('file:'):
                # Silently correct content-type detection for local files.
                # This is not something the user can easily fix, so issuing
                # a warning would not be helpful.
                if content_type == 'text/html':
                    content_type = 'application/xhtml+xml'
            else:
                report.warning(
                    'Document is served with content type "%s" '
                    'but starts with an XML declaration',
                    content_type
                    )

        if is_html and is_xml and accept is Accept.HTML:
            report.warning(
                'HTML document is serialized as XML, while the HTTP Accept '
                'header did not include "application/xhtml+xml"'
                )

        if is_xml or content_type.startswith('text/'):
            # This looks like a text document, now figure out the encoding.

            # Look for encoding in XML declaration (if any).
            decl_encoding = encoding_from_xml_decl(content_head)

            # TODO: Also look at HTML <meta> tags.

            # Try possible encodings in order of precedence.
            # W3C recommends giving the BOM, if present, precedence over HTTP.
            #   http://www.w3.org/International/questions/qa-byte-order-mark
            try:
                content, used_encoding = decode_and_report(
                    content_bytes,
                    ((bom_encoding, 'Byte Order Mark'),
                     (decl_encoding, 'XML declaration'),
                     (http_encoding, 'HTTP header')),
                    report
                    )
            except ValueError as ex:
                # All likely encodings failed.
                report.error('Failed to decode contents: %s', ex)
            else:
                if req_url.startswith('file:'):
                    # Construct a new header that is likely more accurate.
                    content_type_header = \
                            f'{content_type}; charset={used_encoding}'

                if is_html or is_xml:
                    tree = parse_document(content, is_xml, report)
                    if tree is not None:
                        # Find links to other documents.
                        referrers += self.find_referrers_in_xml(
                            tree, req_url, report
                            )
                        if is_html:
                            referrers += self.find_referrers_in_html(
                                tree, req_url
                                )

        self.plugins.resource_loaded(content_bytes, content_type_header, report)
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

    def find_urls(self, tree: etree._ElementTree) -> Iterator[str]:
        """Yield URLs found in the document `tree`."""
        get_attr_name = self._linkElements.__getitem__
        for node in tree.getroot().iter():
            for attr_name in (get_attr_name(cast(str, node.tag)),
                              '{http://www.w3.org/1999/xlink}href'):
                try:
                    yield cast(str, node.attrib[attr_name])
                except KeyError:
                    pass

    def find_referrers_in_xml(
            self,
            tree: etree._ElementTree,
            tree_url: str,
            report: Report
        ) -> Iterator[Referrer]:
        """Yield referrers for links found in XML tags in the document `tree`.
        """
        links: DefaultDict[str, LinkSet] = defaultdict(LinkSet)
        for url in self.find_urls(tree):
            _LOG.debug(' Found URL: %s', url)
            if url.startswith('?'):
                url = urlsplit(tree_url).path + url
            url = urljoin(tree_url, url)
            if url.startswith(self.base_url):
                try:
                    request = Request.from_url(url)
                except ValueError as ex:
                    report.warning('%s', ex)
                else:
                    links[request.page_url].add(request)
        yield from links.values()

    def find_referrers_in_html(
            self,
            tree: etree._ElementTree,
            url: str
        ) -> Iterator[Referrer]:
        """Yield referrers for links and forms found in HTML tags in
        the document `tree`.
        """
        root = tree.getroot()
        ns_prefix = '{%s}' % root.nsmap[None] if None in root.nsmap else ''

        for form_node in root.iter(ns_prefix + 'form'):
            # TODO: How to handle an empty action?
            #       1. take current path, erase query (current impl)
            #       2. take current path, merge query
            #       3. flag as error (not clearly specced)
            #       I think either flag as error, or mimic the browsers.
            try:
                action = cast(str, form_node.attrib['action']) \
                      or urlsplit(url).path
                method = cast(str, form_node.attrib['method']).lower()
            except KeyError:
                continue
            if method == 'post':
                # TODO: Support POST (with flag to enable/disable).
                continue
            if method != 'get':
                # The DTD will already have flagged this as a violation.
                continue
            submit_url = urljoin(url, action)
            if not submit_url.startswith(self.base_url):
                continue

            # Note: Disabled controls should not be submitted, so we pretend
            #       they do not even exist.
            controls = []
            radio_buttons: DefaultDict[str, List[RadioButton]] \
                         = defaultdict(list)
            submit_buttons = []
            for inp in form_node.iter(ns_prefix + 'input'):
                control = _parse_input_control(inp.attrib)
                if control is None:
                    pass
                elif isinstance(control, RadioButton):
                    radio_buttons[control.name].append(control)
                elif isinstance(control, SubmitButton):
                    submit_buttons.append(control)
                else:
                    controls.append(control)
            for control_node in form_node.iter(ns_prefix + 'select'):
                name = control_node.attrib.get('name')
                multiple = control_node.attrib.get('multiple')
                disabled = 'disabled' in control_node.attrib
                if disabled:
                    continue
                options = [
                    option.attrib.get('value', option.text)
                    for option in control_node.iter(ns_prefix + 'option')
                    if option.text is not None
                    ]
                if multiple:
                    for option in options:
                        controls.append(SelectMultiple(name, option))
                else:
                    controls.append(SelectSingle(name, options))
            for control_node in form_node.iter(ns_prefix + 'textarea'):
                name = control_node.attrib.get('name')
                value = control_node.text
                disabled = 'disabled' in control_node.attrib
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
