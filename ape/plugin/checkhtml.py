# SPDX-License-Identifier: BSD-3-Clause

from ape.plugin import Plugin
from ape.vnuclient import VNUClient
from ape.xmlgen import concat, xml

def plugin_arguments(parser):
    parser.add_argument(
        '--check', nargs='?', metavar='URL', const='http://localhost:8888',
        help='check HTML using v.Nu web service at URL'
        )

def plugin_create(args):
    if args.check is not None:
        yield HTMLValidator(args.check)

class HTMLValidator(Plugin):
    '''Runs the Nu Html Checker (v.Nu) on loaded documents.
    Download the checker from: https://github.com/validator/validator
    '''

    def __init__(self, service_url):
        '''Creates a validator that uses the checker web service
        at `service_url`.
        '''
        self.client = VNUClient(service_url)

    def resource_loaded(self, data, content_type_header, report):
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

    def postprocess(self, scribe):
        self.client.close()
