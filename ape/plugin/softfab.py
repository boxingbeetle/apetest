# SPDX-License-Identifier: BSD-3-Clause

from ape.plugin import Plugin

class PropertiesPlugin(Plugin):

    def __init__(self, properties_dir='.'):
        Plugin.__init__(self)
        self.properties_dir = properties_dir

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
        path = self.properties_dir + '/results.properties'
        print('Writing metadata to "%s"...' % path)
        with open(path, 'w') as out:
            for key in sorted(data.keys()):
                print('%s=%s' % (key, data[key]), file=out)
