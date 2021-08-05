"""
Unit tests for `apetest.robots`.
"""

from logging import ERROR, INFO, WARNING, getLogger

from pytest import mark

from apetest.robots import (
    lookup_robots_rules,
    parse_robots_txt,
    path_allowed,
    scan_robots_txt,
)

logger = getLogger(__name__)

# Modified example from the Internet-Draft.

EXAMPLE_LINES = """
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
""".split(
    "\n"
)

EXAMPLE_RECORDS = [
    [(2, "user-agent", "unhipbot"), (3, "disallow", "/")],
    [(5, "user-agent", "webcrawler"), (6, "user-agent", "excite"), (7, "disallow", "")],
    [
        (9, "user-agent", "*"),
        (10, "disallow", "/org/plans.html"),
        (11, "allow", "/org/"),
        (12, "allow", "/serv"),
        (14, "allow", "/~mak"),
        (15, "disallow", "/"),
    ],
]

EXAMPLE_MAP = {
    "*": [
        (False, "/org/plans.html"),
        (True, "/org/"),
        (True, "/serv"),
        (True, "/~mak"),
        (False, "/"),
    ],
    "unhipbot": [(False, "/")],
    "webcrawler": [],
    "excite": [],
}


@mark.parametrize(
    "lines",
    (
        [],
        [""],
        ["", ""],
        [" ", "\t"],
        ["#comment"],
    ),
)
def test_scan_robots_empty(lines, caplog):
    """Test scanning of files that contain no records."""
    with caplog.at_level(INFO, logger=__name__):
        assert list(scan_robots_txt(lines, logger)) == []
    assert not caplog.records


def test_scan_robots_example(caplog):
    """Test scanning of example file."""
    with caplog.at_level(INFO, logger=__name__):
        assert list(scan_robots_txt(EXAMPLE_LINES, logger)) == EXAMPLE_RECORDS
    assert not caplog.records


def test_scan_robots_warn_leading_whitespace(caplog):
    """Test scanning of files with leading whitespace."""
    with caplog.at_level(INFO, logger=__name__):
        assert list(
            scan_robots_txt(
                [
                    # Whitespace before field
                    " User-agent: *",
                    "Disallow: /",
                ],
                logger,
            )
        ) == [
            [(1, "user-agent", "*"), (2, "disallow", "/")],
        ]
    assert caplog.record_tuples == [
        ("test_robots", WARNING, "Line 1 has whitespace before field")
    ]


def test_scan_robots_error_missing_colon(caplog):
    """Test scanning of files with missing colon."""
    with caplog.at_level(INFO, logger=__name__):
        assert list(
            scan_robots_txt(
                [
                    # Non-empty line without ":"
                    "User-agent: *",
                    "Foo",
                    "Disallow: /",
                ],
                logger,
            )
        ) == [
            [(1, "user-agent", "*"), (3, "disallow", "/")],
        ]
    assert caplog.record_tuples == [
        ("test_robots", ERROR, 'Line 2 contains no ":"; ignoring line')
    ]


def test_parse_robots_empty(caplog):
    """Test parsing of empty record set."""
    with caplog.at_level(INFO, logger=__name__):
        assert parse_robots_txt((), logger) == {}
    assert not caplog.records


def test_parse_robots_example(caplog):
    """Test parsing of example records."""
    with caplog.at_level(INFO, logger=__name__):
        assert parse_robots_txt(EXAMPLE_RECORDS, logger) == EXAMPLE_MAP
    assert not caplog.records


def test_parse_robots_unknown(caplog):
    """Test handling of unknown fields."""
    records = [[(1, "user-agent", "*"), (2, "foo", "bar"), (3, "disallow", "/")]]
    with caplog.at_level(INFO, logger=__name__):
        assert parse_robots_txt(records, logger) == {"*": [(False, "/")]}
    assert caplog.record_tuples == [
        ("test_robots", INFO, 'Unknown field "foo" (line 2)')
    ]


def test_parse_robots_user_argent_after_rules(caplog):
    """Test handling of user agents specified after rules."""
    records = [
        [
            (1, "user-agent", "smith"),
            (2, "disallow", "/m"),
            (3, "user-agent", "bender"),
            (4, "disallow", "/casino"),
        ]
    ]
    with caplog.at_level(INFO, logger=__name__):
        assert parse_robots_txt(records, logger) == {
            "smith": [(False, "/m")],
            "bender": [(False, "/casino")],
        }
    assert caplog.record_tuples == [
        (
            "test_robots",
            ERROR,
            "Line 3 specifies user agent after rules; assuming new record",
        )
    ]


