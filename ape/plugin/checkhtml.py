# SPDX-License-Identifier: BSD-3-Clause

from cgi import parse_header
from pathlib import Path
from socket import AF_INET, SOCK_STREAM, socket
from subprocess import DEVNULL, Popen

from ape.plugin import Plugin, PluginError
from ape.vnuclient import VNUClient
from ape.xmlgen import concat, xml

def plugin_arguments(parser):
    parser.add_argument(
        '--check', metavar='PORT|URL|launch',
        help='check HTML using v.Nu web service at PORT (localhost) or '
             'URL (remote), or launch a new instance'
        )

def _pick_port():
    '''Returns an unused TCP port.
    While we can not guarantee it will stay unused, it is very unlikely
    that it will become used within a few seconds.
    '''
    with socket(AF_INET, SOCK_STREAM) as sock:
        sock.bind(('', 0))
        return sock.getsockname()[1]

def _find_vnujar():
    '''Returns the full path to "vnu.jar".
    Raises PluginError if "vnu.jar" cannot be found.
    '''
    try:
        import vnujar
    except ImportError:
        raise PluginError(
            'Please install the "vnujar" module, for example using '
            '"pip3 install html5validator"'
            )
    jar_path = Path(vnujar.__file__).with_name('vnu.jar')
    if not jar_path.exists():
        raise PluginError(
            'The "vnujar" module exists, but does not contain "vnu.jar"'
            )
    return jar_path

def _launch_service(jar_path):
    port = _pick_port()
    args = (
        'java', '-cp', str(jar_path), 'nu.validator.servlet.Main', str(port)
        )
    try:
        proc = Popen(args, stdin=DEVNULL)
    except OSError as ex:
        raise PluginError('Failed to launch v.Nu checker servlet: %s' % ex)
    return proc, 'http://localhost:%d' % port

def plugin_create(args):
    url = args.check
    if url is not None:
        launch = False
        if url == 'launch':
            url = _find_vnujar()
            launch = True
        elif url.isdigit():
            url = 'http://localhost:' + url
        yield HTMLValidator(url, launch)

class HTMLValidator(Plugin):
    '''Runs the Nu Html Checker (v.Nu) on loaded documents.
    Download the checker from: https://github.com/validator/validator
    '''

    def __init__(self, service_url, launch):
        '''Creates a validator that uses the checker web service
        at `service_url`.
        If `launch` is True, the validator should be launched using
        the JAR file specified by `service_url`; if `launch` is False,
        `service_url` is the URL of an externally started web service.
        '''
        if launch:
            service, service_url = _launch_service(service_url)
            self.service = service
        else:
            self.service = None
        self.client = VNUClient(service_url)

    def close(self):
        self.client.close()
        if self.service is not None:
            self.service.terminate()

    def resource_loaded(self, data, content_type_header, report):
        # Only forward documents that the checker may be able to handle.
        content_type, args_ = parse_header(content_type_header)
        if content_type not in ('text/html', 'text/css') \
                and not content_type.endswith('+xml'):
            return

        for message in self.client.request(data, content_type_header):
            msg_type = message.get('type')
            subtype = message.get('subtype')
            text = message.get('message', '(no message)')

            if msg_type == 'info':
                level = 'warning' if subtype == 'warning' else 'info'
            elif msg_type == 'error':
                level = 'error'
            elif msg_type == 'non-document-error':
                subtype = subtype or 'general'
                text = '%s error in checker: %s' % (subtype.capitalize(), text)
                level = 'error'
            else:
                text = 'Undocumented message type "%s": %s' % (msg_type, text)
                level = 'error'

            if msg_type == 'error' and subtype == 'fatal':
                text = concat(
                    text, xml.br,
                    xml.b['Fatal:'], ' This error blocks further checking.'
                    )

            lines = '-'.join(
                str(message[attr])
                for attr in ('firstLine', 'lastLine')
                if attr in message
                )
            if lines:
                text = 'line %s: %s' % (lines, text)

            extract = message.get('extract')
            if extract:
                start = message.get('hiliteStart')
                length = message.get('hiliteLength')
                if isinstance(start, int) and isinstance(length, int):
                    end = start + length
                    if 0 <= start < end <= len(extract):
                        extract = (
                            extract[:start],
                            xml.span(class_='extract')[extract[start:end]],
                            extract[end:]
                            )
                text = concat(text, xml.br, xml.code[extract])

            report.add_message(level, text)
