# SPDX-License-Identifier: BSD-3-Clause

"""
Checks a document for problems and finds links to other documents.

The L{PageChecker} class is where the work is done.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Iterator
from enum import Enum, auto
from logging import getLogger
from typing import DefaultDict, cast
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.response import addinfourl

from lxml import etree

from apetest.control import (
    Checkbox,
    Control,
    FileInput,
    HiddenInput,
    RadioButton,
    RadioButtonGroup,
    SelectMultiple,
    SelectSingle,
    SubmitButton,
    SubmitButtons,
    TextArea,
    TextField,
)
from apetest.decode import decode_and_report, encoding_from_bom
from apetest.fetch import load_page
from apetest.plugin import PluginCollection
from apetest.referrer import Form, LinkSet, Redirect, Referrer
from apetest.report import Checked, Report, Scribe
from apetest.request import Request
from apetest.xmlgen import concat, xml

Element = etree._Element  # pylint: disable=protected-access


class Accept(Enum):
    """The types of documents that we tell the server we accept."""

    ANY = auto()
    """Accept both HTML and XHTML."""

    HTML = auto()
    """Accept only HTML."""


_LOG = getLogger(__name__)

_RE_XML_DECL = re.compile(r'<\?xml([ \t\r\n\'"\w.\-=]*).*\?>')
_RE_XML_DECL_ATTR = re.compile(
    r"[ \t\r\n]+([a-z]+)[ \t\r\n]*=[ \t\r\n]*(?P<quote>['\"])([\w.\-]*)(?P=quote)"
)


def strip_xml_decl(text: str) -> str:
    """
    Strip the XML declaration from the start of the given text.

    @return: The given text without XML declaration,
             or the unmodified text if no XML declaration was found.
    """
    match = _RE_XML_DECL.match(text)
    return text if match is None else text[match.end() :]


def encoding_from_xml_decl(text: str) -> str | None:
    """
    Look for an XML declaration with an C{encoding} attribute at the start
    of the given text.

    @return: The attribute value, converted to lower case,
             or C{None} if no attribute was found.
    """

    match = _RE_XML_DECL.match(text)
    if match is not None:
        decl = match.group(1)
        for match in _RE_XML_DECL_ATTR.finditer(decl):
            name, quote_, value = match.groups()
            if name == "encoding":
                return value.lower()
    return None


def normalize_url(url: str) -> str:
    """
    Return a unique string for the given URL.

    This is required in some places, since different libraries
    have different opinions whether local URLs should start with
    C{file:/} or C{file:///}.
    """

    return urlunsplit(urlsplit(url))


def parse_document(
    content: str, is_xml: bool, report: Report
) -> etree._ElementTree | None:
    """
    Parse the given XML or HTML document.

    @param content:
        Text to be parsed.
    @param is_xml:
        If C{True}, parse as XML, otherwise parse as HTML.
    @param report:
        Parse errors are logged here.
    @return:
        A document U{C{etree}<https://lxml.de/api.html#lxml-etree>},
        or C{None} if the document is too broken to be parsed.
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
            "Failed to parse document as %s; "
            "cannot gather references to other documents.",
            "XML" if is_xml else "HTML",
        )
        return None

    # The lxml HTML parser is an HTML4 parser. HTML5 is similar enough
    # that it will still be able to produce a document tree, but it will
    # report errors on for example inline SVG.
    if is_xml:
        for error in parser.error_log:  # pylint: disable=not-an-iterable
            if hasattr(error, "line"):
                line = error.line
            elif hasattr(error, "position"):
                line = error.position[0]
            else:
                line = None

            message = error.message
            if line is not None:
                message += f" (line {line:d})"

            report.error(message)

    return None if root is None else root.getroottree()


def repair_tree(tree: etree._ElementTree, content_type: str, report: Report) -> bool:
    """
    Check the document tree for general errors that would prevent
    other checkers from doing their work and repair those if possible.

    @return: True iff the tree was modified.
    """

    modified = False

    # Make sure XHTML root element has a namespace.
    if content_type == "application/xhtml+xml":
        root = tree.getroot()
        if root.tag != "{http://www.w3.org/1999/xhtml}html":
            msg = "The root element does not use the XHTML namespace."
            html = concat(
                msg,
                xml.br,
                "expected: ",
                xml.code['<html xmlns="http://www.w3.org/1999/xhtml"'],
            )
            report.error(msg, extra={"html": html})
            # lxml will auto-fix this for us when serializing, so there is
            # no need to actually modify the tree.
            modified = True

    return modified


def _get_text(element: Element) -> str:
    value = element.text
    return "" if value is None else value


def _parse_controls(nodes: Iterable[Element]) -> Iterator[tuple[Element, str]]:
    """
    Iterate through the submittable controls defined in the given HTML nodes.

    Each yielded item is a pair containing one control's node and name.

    Controls that are disabled should not be submitted and are therefore skipped over.
    Controls that are nameless cannot be submitted and are likewise skipped over.
    """
    for node in nodes:
        attrib = node.attrib

        disabled = "disabled" in attrib
        if disabled:
            # Disabled controls should not be submitted.
            continue

        name = attrib.get("name")
        if not name:
            # Nameless controls cannot be submitted.
            continue

        yield node, name


def _create_input_control(node: Element, name: str) -> Control | None:
    attrib = node.attrib
    _LOG.debug("input: %s", attrib)
    # TODO: Support readonly controls?
    ctype = attrib.get("type", "text")

    if ctype in ("text", "password"):
        return TextField(name, attrib.get("value", ""))
    elif ctype == "checkbox":
        return Checkbox(name, attrib.get("value", "on"))
    elif ctype == "radio":
        return RadioButton(name, attrib.get("value", "on"))
    elif ctype == "file":
        return FileInput(name, attrib.get("value", ""))
    elif ctype == "hidden":
        return HiddenInput(name, attrib.get("value", ""))
    elif ctype in ("submit", "image"):
        return SubmitButton(name, attrib.get("value", ""))
    elif ctype in ("button", "reset"):
        # Type "button" is used by JavaScript, "reset" by the browser.
        return None
    else:
        # Invalid control type, will already be flagged by the DTD.
        return None


class PageChecker:
    """
    Retrieves a page, checks its contents and finds references
    to other pages.
    """

    def __init__(self, accept: Accept, scribe: Scribe, plugins: PluginCollection):
        """
        Initialize page checker.

        @param accept:
            The types of documents that we tell the server we accept.
        @param scribe:
            Reports will be added here.
        @param plugins:
            Plugins to notify of loaded documents.
        """

        self.accept = accept
        self.scribe = scribe
        self.plugins = plugins

    def check(self, req: Request) -> Iterator[Referrer]:
        """Check a single L{Request}."""

        req_url = str(req)
        _LOG.info("Checking page: %s", req_url)

        accept_header = {
            # Prefer XHTML to HTML because it is stricter.
            Accept.ANY: "text/html; q=0.8, application/xhtml+xml; q=1.0",
            Accept.HTML: "text/html; q=1.0",
        }[self.accept]

        report, response, content_bytes = load_page(
            req_url, req.maybe_bad, accept_header
        )

        if response is not None and 300 <= (response.code or 0) < 400:
            assert response is not None
            content_url = normalize_url(response.url)
            # TODO: If the URL is unchanged, we should probably warn about that.
            if content_url != req_url:
                if not content_url.startswith("file:"):
                    report.info("Redirected to: %s", content_url)
                try:
                    yield Redirect(Request.from_url(content_url))
                except ValueError as ex:
                    report.warning("%s", ex)

        if content_bytes is None:
            report.info("Could not get any content to check")
            report.checked = Checked.NO_CONTENT
        else:
            # If response is None, content_bytes is also None.
            assert response is not None
            yield from self._check_response(req_url, report, response, content_bytes)

        self.scribe.add_report(report)

    def _check_response(
        self, req_url: str, report: Report, response: addinfourl, content_bytes: bytes
    ) -> Iterator[Referrer]:
        """Check the server's response to a request."""

        if response.code not in (200, None):
            # TODO: This should probably be user-selectable.
            #       A lot of web servers produce error and redirection
            #       notices that are not HTML5 compliant. Checking the
            #       content is likely only useful if the application
            #       under test is producing the content instead.
            report.info(
                "Skipping content check because of HTTP status %d", response.code
            )
            report.checked = Checked.HTTP_STATUS_SKIP
            return

        headers = response.headers
        content_type_header = headers["Content-Type"]
        if content_type_header is None:
            message = "Missing Content-Type header"
            _LOG.error(message)
            report.error(message)
            return
        else:
            # Convert Header to plain string.
            content_type_header = str(content_type_header)

        content_type = headers.get_content_type()
        is_html = content_type in ("text/html", "application/xhtml+xml")
        is_xml = content_type.endswith("/xml") or content_type.endswith("+xml")
        http_encoding = headers.get_content_charset()

        # Speculatively decode the first 1024 bytes, so we can look inside
        # the document for encoding clues.
        bom_encoding = encoding_from_bom(content_bytes)
        content_head = content_bytes[:1024].decode(bom_encoding or "ascii", "replace")

        if not is_xml and content_head.startswith("<?xml"):
            is_xml = True
            if req_url.startswith("file:"):
                # Silently correct content-type detection for local files.
                # This is not something the user can easily fix, so issuing
                # a warning would not be helpful.
                if content_type == "text/html":
                    content_type = "application/xhtml+xml"
            else:
                report.warning(
                    'Document is served with content type "%s" '
                    "but starts with an XML declaration",
                    content_type,
                )

        if is_html and is_xml and self.accept is Accept.HTML:
            report.warning(
                "HTML document is serialized as XML, while the HTTP Accept "
                'header did not include "application/xhtml+xml"'
            )

        if is_xml or content_type.startswith("text/"):
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
                    (
                        (bom_encoding, "Byte Order Mark"),
                        (decl_encoding, "XML declaration"),
                        (http_encoding, "HTTP header"),
                    ),
                    report,
                )
            except ValueError as ex:
                # All likely encodings failed.
                report.error("Failed to decode contents: %s", ex)
            else:
                if req_url.startswith("file:"):
                    # Construct a new header that is likely more accurate.
                    content_type_header = f"{content_type}; charset={used_encoding}"

                if is_html or is_xml:
                    tree = parse_document(content, is_xml, report)
                    if tree is not None:
                        if repair_tree(tree, content_type, report):
                            # Offer the repaired tree to plugins, so they
                            # are more likely to be able to do their work.
                            repaired = etree.tostring(tree, encoding="utf-8")
                            assert isinstance(repaired, bytes)
                            content_bytes = repaired

                        # Find links to other documents.
                        yield from find_referrers_in_xml(tree, req_url, report)
                        if is_html:
                            yield from find_referrers_in_html(tree, req_url)

        self.plugins.resource_loaded(content_bytes, content_type_header, report)


