# SPDX-License-Identifier: BSD-3-Clause

"""Text decode functions.

These functions can be used to get Unicode strings from a series of bytes.
"""

from codecs import (
    BOM_UTF8, BOM_UTF16_BE, BOM_UTF16_LE, BOM_UTF32_BE, BOM_UTF32_LE,
    lookup as lookup_codec
)
from collections import OrderedDict


def encoding_from_bom(data):
    """Look for a byte-order-marker at the start of the given `bytes`.
    If found, return the encoding matching that BOM, otherwise return `None`.
    """
    if data.startswith(BOM_UTF8):
        return 'utf-8'
    elif data.startswith(BOM_UTF16_LE) or data.startswith(BOM_UTF16_BE):
        return 'utf-16'
    elif data.startswith(BOM_UTF32_LE) or data.startswith(BOM_UTF32_BE):
        return 'utf-32'
    else:
        return None

def standard_codec_name(codec):
    """Map a codec name to the preferred standardized version.

    The preferred names were taken from this list published by IANA:
      http://www.iana.org/assignments/character-sets/character-sets.xhtml
    """
    name = codec.name
    if name.startswith('iso8859'):
        return 'iso-8859' + name[7:]
    return {
        'ascii': 'us-ascii',
        'euc_jp': 'euc-jp',
        'euc_kr': 'euc-kr',
        'iso2022_jp': 'iso-2022-jp',
        'iso2022_jp_2': 'iso-2022-jp-2',
        'iso2022_kr': 'iso-2022-kr',
        }.get(name, name)

def try_decode(data, encodings):
    """Attempt to decode text using the given encodings in order.

    Parameters:

    data: bytes
        Encoded version of the text.
    encodings: (encoding | None)*
        Names of the encodings to try.
        Duplicate and `None` entries are skipped.

    Returns:

    text, encoding
        The decoded string and the encoding used to decode it.

    Raises:

    UnicodeDecodeError
        If the text could not be decoded.
    """

    # Build sequence of codecs to try.
    codecs = OrderedDict()
    for encoding in encodings:
        if encoding is not None:
            try:
                codec = lookup_codec(encoding)
            except LookupError:
                pass
            else:
                codecs[standard_codec_name(codec)] = codec

    # Apply decoders to the document.
    for name, codec in codecs.items():
        try:
            text, consumed = codec.decode(data, 'strict')
        except UnicodeDecodeError:
            continue
        if consumed == len(data):
            return text, name
    raise UnicodeDecodeError(
        'Unable to determine document encoding; tried: '
        + ', '.join(codecs.keys())
        )

def decode_and_report(data, encoding_options, report):
    """Attempt to decode text using several encoding options in order.

    Parameters:

    data: bytes
        Encoded version of the text.
    encoding_options: (encoding | None, source)*
        Each option is a pair of encoding name and a description of
        where this encoding suggestion originated.
        If the encoding name is `None`, the option is skipped.
    report
        Non-fatal problems are logged here.
        Such problems include an unknown or differing encodings
        among the options.

    Returns:

    text, encoding
        The decoded string and the encoding used to decode it.

    Raises:

    UnicodeDecodeError
        If the text could not be decoded.
    """

    encodings = [encoding for encoding, source in encoding_options]
    # Always try to decode as UTF-8, since that is the most common encoding
    # these days, plus it's a superset of ASCII so it also works for old or
    # simple documents.
    encodings.append('utf-8')
    text, used_encoding = try_decode(data, encodings)

    # Report differences between suggested encodings and the one we
    # settled on.
    for encoding, source in encoding_options:
        if encoding is None:
            continue

        try:
            codec = lookup_codec(encoding)
        except LookupError:
            report.warning(
                '%s specifies encoding "%s", which is unknown to Python',
                source, encoding
                )
            continue

        std_name = standard_codec_name(codec)
        if std_name != used_encoding:
            report.warning(
                '%s specifies encoding "%s", '
                'while actual encoding seems to be "%s"',
                source, encoding, used_encoding
                )
        elif std_name != encoding:
            report.info(
                '%s specifies encoding "%s", '
                'which is not the standard name "%s"',
                source, encoding, used_encoding
                )

    return text, used_encoding
