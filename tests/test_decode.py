import codecs
import logging
import unittest

from apetest.decode import decode_and_report, standard_codec_name, try_decode

from utils import no_log


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class TestStandardCodecName(unittest.TestCase):
    """Test `standard_codec_name` function."""

    names = (
        'us-ascii',
        'iso-8859-1',
        'iso-8859-2',
        'iso-8859-3',
        'iso-8859-4',
        'iso-8859-5',
        'iso-8859-6',
        'iso-8859-7',
        'iso-8859-8',
        'iso-8859-9',
        'iso-8859-10',
        'shift_jis',
        'euc-jp',
        'iso-2022-kr',
        'euc-kr',
        'iso-2022-jp',
        'iso-2022-jp-2',
        'iso-8859-6-e',
        'iso-8859-6-i',
        'iso-8859-8-e',
        'iso-8859-8-i',
        'gb2312',
        'big5',
        'koi8-r',
        )

    def test_self(self):
        """Test whether a standard name is returned as-is."""
        for name in self.names:
            self.assertEqual(standard_codec_name(name), name)

    def test_other(self):
        """Test whether an unlisted codec name is returned as-is."""
        for name in ('cp437', 'gibberish'):
            self.assertEqual(standard_codec_name(name), name)

    def test_round_trip(self):
        """Test standard name -> Python name -> standard name cycle."""
        for name in self.names:
            if name in ('iso-8859-6-e', 'iso-8859-6-i',
                        'iso-8859-8-e', 'iso-8859-8-i'):
                # RFC 1556 defines explicit ("-e") and implicit ("-i")
                # handling of bi-directional text, such as Arabic or Hebrew
                # (right-to-left) mixed with English (left-to-right).
                # Python does not have separate codecs for these charset names.
                continue
            codec_info = codecs.lookup(name)
            self.assertEqual(standard_codec_name(codec_info.name), name)

class TestTryDecode(unittest.TestCase):
    """Test `try_decode` function."""

    def test_trivial(self):
        """Test scanning of files that contain no records."""
        def to_try():
            yield 'us-ascii'
        text, encoding = try_decode(b'Hello', to_try())
        self.assertEqual(text, 'Hello')
        self.assertEqual(encoding, 'us-ascii')

    def test_nonstandard(self):
        """Test handling of a non-standard encoding name."""
        def to_try():
            yield 'ascii'
        text, encoding = try_decode(b'Hello', to_try())
        self.assertEqual(text, 'Hello')
        self.assertEqual(encoding, 'us-ascii')

    def test_no_options(self):
        """Test handling of no encoding options."""
        with self.assertRaises(ValueError):
            text, encoding = try_decode(b'Hello', ())

    def test_no_valid_options(self):
        """Test handling of no valid encoding options."""
        def to_try():
            yield 'utf-8'
        with self.assertRaises(ValueError):
            text, encoding = try_decode(b'\xC0', to_try())

    def test_first(self):
        """Test whether the first possible encoding is used."""
        def to_try():
            yield 'us-ascii'
            yield 'utf-8'
        text, encoding = try_decode(b'Hello', to_try())
        self.assertEqual(text, 'Hello')
        self.assertEqual(encoding, 'us-ascii')
        text, encoding = try_decode(b'Hello', reversed(list(to_try())))
        self.assertEqual(text, 'Hello')
        self.assertEqual(encoding, 'utf-8')

    def test_utf8_only(self):
        """Test whether an emoji is decoded as UTF-8."""
        to_try = ['us-ascii', 'utf-8']
        text, encoding = try_decode(b'smile \xf0\x9f\x98\x83', to_try)
        self.assertEqual(text, 'smile \U0001f603')
        self.assertEqual(encoding, 'utf-8')
        to_try.reverse()
        text, encoding = try_decode(b'smile \xf0\x9f\x98\x83', to_try)
        self.assertEqual(text, 'smile \U0001f603')
        self.assertEqual(encoding, 'utf-8')

class TestDecodeAndReport(unittest.TestCase):
    """Test `decode_and_report` function."""

    def test_trivial(self):
        """Test an input that should succeed without logging."""
        def to_try():
            yield 'us-ascii', 'header'
        with no_log(logger):
            text, encoding = decode_and_report(b'Hello', to_try(), logger)
        self.assertEqual(text, 'Hello')
        self.assertEqual(encoding, 'us-ascii')

    def test_nonstandard(self):
        """Test handling of a non-standard encoding name."""
        def to_try():
            yield 'ascii', 'header'
        with self.assertLogs(logger, logging.INFO):
            text, encoding = decode_and_report(b'Hello', to_try(), logger)
        self.assertEqual(text, 'Hello')
        self.assertEqual(encoding, 'us-ascii')

    def test_implicit_utf8(self):
        """Test whether UTF-8 is tried even when not specified."""
        to_try = (
            ('ascii', 'bad header'),
            )
        with self.assertLogs(logger, logging.WARNING):
            text, encoding = decode_and_report(b'smile \xf0\x9f\x98\x83',
                                               to_try, logger)
        self.assertEqual(text, 'smile \U0001f603')
        self.assertEqual(encoding, 'utf-8')

    def test_none(self):
        """Test whether None entries are ignored."""
        to_try = (
            (None, 'HTTP header'),
            ('utf-8', 'XML declaration'),
            (None, 'Unicode BOM'),
            )
        with no_log(logger):
            text, encoding = decode_and_report(b'smile \xf0\x9f\x98\x83',
                                               to_try, logger)
        self.assertEqual(text, 'smile \U0001f603')
        self.assertEqual(encoding, 'utf-8')

    def test_invalid(self):
        """Test what happens when there is no valid way to decode."""
        to_try = (
            ('us-ascii', 'HTTP header'),
            (None, 'Unicode BOM'),
            ('utf-8', 'XML declaration'),
            )
        with self.assertRaises(ValueError):
            text, encoding = decode_and_report(b'cut-off smile \xf0\x9f\x98',
                                               to_try, logger)

if __name__ == '__main__':
    unittest.main()