_htmlLinkElements = {
    "a": "href",
    "link": "href",
    "img": "src",
    "script": "src",
}
_xmlLinkElements = {
    "{http://www.w3.org/1999/xhtml}" + tag_name: attr_name
    for tag_name, attr_name in _htmlLinkElements.items()
}
# SVG 1.1 uses XLink, but SVG 2 has native 'href' attributes.
# We're only interested in elements that can link to external
# resources, not all elements that support 'href'.
_xmlLinkElements.update(
    {
        "{http://www.w3.org/2000/svg}" + tag_name: "href"
        for tag_name in ("a", "image", "script")
    }
)
_xmlLinkElements.update({"{http://www.w3.org/2005/Atom}link": "href"})
# Insert HTML elements without namespace for HTML trees and
# with namespace for XHTML trees.
_linkElements = dict(_htmlLinkElements)
_linkElements.update(_xmlLinkElements)


def link_attrs_for_node(tag: str) -> Iterator[str]:
    """
    Yield names of attributes that might exist on the given tag and contain URLs.
    """
    try:
        yield _linkElements[tag]
    except KeyError:
        pass
    yield "{http://www.w3.org/1999/xlink}href"


def find_urls(tree: etree._ElementTree) -> Iterator[str]:
    """Yield URLs found in the document C{tree}."""
    for node in tree.getroot().iter():
        for attr in link_attrs_for_node(node.tag):
            try:
                yield cast(str, node.attrib[attr])
            except KeyError:
                pass


