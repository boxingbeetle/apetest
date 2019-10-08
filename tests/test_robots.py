import logging
import unittest

from apetest.robots import (
    lookup_robots_rules, parse_robots_txt, path_allowed, scan_robots_txt
    )

from utils import no_log


logger = logging.getLogger(__name__)

# Modified example from the Internet-Draft.

EXAMPLE_LINES = '''
User-agent: unhipbot
Disallow: /

User-agent: webcrawler
User-agent: excite      # comment
Disallow:

User-agent: *
Disallow: /org/plans.html
Allow: /org/
Allow: /serv
# Comment-only lines do not end record.
Allow: /~mak
Disallow: /
'''.split('\n')

EXAMPLE_RECORDS = [
    [(2, 'user-agent', 'unhipbot'),
     (3, 'disallow', '/')],
    [(5, 'user-agent', 'webcrawler'),
     (6, 'user-agent', 'excite'),
     (7, 'disallow', '')],
    [(9, 'user-agent', '*'),
     (10, 'disallow', '/org/plans.html'),
     (11, 'allow', '/org/'),
     (12, 'allow', '/serv'),
     (14, 'allow', '/~mak'),
     (15, 'disallow', '/')]
    ]

EXAMPLE_MAP = {
    '*': [
        (False, '/org/plans.html'),
        (True, '/org/'),
        (True, '/serv'),
        (True, '/~mak'),
        (False, '/')
        ],
    'unhipbot': [
        (False, '/')
        ],
    'webcrawler': [],
    'excite': [],
    }

class TestScanRobots(unittest.TestCase):
    """Test scanning of "robots.txt".
    """

    def test_0100_empty(self):
        """Test scanning of files that contain no records."""
        with no_log(logger):
            self.assertCountEqual(scan_robots_txt([], logger), ())
            self.assertCountEqual(scan_robots_txt([''], logger), ())
            self.assertCountEqual(scan_robots_txt(['', ''], logger), ())
            self.assertCountEqual(scan_robots_txt([' ', '\t'], logger), ())
            self.assertCountEqual(scan_robots_txt(['#comment'], logger), ())

    def test_0200_example(self):
        """Test scanning of example file."""
        with no_log(logger):
            self.assertEqual(
                list(scan_robots_txt(EXAMPLE_LINES, logger)),
                EXAMPLE_RECORDS
                )

    def test_0300_warn(self):
        """Test scanning of files that trigger warnings."""
        with self.assertLogs(logger, logging.WARNING):
            self.assertEqual(list(scan_robots_txt([
                # Whitespace before field
                ' User-agent: *', 'Disallow: /'
                ], logger)), [
                [(1, 'user-agent', '*'), (2, 'disallow', '/')],
                ])
        with self.assertLogs(logger, logging.WARNING):
            self.assertEqual(list(scan_robots_txt([
                # Non-empty line without ":"
                'User-agent: *', 'Foo', 'Disallow: /'
                ], logger)), [
                [(1, 'user-agent', '*'), (3, 'disallow', '/')],
                ])

