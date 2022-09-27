# SPDX-License-Identifier: BSD-3-Clause

"""
Text decode functions.

These functions can be used to get Unicode strings from a series of bytes.
"""

from __future__ import annotations

from codecs import (
    BOM_UTF8,
    BOM_UTF16_BE,
    BOM_UTF16_LE,
    BOM_UTF32_BE,
    BOM_UTF32_LE,
    CodecInfo,
    lookup as lookup_codec,
)
from typing import Iterable

from apetest.typing import LoggerT


def encoding_from_bom(data: bytes) -> str | None:
    """
    Look for a byte-order-marker at the start of the given C{bytes}.
    If found, return the encoding matching that BOM, otherwise return C{None}.
    """
    if data.startswith(BOM_UTF8):
        return "utf-8"
    elif data.startswith(BOM_UTF16_LE) or data.startswith(BOM_UTF16_BE):
        return "utf-16"
    elif data.startswith(BOM_UTF32_LE) or data.startswith(BOM_UTF32_BE):
        return "utf-32"
    else:
        return None


def standard_codec_name(name: str) -> str:
    """
    Map a codec name to the preferred standardized version.

    The preferred names were taken from this list published by IANA:
    U{http://www.iana.org/assignments/character-sets/character-sets.xhtml}

    @param name:
        Text encoding name, in lower case.
    """
    if name.startswith("iso8859"):
        return "iso-8859" + name[7:]
    return {
        "ascii": "us-ascii",
        "euc_jp": "euc-jp",
        "euc_kr": "euc-kr",
        "iso2022_jp": "iso-2022-jp",
        "iso2022_jp_2": "iso-2022-jp-2",
        "iso2022_kr": "iso-2022-kr",
    }.get(name, name)


def try_decode(data: bytes, encodings: Iterable[str]) -> tuple[str, str]:
    """
    Attempt to decode text using the given encodings in order.

    @param data:
        Encoded version of the text.
    @param encodings:
        Names of the encodings to try. Must all be lower case.
    @return: C{(text, encoding)}
        The decoded string and the encoding used to decode it.
        The returned encoding is name the preferred name, which could differ
        from the name used in the C{encodings} argument.
    @raise ValueError:
        If the text could not be decoded.
    """

    # Build sequence of codecs to try.
    codecs: dict[str, CodecInfo] = {}
    for encoding in encodings:
        try:
            codec = lookup_codec(encoding)
        except LookupError:
            pass
        else:
            codecs[standard_codec_name(codec.name)] = codec

    # Apply decoders to the document.
    for name, codec in codecs.items():
        try:
            text, consumed = codec.decode(data, "strict")
        except UnicodeDecodeError:
            continue
        if consumed == len(data):
            return text, name
    raise ValueError("Unable to determine document encoding")


def decode_and_report(
    data: bytes,
    encoding_options: Iterable[tuple[str | None, str]],
    logger: LoggerT,
) -> tuple[str, str]:
    """
    Attempt to decode text using several encoding options in order.

    @param data:
        Encoded version of the text.
    @param encoding_options: C{(encoding | None, source)*}
        Each option is a pair of encoding name and a description of
        where this encoding suggestion originated.
        If the encoding name is C{None}, the option is skipped.
    @param logger:
        Non-fatal problems are logged here.
        Such problems include an unknown or differing encodings
        among the options.
    @return: C{(text, encoding)}
        The decoded string and the encoding used to decode it.
    @raise ValueError:
        If the text could not be decoded.
    """

    # Filter and remember encoding options.
    options = [
        (encoding, source)
        for encoding, source in encoding_options
        if encoding is not None
    ]

    encodings = [encoding for encoding, source in options]
    # Always try to decode as UTF-8, since that is the most common encoding
    # these days, plus it's a superset of ASCII so it also works for old or
    # simple documents.
    encodings.append("utf-8")
    text, used_encoding = try_decode(data, encodings)

    # Report differences between suggested encodings and the one we
    # settled on.
    for encoding, source in options:
        try:
            codec = lookup_codec(encoding)
        except LookupError:
            logger.warning(
                '%s specifies encoding "%s", which is unknown to Python',
                source,
                encoding,
            )
            continue

        std_name = standard_codec_name(codec.name)
        if std_name != used_encoding:
            logger.warning(
                '%s specifies encoding "%s", while actual encoding seems to be "%s"',
                source,
                encoding,
                used_encoding,
            )
        elif std_name != encoding:
            logger.info(
                '%s specifies encoding "%s", which is not the standard name "%s"',
                source,
                encoding,
                used_encoding,
            )

    return text, used_encoding
