# SPDX-License-Identifier: BSD-3-Clause

from ape.plugin import Plugin

def plugin_arguments(parser):
    parser.add_argument(
        '--result',
        help='properties file (SoftFab compatible) to write results to'
        )

def plugin_create(args):
    if args.result is not None:
        yield PropertiesPlugin(args.result)

class PropertiesPlugin(Plugin):

    def __init__(self, properties_file):
        self.properties_file = properties_file

    def postprocess(self, scribe):
        total = len(scribe.get_pages())
        num_failed_pages = len(scribe.get_failed_pages())
        data = {
            'result': 'ok' if num_failed_pages == 0 else 'warning',
            'summary': scribe.get_summary(),
            'data.pages_total': total,
            'data.pages_pass': total - num_failed_pages,
            'data.pages_fail': num_failed_pages,
            }
        path = self.properties_file
        print('Writing metadata to "%s"...' % path)
        with open(path, 'w') as out:
            for key in sorted(data.keys()):
                print('%s=%s' % (key, data[key]), file=out)
