# SPDX-License-Identifier: BSD-3-Clause

from copy import deepcopy
from os.path import isdir
from time import sleep
from urllib import unquote
from urllib2 import HTTPError, URLError, Request as URLRequest, urlopen
from urlparse import urljoin, urlsplit, urlunsplit

from lxml import etree

from control import (
    Checkbox, FileInput, HiddenInput, RadioButton, RadioButtonGroup,
    SelectSingle, SelectMultiple, SubmitButton, SubmitButtons,
    TextArea, TextField
    )
from referrer import Form, LinkSet, Redirect
from report import FetchFailure, IncrementalReport
from request import Request

def normalizeURL(url):
    '''Returns a unique string for the given URL.
    This is required in some places, since different libs have different
    opinions whether local URLs should start with "file:/" or "file:///".
    '''
    return urlunsplit(urlsplit(url))

class RedirectResult(object):
    '''Fake HTTP result object that represents a redirection.
    Only the members we use are implemented.
    '''

    def __init__(self, url):
        self.url = url

# Namespaces can be used for inlined content and that are not included in the
# XHTML DTDs. Because DTDs are not namespace aware, anything from an unknown
# namespace is flagged as an error; we must compensate for that.
_unvalidatableNamespaces = {
    'http://www.w3.org/2000/svg': 'SVG',
    }

# Namespaces of which the elements and attributes are mosty likely included in
# the XHTML DTDs.
_validatableNamespaces = {
    'http://www.w3.org/XML/1998/namespace': 'XML',
    }

def _getForeignNamespaces(root):
    mainNamespace = root.nsmap[None]
    acceptedNSPrefixes = [
        '{%s}' % namespace
        for namespace in [mainNamespace] + list(_validatableNamespaces)
        ]
    foreignElemNamespaces = set()
    foreignAttrNamespaces = set()
    for elem in root.iter(etree.Element):
        tag = elem.tag
        if not any(tag.startswith(prefix) for prefix in acceptedNSPrefixes):
            if tag.startswith('{'):
                index = tag.find('}')
                if index != -1:
                    foreignElemNamespaces.add(tag[1 : index])
        for name in elem.attrib.iterkeys():
            if name.startswith('{'):
                if not any(name.startswith(prefix)
                           for prefix in acceptedNSPrefixes):
                    index = name.find('}')
                    if index != -1:
                        foreignAttrNamespaces.add(name[1 : index])
    return foreignElemNamespaces, foreignAttrNamespaces