def find_referrers_in_xml(
    tree: etree._ElementTree, tree_url: str, report: Report
) -> Iterator[Referrer]:
    """
    Yield referrers for links found in XML tags in the document C{tree}.
    """
    links: DefaultDict[str, LinkSet] = defaultdict(LinkSet)
    for url in find_urls(tree):
        _LOG.debug(" Found URL: %s", url)
        if url.startswith("?"):
            url = urlsplit(tree_url).path + url
        url = urljoin(tree_url, url)
        try:
            request = Request.from_url(url)
        except ValueError as ex:
            report.warning("%s", ex)
        else:
            links[request.page_url].add(request)
    yield from links.values()


def find_referrers_in_html(tree: etree._ElementTree, url: str) -> Iterator[Referrer]:
    """
    Yield referrers for links and forms found in HTML tags in the document C{tree}.
    """
    root = tree.getroot()
    if None in root.nsmap:
        ns_prefix = "{%s}" % root.nsmap[None]
    else:
        ns_prefix = ""

    for form_node in root.iter(ns_prefix + "form"):
        # TODO: How to handle an empty action?
        #       1. take current path, erase query (current impl)
        #       2. take current path, merge query
        #       3. flag as error (not clearly specced)
        #       I think either flag as error, or mimic the browsers.
        try:
            action = cast(str, form_node.attrib["action"]) or urlsplit(url).path
            method = cast(str, form_node.attrib["method"]).lower()
        except KeyError:
            continue
        if method == "post":
            # TODO: Support POST (with flag to enable/disable).
            continue
        if method != "get":
            # The DTD will already have flagged this as a violation.
            continue
        submit_url = urljoin(url, action)

        controls = []
        radio_buttons: DefaultDict[str, list[RadioButton]] = defaultdict(list)
        submit_buttons = []
        for control_node, name in _parse_controls(form_node.iter(ns_prefix + "input")):
            control = _create_input_control(control_node, name)
            if control is None:
                pass
            elif isinstance(control, RadioButton):
                radio_buttons[name].append(control)
            elif isinstance(control, SubmitButton):
                submit_buttons.append(control)
            else:
                controls.append(control)
        for control_node, name in _parse_controls(form_node.iter(ns_prefix + "select")):
            options = []
            for option_node in control_node.iter(ns_prefix + "option"):
                value = option_node.attrib.get("value")
                if value is None:
                    value = _get_text(option_node)
                options.append(value)
            if "multiple" in control_node.attrib:
                for option in options:
                    controls.append(SelectMultiple(name, option))
            else:
                controls.append(SelectSingle(name, options))
        for control_node, name in _parse_controls(
            form_node.iter(ns_prefix + "textarea")
        ):
            value = _get_text(control_node)
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
