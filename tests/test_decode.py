"""
Unit tests for `apetest.decode`.
"""

from logging import INFO, WARNING, getLogger
import codecs

from pytest import mark, raises

from apetest.decode import decode_and_report, standard_codec_name, try_decode

logger = getLogger(__name__)
logger.setLevel(INFO)


CODEC_NAMES = (
    "us-ascii",
    "iso-8859-1",
    "iso-8859-2",
    "iso-8859-3",
    "iso-8859-4",
    "iso-8859-5",
    "iso-8859-6",
    "iso-8859-7",
    "iso-8859-8",
    "iso-8859-9",
    "iso-8859-10",
    "shift_jis",
    "euc-jp",
    "iso-2022-kr",
    "euc-kr",
    "iso-2022-jp",
    "iso-2022-jp-2",
    "iso-8859-6-e",
    "iso-8859-6-i",
    "iso-8859-8-e",
    "iso-8859-8-i",
    "gb2312",
    "big5",
    "koi8-r",
)


@mark.parametrize("name", CODEC_NAMES)
def test_standard_codec_name_exact(name):
    """Test whether a standard name is returned as-is."""
    assert standard_codec_name(name) == name


@mark.parametrize("name", ("cp437", "gibberish"))
def test_standard_codec_name_unknown(name):
    """Test whether an unlisted codec name is returned as-is."""
    assert standard_codec_name(name) == name


@mark.parametrize(
    "name",
    set(CODEC_NAMES)
    - {
        # RFC 1556 defines explicit ("-e") and implicit ("-i")
        # handling of bi-directional text, such as Arabic or Hebrew
        # (right-to-left) mixed with English (left-to-right).
        # Python does not have separate codecs for these charset names.
        "iso-8859-6-e",
        "iso-8859-6-i",
        "iso-8859-8-e",
        "iso-8859-8-i",
    },
)
def test_standard_codec_name_round_trip(name):
    """Test standard name -> Python name -> standard name cycle."""
    codec_info = codecs.lookup(name)
    assert standard_codec_name(codec_info.name) == name


def test_try_decode_trivial():
    """Test scanning of files that contain no records."""

    def to_try():
        yield "us-ascii"

    text, encoding = try_decode(b"Hello", to_try())
    assert text == "Hello"
    assert encoding == "us-ascii"


def test_try_decode_nonstandard():
    """Test handling of a non-standard encoding name."""

    def to_try():
        yield "ascii"

    text, encoding = try_decode(b"Hello", to_try())
    assert text == "Hello"
    assert encoding == "us-ascii"


def test_try_decode_no_options():
    """Test handling of no encoding options."""
    with raises(ValueError):
        text, encoding = try_decode(b"Hello", ())


def test_try_decode_no_valid_options():
    """Test handling of no valid encoding options."""

    def to_try():
        yield "utf-8"

    with raises(ValueError):
        text, encoding = try_decode(b"\xC0", to_try())


def test_try_decode_first():
    """Test whether the first possible encoding is used."""

    def to_try():
        yield "us-ascii"
        yield "utf-8"

    text, encoding = try_decode(b"Hello", to_try())
    assert text == "Hello"
    assert encoding == "us-ascii"
    text, encoding = try_decode(b"Hello", reversed(list(to_try())))
    assert text == "Hello"
    assert encoding == "utf-8"


def test_try_decode_utf8_only():
    """Test whether an emoji is decoded as UTF-8."""
    to_try = ["us-ascii", "utf-8"]
    text, encoding = try_decode(b"smile \xf0\x9f\x98\x83", to_try)
    assert text == "smile \U0001f603"
    assert encoding == "utf-8"
    to_try.reverse()
    text, encoding = try_decode(b"smile \xf0\x9f\x98\x83", to_try)
    assert text == "smile \U0001f603"
    assert encoding == "utf-8"


def test_decode_and_report_trivial(caplog):
    """Test an input that should succeed without logging."""

    def to_try():
        yield "us-ascii", "header"

    with caplog.at_level(INFO, logger=__name__):
        text, encoding = decode_and_report(b"Hello", to_try(), logger)
    assert text == "Hello"
    assert encoding == "us-ascii"
    assert not caplog.records


def test_decode_and_report_nonstandard(caplog):
    """Test handling of a non-standard encoding name."""

    def to_try():
        yield "ascii", "header"

    with caplog.at_level(INFO, logger=__name__):
        text, encoding = decode_and_report(b"Hello", to_try(), logger)
    assert text == "Hello"
    assert encoding == "us-ascii"
    assert caplog.record_tuples == [
        (
            "test_decode",
            INFO,
            'header specifies encoding "ascii", '
            'which is not the standard name "us-ascii"',
        )
    ]


def test_decode_and_report_implicit_utf8(caplog):
    """Test whether UTF-8 is tried even when not specified."""
    to_try = (("ascii", "bad header"),)
    with caplog.at_level(INFO, logger=__name__):
        text, encoding = decode_and_report(b"smile \xf0\x9f\x98\x83", to_try, logger)
    assert text == "smile \U0001f603"
    assert encoding == "utf-8"
    assert caplog.record_tuples == [
        (
            "test_decode",
            WARNING,
            'bad header specifies encoding "ascii", '
            'while actual encoding seems to be "utf-8"',
        )
    ]


def test_decode_and_report_none(caplog):
    """Test whether None entries are ignored."""
    to_try = (
        (None, "HTTP header"),
        ("utf-8", "XML declaration"),
        (None, "Unicode BOM"),
    )
    with caplog.at_level(INFO, logger=__name__):
        text, encoding = decode_and_report(b"smile \xf0\x9f\x98\x83", to_try, logger)
    assert text == "smile \U0001f603"
    assert encoding == "utf-8"
    assert not caplog.records


def test_decode_and_report_invalid():
    """Test what happens when there is no valid way to decode."""
    to_try = (
        ("us-ascii", "HTTP header"),
        (None, "Unicode BOM"),
        ("utf-8", "XML declaration"),
    )
    with raises(ValueError):
        text, encoding = decode_and_report(
            b"cut-off smile \xf0\x9f\x98", to_try, logger
        )
