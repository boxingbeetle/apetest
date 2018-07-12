# SPDX-License-Identifier: BSD-3-Clause

from ape.vnuclient import VNUClient
from ape.xmlgen import concat, xml

class HTMLValidator:
    '''Runs the Nu Html Checker on a document and adds the results to
     an `IncrementalReport`.
    '''

    def __init__(self):
        self.client = VNUClient('http://localhost:8888')

    def close(self):
        self.client.close()

    def validate(self, data, content_type_header, report):
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
                    if 0 <= start < end < len(extract):
                        extract = xml.code[
                            extract[:start],
                            xml.span(class_='extract')[extract[start:end]],
                            extract[end:]
                            ]
                text = concat(text, xml.br, extract)

            report.add_message(level, text)
