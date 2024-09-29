# SPDX-License-Identifier: BSD-3-Clause

"""Functions for handling robot exclusion files ("robots.txt").

There is no official standard for these files: it started with a post
that was later developed into a draft RFC, but that was never finalized.
Later, several search engines invented their own extensions.

This module implements all of the original proposal and some of the
extensions:
  - C{allow} rules
  - percent-encoded UTF-8 in paths

Note that the module takes sequences of strings as its input,
so the decoding of the text file itself is done by the caller.
For interoperability, it is recommended to support at least
UTF-8 both with and without a BOM.

Features that are not (yet) implemented:
  - non-group records such as C{sitemap}
  - C{crawl-delay} rules
  - wildcards in paths

References:
  - U{https://en.wikipedia.org/wiki/Robots_exclusion_standard}
  - U{https://developers.google.com/search/reference/robots_txt}
  - U{http://www.robotstxt.org/}
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping

from apetest.typing import LoggerT


def scan_robots_txt(
    lines: Iterable[str], logger: LoggerT
) -> Iterator[Iterable[tuple[int, str, str]]]:
    """
    Tokenizes the contents of a C{robots.txt} file.

    @param lines:
        Contents of a C{robots.txt} file.
    @param logger:
        Problems found while scanning are logged here.
    @return:
        Yields records, where each record is a sequence of
        C{(lineno, token, value)} triples.
    """
    record: list[tuple[int, str, str]] = []
    for lineno, line in enumerate(lines, 1):
        stripped_line = line.lstrip()
        if stripped_line.startswith("#"):
            # Comment-only lines are discarded and do not end records.
            continue
        if not stripped_line:
            # Empty lines end records.
            if record:
                yield record
                record = []
            continue
        if len(stripped_line) != len(line):
            logger.warning("Line %d has whitespace before field", lineno)

        nocomment_line = stripped_line.split("#", 1)[0]
        try:
            field, value = nocomment_line.split(":", 1)
        except ValueError:
            logger.error('Line %d contains no ":"; ignoring line', lineno)
        else:
            record.append((lineno, field.casefold(), value.strip()))

    if record:
        yield record


def parse_robots_txt(
    records: Iterable[Iterable[tuple[int, str, str]]], logger: LoggerT
) -> Mapping[str, Iterable[tuple[bool, str]]]:
    """
    Parses C{robots.txt} records.

    @param records:
        Tokenized records as produced by L{scan_robots_txt}.
    @param logger:
        Problems found while parsing are logged here.
    @return:
        rules_map: C{{ user_agent: (allowed, url_prefix)* }}
        A mapping from user agent name (case-folded) to a sequence of
        allow/disallow rules, where C{allowed} is C{True} iff the user agent
        is allowed to visit URLs starting with C{url_prefix}.
    """
    result: dict[str, Iterable[tuple[bool, str]]] = {}
    unknowns: set[str] = set()
    for record in records:
        seen_user_agent = False
        rules: list[tuple[bool, str]] = []
        for lineno, field, value in record:
            if field == "user-agent":
                if rules:
                    logger.error(
                        "Line %d specifies user agent after rules; "
                        "assuming new record",
                        lineno,
                    )
                    rules = []
                seen_user_agent = True
                name = value.casefold()
                if name in result:
                    logger.error(
                        'Line %d specifies user agent "%s", which was '
                        "already addressed in an earlier record; "
                        "ignoring new record",
                        lineno,
                        value,
                    )
                else:
                    result[name] = rules
            elif field in ("allow", "disallow"):
                if seen_user_agent:
                    try:
                        path = unescape_path(value)
                    except ValueError as ex:
                        logger.error(
                            "Bad escape in %s URL on line %d: %s", field, lineno, ex
                        )
                    else:
                        # Ignore allow/disallow directives without a path.
                        if path:
                            rules.append((field == "allow", path))
                else:
                    logger.error(
                        "Line %d specifies %s rule without a preceding "
                        "user agent line; ignoring line",
                        lineno,
                        field,
                    )
            else:
                # Unknown fields are allowed for extensions.
                if field not in unknowns:
                    unknowns.add(field)
                    logger.info('Unknown field "%s" (line %d)', field, lineno)
    return result


def unescape_path(path: str) -> str:
    """
    Decodes a percent-encoded URL path.

    @raise ValueError:
        If the escaping is incorrect.
    """
    idx = 0
    while True:
        idx = path.find("%", idx)
        if idx == -1:
            return path

        # Percent escaping can be used for UTF-8 paths.
        start = idx
        data = []
        remaining: int = None  # type: ignore[assignment]
        while True:
            hex_num = path[idx + 1 : idx + 3]
            if len(hex_num) != 2:
                raise ValueError('incomplete escape, expected 2 characters after "%"')
            idx += 3

            try:
                if "-" in hex_num:
                    raise ValueError()
                value = int(hex_num, 16)
            except ValueError:
                raise ValueError(
                    f"incorrect escape: "
                    f'expected 2 hex digits after "%", got "{hex_num}"'
                ) from None
            data.append(value)

            if len(data) > 1:
                if (value & 0xC0) == 0x80:
                    remaining -= 1
                    if remaining == 0:
                        path = path[:start] + bytes(data).decode() + path[idx:]
                        break
                else:
                    raise ValueError(
                        f"invalid percent-encoded UTF8: "
                        f"expected 0x80..0xBF for non-first byte, got 0x{value:02X}"
                    )
            elif value == 0x2F:  # '/'
                # Path separator should remain escaped.
                path = path[:start] + "%2f" + path[idx:]
                break
            elif value < 0x80:
                path = path[:start] + chr(value) + path[idx:]
                break
            elif value < 0xC0 or value >= 0xF8:
                raise ValueError(
                    "invalid percent-encoded UTF8: "
                    f"expected 0xC0..0xF7 for first byte, got 0x{value:02X}"
                )
            elif value < 0xE0:
                remaining = 1
            elif value < 0xF0:
                remaining = 2
            else:
                assert value < 0xF8, value
                remaining = 3

            if idx == len(path) or path[idx] != "%":
                raise ValueError(
                    f"incomplete escaped UTF8 character, "
                    f"expected {remaining:d} more escaped bytes"
                )


def lookup_robots_rules(
    rules_map: Mapping[str, Iterable[tuple[bool, str]]], user_agent: str
) -> Iterable[tuple[bool, str]]:
    """
    Looks up a user agent in a rules mapping.

    @param rules_map:
        Rules mapping as produced by L{parse_robots_txt}.
    @param user_agent:
        Name of the user agent to look up in the rules.
    @return:
        C{rules: (allowed, url_prefix)*}
        The rules that apply to the given user agent.
    """

    user_agent = user_agent.casefold()
    for name, rules in rules_map.items():
        if name.startswith(user_agent):
            return rules
    return rules_map.get("*", [])


def path_allowed(path: str, rules: Iterable[tuple[bool, str]]) -> bool:
    """
    Checks whether the given rules allow visiting the given path.

    @param path:
        URL path component.
        Must not contain percent-encoded values other than C{%2f} (C{/}).
    @param rules:
        Rules as returned by L{lookup_robots_rules}.
    @return:
        C{True} iff C{path} is allowed by C{rules}.
    """

    # The draft RFC specifies that the first match should be used,
    # but both Google and Bing use the longest (most specific) match
    # instead. This means that in practice "longest match" will be
    # used by sites, so we'll follow that.
    result = True
    longest = 0
    for allow, prefix in rules:
        if path.startswith(prefix) and len(prefix) > longest:
            result = allow
            longest = len(prefix)
    return result