class PageChecker(object):
    '''Retrieves a page, validates the XML and parses the contents to find
    references to other pages.
    '''

    def __init__(self, baseURL, scribe):
        self.baseURL = normalizeURL(baseURL)
        self.scribe = scribe

    def shortURL(self, pageURL):
        assert pageURL.startswith(self.baseURL), pageURL
        return pageURL[self.baseURL.rindex('/') + 1 : ]

    def fetchPage(self, request):
        url = str(request)
        fetchURL = url
        removeIndex = False
        if url.startswith('file:'):
            # Emulate the way a web server handles directories.
            path = unquote(urlsplit(url).path)
            if not path.endswith('/') and isdir(path):
                return RedirectResult(url + '/')
            elif path.endswith('/'):
                removeIndex = True
                fetchURL = url + 'index.html'
        # TODO: Figure out how to do authentication, "user:password@" in
        #       the URL does not work.
        urlRequest = URLRequest(fetchURL)
        urlRequest.add_header(
            'Accept',
            'text/html; q=0.8, application/xhtml+xml; q=1.0'
            )
        while True:
            try:
                result = urlopen(urlRequest)
                if removeIndex:
                    result.url = url
                return result
            except HTTPError, ex:
                if ex.code == 503:
                    if 'retry-after' in ex.headers:
                        try:
                            seconds = int(ex.headers['retry-after'])
                        except ValueError:
                            # TODO: HTTP spec allows a date string here.
                            print 'Parsing of "Retry-After" dates ' \
                                'is not yet implemented'
                            seconds = 5
                    else:
                        seconds = 5
                    print 'Server not ready yet, trying again ' \
                        'in %d seconds' % seconds
                    sleep(seconds)
                elif ex.code == 400:
                    # Generic client error, could be because we submitted an
                    # invalid form value.
                    print 'Bad request (HTTP error 400):', ex.msg
                    if request.maybeBad:
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
            except URLError, ex:
                raise FetchFailure(url, str(ex.reason))
            except OSError, ex:
                raise FetchFailure(url, ex.strerror)

    def check(self, checkRequest):
        pageURL = str(checkRequest)
        print 'Checking page:', self.shortURL(pageURL)

        try:
            inp = self.fetchPage(checkRequest)
        except FetchFailure, report:
            print 'Failed to open page'
            self.scribe.addReport(report)
            return []

        contentURL = normalizeURL(inp.url)
        if contentURL != pageURL:
            report = IncrementalReport(pageURL)
            referrers = []
            if contentURL.startswith(self.baseURL):
                print 'Redirected to:', self.shortURL(contentURL)
                try:
                    referrers = [Redirect(Request.fromURL(contentURL))]
                except ValueError, ex:
                    report.addQueryWarning(str(ex))
            else:
                print 'Redirected outside:', contentURL
            if not contentURL.startswith('file:'):
                self.scribe.addReport(report)
                inp.close()
            return referrers

        if inp.info().type not in ('text/html', 'application/xhtml+xml'):
            print 'Skipping. Document type is not HTML or XHTML, but [%s].' % inp.info().type
            inp.close()
            return []

        try:
            content = inp.read()
        except IOError, ex:
            print 'Failed to fetch'
            self.scribe.addReport(FetchFailure(pageURL, str(ex)))
            return []
        finally:
            inp.close()

        report = IncrementalReport(pageURL)
        root = self.parseDocument(content, report)
        if root is None:
            self.scribe.addReport(report)
            return []

        nsPrefix = '{%s}' % root.nsmap[None] if None in root.nsmap else ''

        links = {}
        for anchor in root.iter(nsPrefix + 'a'):
            try:
                href = anchor.attrib['href']
            except KeyError:
                # Not a hyperlink anchor.
                continue
            if href.startswith('?'):
                href = urlsplit(pageURL).path + href
            url = urljoin(pageURL, href)
            if url.startswith(self.baseURL):
                try:
                    request = Request.fromURL(url)
                except ValueError, ex:
                    report.addQueryWarning(str(ex))
                else:
                    linksToPage = links.get(request.pageURL)
                    if linksToPage is None:
                        linksToPage = LinkSet()
                        links[request.pageURL] = linksToPage
                    linksToPage.add(request)

        referrers = list(links.itervalues())

        for link in root.iter(nsPrefix + 'link'):
            try:
                linkhref = link.attrib['href']
            except KeyError:
                # Not containing a hyperlink link
                continue
            print ' Found link href: ', linkhref

        for image in root.iter(nsPrefix + 'img'):
            try:
                imgsrc = image.attrib['src']
            except KeyError:
                # Not containing a src attribute
                continue
            print ' Found image src: ', imgsrc

        for script in root.iter(nsPrefix + 'script'):
            try:
                scriptsrc = script.attrib['src']
            except KeyError:
                # Not containing a src attribute
                continue
            print ' Found script src: ', scriptsrc

        for formNode in root.getiterator(nsPrefix + 'form'):
            # TODO: How to handle an empty action?
            #       1. take current path, erase query (current impl)
            #       2. take current path, merge query
            #       3. flag as error (not clearly specced)
            #       I think either flag as error, or mimic the browsers.
            try:
                action = formNode.attrib['action'] or urlsplit(pageURL).path
                method = formNode.attrib['method'].lower()
            except KeyError:
                continue
            if method == 'post':
                # TODO: Support POST (with flag to enable/disable).
                continue
            if method != 'get':
                # The DTD will already have flagged this as a violation.
                continue
            submitURL = urljoin(pageURL, action)
            if not submitURL.startswith(self.baseURL):
                continue

            # Note: Disabled controls should not be submitted, so we pretend
            #       they do not even exist.
            controls = []
            radioButtons = {}
            submitButtons = []
            for inp in formNode.getiterator(nsPrefix + 'input'):
                control = self.parseInputControl(inp.attrib)
                if control is None:
                    pass
                elif isinstance(control, RadioButton):
                    radioButtons.setdefault(control.name, []).append(control)
                elif isinstance(control, SubmitButton):
                    submitButtons.append(control)
                else:
                    controls.append(control)
            for control in formNode.getiterator(nsPrefix + 'select'):
                name = control.attrib.get('name')
                multiple = control.attrib.get('multiple')
                disabled = 'disabled' in control.attrib
                if disabled:
                    continue
                options = [
                    option.attrib.get('value', option.text)
                    for option in control.getiterator(nsPrefix + 'option')
                    ]
                if multiple:
                    for option in options:
                        controls.append(SelectMultiple(name, option))
                else:
                    controls.append(SelectSingle(name, options))
            for control in formNode.getiterator(nsPrefix + 'textarea'):
                name = control.attrib.get('name')
                value = control.text
                disabled = 'disabled' in control.attrib
                if disabled:
                    continue
                print 'textarea "%s": %s' % (name, value)
                controls.append(TextArea(name, value))

            # Merge exclusive controls.
            for buttons in radioButtons.itervalues():
                controls.append(RadioButtonGroup(buttons))
            if submitButtons:
                controls.append(SubmitButtons(submitButtons))
            # If the form contains no submit buttons, assume it can be
            # submitted using JavaScript, so continue.

            form = Form(submitURL, method, controls)
            referrers.append(form)

        self.scribe.addReport(report)
        return referrers

    def parseDocument(self, content, report):
        root = None
        validationErrors = None
        xmlnsdef = 'xmlns='
        xmldoc = False

        # Try to parse XML with a DTD validating parser.
        # TODO: The content can be XML but also HTML
        #        If the content is HTML, than we use the wrong parser (XML) now.
        if xmlnsdef in content:
            xmldoc = True

        if xmldoc:
            report.addNote('Page content is XML')
            parser = etree.XMLParser(dtd_validation=True, no_network=True)
        else:
            report.addNote('Page content is HTML')
            parser = etree.HTMLParser()
        try:
            root = etree.fromstring(content, parser)
        except etree.XMLSyntaxError, ex:
            report.addNote('Failed to parse with DTD validation.')
            validationErrors = [ex]
        else:
            if parser.error_log:
                # Parsing succeeded with errors; errors will be reported later.
                validationErrors = parser.error_log
            else:
                # Parsing succeeded with no errors, so we are done.
                return root

        # Try to get a parsed version by being less strict.
        for recover in (False, True):
            if root is None:
                parser = etree.XMLParser(
                    recover=recover,
                    dtd_validation=False,
                    load_dtd=True,
                    no_network=True,
                    )
                try:
                    root = etree.fromstring(content, parser)
                except etree.XMLSyntaxError, ex:
                    if recover:
                        report.addNote('Failed to parse in recovery.')
                    else:
                        report.addNote(
                            'Failed to parse without DTD validation.'
                            )
                    report.addValidationFailure(ex)
        if root is None:
            report.addValidationFailure(
                'Unable to parse: page output does not look like XML or HTML.'
                )
            return None

        mainNamespace = root.nsmap.get(None, None)
        if mainNamespace:
            foreignElemNamespaces, foreignAttrNamespaces = \
                _getForeignNamespaces(root)
            # Remove inline content we cannot validate, for example SVG.
            namespacesToRemove = \
                foreignElemNamespaces & set(_unvalidatableNamespaces)

            if namespacesToRemove:
                prunedRoot = deepcopy(root.getroottree()).getroot()
                for namespace in sorted(namespacesToRemove):
                    print 'Removing inline content from namespace', namespace
                    report.addNote(
                        'Page contains inline %s content; '
                        'this will not be validated.'
                        % _unvalidatableNamespaces[namespace]
                        )
                    nodesToRemove = list(prunedRoot.iter('{%s}*' % namespace))
                    for elem in nodesToRemove:
                        #report.addNote('Remove inline element: %s' % elem)
                        elem.getparent().remove(elem)
                # Recompute remaining foreign namespaces.
                foreignElemNamespaces, foreignAttrNamespaces = \
                    _getForeignNamespaces(prunedRoot)
            else:
                prunedRoot = None

            for namespace in sorted(foreignElemNamespaces
                                    | foreignAttrNamespaces):
                report.addNote(
                    'Page contains %s from XML namespace "%s"; '
                    'these might be wrongly reported as invalid'
                    % (
                        ' and '.join(
                            description
                            for description, category in (
                                ('elements', foreignElemNamespaces),
                                ('attributes', foreignAttrNamespaces),
                                )
                            if namespace in category
                            ),
                        namespace,
                        )
                    )

            if prunedRoot is not None:
                # Try to parse pruned tree with a validating parser.
                # We do this only for the error list: the tree we return is
                # the full tree, since following links from for example SVG
                # content will improve our ability to discover pages and
                # queries.
                parser = etree.XMLParser(dtd_validation=True, no_network=True)
                docinfo = root.getroottree().docinfo
                prunedContent = (
                    "<?xml version='%s' encoding='%s'?>\n" % (
                        docinfo.xml_version.encode('ASCII'),
                        docinfo.encoding.encode('ASCII'),
                        ) +
                    etree.tostring(
                        prunedRoot.getroottree(),
                        encoding=docinfo.encoding,
                        xml_declaration=False,
                        )
                    )
                #print prunedContent
                report.addNote(
                    'Try to parse the pruned tree with a validated parser...'
                    )
                try:
                    dummyRoot_ = etree.fromstring(prunedContent, parser)
                except etree.XMLSyntaxError, ex:
                    report.addNote(
                        'Failed to parse pruned tree with validation.'
                        )
                    report.addValidationFailure(ex)
                else:
                    # Error list from pruned tree will contain less false
                    # positives, so replace original error list.
                    validationErrors = parser.error_log
                    if validationErrors:
                        report.addNote('Line numbers are inexact.')

        if validationErrors:
            for error in validationErrors:
                report.addValidationFailure(error)
        return root

    def parseInputControl(self, attrib):
        print 'input:', attrib
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