class TestParseRobots(unittest.TestCase):
    """Test parsing of "robots.txt".
    """

    def test_0100_empty(self):
        """Test parsing of empty record set."""
        with no_log(logger):
            self.assertEqual(parse_robots_txt((), logger), {})

    def test_0200_example(self):
        """Test parsing of example records."""
        with no_log(logger):
            self.assertEqual(
                parse_robots_txt(EXAMPLE_RECORDS, logger),
                EXAMPLE_MAP
                )

    def test_0300_unknown(self):
        """Test handling of unknown fields."""
        records = [
            [(1, 'user-agent', '*'),
             (2, 'foo', 'bar'),
             (3, 'disallow', '/')]
            ]
        with self.assertLogs(logger, logging.INFO):
            self.assertEqual(
                parse_robots_txt(records, logger),
                {'*': [(False, '/')]}
                )

    def test_0310_user_argent_after_rules(self):
        """Test handling of user agents specified after rules."""
        records = [
            [(1, 'user-agent', 'smith'),
             (2, 'disallow', '/m'),
             (3, 'user-agent', 'bender'),
             (4, 'disallow', '/casino')]
            ]
        with self.assertLogs(logger, logging.ERROR):
            self.assertEqual(
                parse_robots_txt(records, logger),
                {'smith': [(False, '/m')], 'bender': [(False, '/casino')]}
                )

    def test_0320_rules_before_user_argent(self):
        """Test handling of rules specified before user agent."""
        records = [
            [(1, 'disallow', '/m'),
             (2, 'user-agent', 'smith'),
             (3, 'user-agent', 'bender'),
             (4, 'disallow', '/casino')]
            ]
        with self.assertLogs(logger, logging.ERROR):
            self.assertEqual(
                parse_robots_txt(records, logger),
                {'smith': [(False, '/casino')], 'bender': [(False, '/casino')]}
                )

    def test_0330_duplicate_user_agent(self):
        """Test handling of multiple rules for the same user agent."""
        records = [
            [(1, 'user-agent', 'smith'),
             (2, 'disallow', '/m2'),
             (3, 'user-agent', 'smith'),
             (4, 'disallow', '/m3')]
            ]
        with self.assertLogs(logger, logging.ERROR):
            self.assertEqual(
                parse_robots_txt(records, logger),
                {'smith': [(False, '/m2')]}
                )

    def test_0400_unescape_valid(self):
        """Test unescaping of correctly escaped paths."""
        records = [
            [(1, 'user-agent', '*'),
             (2, 'disallow', '/a%3cd.html'),
             (3, 'disallow', '/%7Ejoe/'),
             (4, 'disallow', '/a%2fb.html'),
             (5, 'disallow', '/%C2%A2'),
             (6, 'disallow', '/%e2%82%ac'),
             (7, 'disallow', '/%F0%90%8d%88')]
            ]
        with no_log(logger):
            self.assertEqual(parse_robots_txt(records, logger), {
                '*': [
                    (False, '/a<d.html'),
                    (False, '/~joe/'),
                    (False, '/a%2fb.html'),
                    (False, '/\u00A2'),
                    (False, '/\u20AC'),
                    (False, '/\U00010348'),
                    ]
                })

    def test_0410_unescape_invalid(self):
        """Test handling of incorrect escaped paths."""
        for bad_path in (
                '/%', '/%1', # too short
                '/%1x', '/%-3', # bad hex digits
                '/%80', '/%e2%e3', # not UTF8
                '/%e2%82', '/%e2%82%a', '/%e2%82ac', # incomplete UTF8
                ):
            with self.assertLogs(logger, logging.ERROR):
                self.assertEqual(
                    parse_robots_txt([
                        [(1, 'user-agent', '*'),
                         (2, 'disallow', bad_path),
                         (3, 'allow', '/good')]
                        ], logger),
                    {'*': [(True, '/good')]}
                    )

    def test_0500_lookup(self):
        """Test lookup of rules for a specific user agent."""
        # Exact match.
        self.assertEqual(
            lookup_robots_rules(EXAMPLE_MAP, 'excite'),
            EXAMPLE_MAP['excite']
            )
        # Prefix match.
        self.assertEqual(
            lookup_robots_rules(EXAMPLE_MAP, 'web'),
            EXAMPLE_MAP['webcrawler']
            )
        # Case-insensitive match.
        self.assertEqual(
            lookup_robots_rules(EXAMPLE_MAP, 'UnHipBot'),
            EXAMPLE_MAP['unhipbot']
            )
        # Default.
        self.assertEqual(
            lookup_robots_rules(EXAMPLE_MAP, 'unknown-bot'),
            EXAMPLE_MAP['*']
            )

    def test_0600_match_path(self):
        """Test the `path_allowed` function."""
        rules_all = EXAMPLE_MAP['excite']
        rules_none = EXAMPLE_MAP['unhipbot']
        rules_some = EXAMPLE_MAP['*']
        for path, expected in (
                ('/', False),
                ('/index.html', False),
                ('/server.html', True),
                ('/services/fast.html', True),
                ('/orgo.gif', False),
                ('/org/about.html', True),
                ('/org/plans.html', False),
                ('/~jim/jim.html', False),
                ('/~mak/mak.html', True),
                ):
            self.assertTrue(path_allowed(path, rules_all))
            self.assertFalse(path_allowed(path, rules_none))
            self.assertEqual(path_allowed(path, rules_some), expected)

if __name__ == '__main__':
    unittest.main()
