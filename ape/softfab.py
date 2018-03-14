# SPDX-License-Identifier: BSD-3-Clause

from plugin import Plugin

class PropertiesPlugin(Plugin):

    def __init__(self, propertiesDir = '.'):
        Plugin.__init__(self)
        self.propertiesDir = propertiesDir

    def postProcess(self, scribe):
        total = len(scribe.pages)
        numFailedPages = len(scribe.getFailedPages())
        resultsProperties = {
            'result': 'ok' if numFailedPages == 0 else 'warning',
            'summary': scribe.getSummary(),
            'data.pages_total': total,
            'data.pages_pass': total - numFailedPages,
            'data.pages_fail': numFailedPages,
            }
        #midLevelProperties =  {
        #    'extraction.result': 'ok',
        #    'data.pages_total': total,
        #    'data.pages_pass': total - numFailedPages,
        #    'data.pages_fail': numFailedPages,
        #    }

        for description, fileName, data in (
            ( 'execution', 'results.properties', resultsProperties ),
            #( 'mid-level', 'extracted.properties', midLevelProperties ),
            ):
            fullFileName = self.propertiesDir + '/' + fileName
            print 'Writing %s metadata to "%s"...' % (
                description, fullFileName
                )
            out = file(fullFileName, 'w')
            for key in sorted(data.iterkeys()):
                print >> out, '%s=%s' % ( key, data[key] )
            out.close()