def test_parse_robots_rules_before_user_agent(caplog):
    """Test handling of rules specified before user agent."""
    records = [
        [
            (1, "disallow", "/m"),
            (2, "user-agent", "smith"),
            (3, "user-agent", "bender"),
            (4, "disallow", "/casino"),
        ]
    ]
    with caplog.at_level(INFO, logger=__name__):
        assert parse_robots_txt(records, logger) == {
            "smith": [(False, "/casino")],
            "bender": [(False, "/casino")],
        }
    assert caplog.record_tuples == [
        (
            "test_robots",
            ERROR,
            "Line 1 specifies disallow rule without a preceding user agent line; "
            "ignoring line",
        )
    ]


def test_parse_robots_duplicate_user_agent(caplog):
    """Test handling of multiple rules for the same user agent."""
    records = [
        [(1, "user-agent", "smith"), (2, "disallow", "/m2")],
        [
            (3, "user-agent", "smith"),
            (4, "disallow", "/m3"),
        ],
    ]
    with caplog.at_level(INFO, logger=__name__):
        assert parse_robots_txt(records, logger) == {"smith": [(False, "/m2")]}
    assert caplog.record_tuples == [
        (
            "test_robots",
            ERROR,
            'Line 3 specifies user agent "smith", which was already addressed '
            "in an earlier record; ignoring new record",
        ),
    ]


def test_parse_robots_unescape_valid(caplog):
    """Test unescaping of correctly escaped paths."""
    records = [
        [
            (1, "user-agent", "*"),
            (2, "disallow", "/a%3cd.html"),
            (3, "disallow", "/%7Ejoe/"),
            (4, "disallow", "/a%2fb.html"),
            (5, "disallow", "/%C2%A2"),
            (6, "disallow", "/%e2%82%ac"),
            (7, "disallow", "/%F0%90%8d%88"),
        ]
    ]
    with caplog.at_level(INFO, logger=__name__):
        assert parse_robots_txt(records, logger) == {
            "*": [
                (False, "/a<d.html"),
                (False, "/~joe/"),
                (False, "/a%2fb.html"),
                (False, "/\u00A2"),
                (False, "/\u20AC"),
                (False, "/\U00010348"),
            ]
        }
    assert not caplog.records


@mark.parametrize(
    "bad_path, reason",
    (
        ("/%", 'incomplete escape, expected 2 characters after "%"'),
        ("/%1", 'incomplete escape, expected 2 characters after "%"'),
        ("/%1x", 'incorrect escape: expected 2 hex digits after "%", got "1x"'),
        ("/%-3", 'incorrect escape: expected 2 hex digits after "%", got "-3"'),
        (
            "/%80",
            "invalid percent-encoded UTF8: expected 0xC0..0xF7 for first byte, "
            "got 0x80",
        ),
        (
            "/%e2%e3",
            "invalid percent-encoded UTF8: expected 0x80..0xBF for non-first byte, "
            "got 0xE3",
        ),
        ("/%e2%82", "incomplete escaped UTF8 character, expected 1 more escaped bytes"),
        ("/%e2%82%a", 'incomplete escape, expected 2 characters after "%"'),
        (
            "/%e2%82ac",
            "incomplete escaped UTF8 character, expected 1 more escaped bytes",
        ),
    ),
)
def test_parse_robots_unescape_invalid(bad_path, reason, caplog):
    """Test handling of incorrect escaped paths."""
    with caplog.at_level(INFO, logger=__name__):
        assert (
            parse_robots_txt(
                [
                    [
                        (1, "user-agent", "*"),
                        (2, "disallow", bad_path),
                        (3, "allow", "/good"),
                    ]
                ],
                logger,
            )
            == {"*": [(True, "/good")]}
        )
    assert caplog.record_tuples == [
        ("test_robots", ERROR, f"Bad escape in disallow URL on line 2: {reason}")
    ]


@mark.parametrize(
    "name, entry",
    (
        # Exact match.
        ("excite", "excite"),
        # Prefix match.
        ("web", "webcrawler"),
        # Case-insensitive match.
        ("UnHipBot", "unhipbot"),
        # Default.
        ("unknown-bot", "*"),
    ),
)
def test_parse_robots_lookup(name, entry):
    """Test lookup of rules for a specific user agent."""
    assert lookup_robots_rules(EXAMPLE_MAP, name) == EXAMPLE_MAP[entry]


@mark.parametrize(
    "path, expected",
    (
        ("/", False),
        ("/index.html", False),
        ("/server.html", True),
        ("/services/fast.html", True),
        ("/orgo.gif", False),
        ("/org/about.html", True),
        ("/org/plans.html", False),
        ("/~jim/jim.html", False),
        ("/~mak/mak.html", True),
    ),
)
def test_parse_robots_match_path(path, expected):
    """Test the `path_allowed` function."""
    assert path_allowed(path, EXAMPLE_MAP["excite"])
    assert not path_allowed(path, EXAMPLE_MAP["unhipbot"])
    assert path_allowed(path, EXAMPLE_MAP["*"]) == expected
