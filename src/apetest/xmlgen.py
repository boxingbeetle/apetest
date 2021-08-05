# SPDX-License-Identifier: BSD-3-Clause

"""A friendly syntax to create XML in Python.

This is a system to generate strings in XML format. It does not provide
an editable document model or a templates. Instead, you create a tree
of XML objects and serialize it to a string.

An XML element can be created using the following syntax::

    xml.dish(style='recommended', id=123)[
        xml.spam['wonderful'],
        xml.egg(class_='large')
        ]

C{xml.I{name}} creates an XML element with the given name.
If the name is not a constant or contains for example a dash,
you can use the alternative syntax C{xml['I{tricky-name}']}.

Attributes are added to an element using keyword arguments. If an
argument's value is C{None}, that attribute will be omitted.
Argument values will be converted to strings if necessary.
Trailing underscores in names will be stripped off, which is
useful for names such as C{class} that are reserved in Python.

Nested content is added to an element using brackets. The following
types of content are supported:
  - XML objects: elements, character data and sequences
  - strings, which will be treated as character data
  - iterables (list, tuple, generator etc.) containing objects of the
    supported types; nested iterables are allowed
  - C{None}, which will be ignored
  - L{raw} objects, which contain text that will not be escaped

It is possible to derive an XML element from an existing one by
applying the attribute or nested content syntax to it. This will
produce a new XML element with updated attributes or added content;
the original element object will not be modified.

You can construct sequences of XML objects using the C{+} operator
or the L{concat} function. If you are creating a sequence of many
objects, L{concat} will perform better. The same conversion rules
for nested content are applied when creating sequences.

You can also create a sequence of XML objects using the L{join()} method
of any XML object, similar to Python's C{str.join()}::

    xml.br.join(lines)

To output the generated XML, you convert an XML object to a string
by calling its L{flatten()} method.

When an element is flattened, the generated XML will be well-formed,
assuming you used only allowed characters in element and attribute
names. Characters in attribute values and character data that have
a special meaning in XML will be automatically escaped.

The XML string will retain any Unicode characters that were put into
the XML tree. Therefore, if you want to write the generated XML as
bytes, you should either encode the string in a Unicode encoding such
as UTF-8, or escape Unicode characters that don't exist in the selected
encoding. For example::

    with open(name, 'w',
              encoding='ascii',
              errors='xmlcharrefreplace'
              ) as out:
        out.write(tree.flatten())
"""

from html import escape
from typing import Iterable, Iterator, Mapping, Optional, Union


class _XMLSerializable:
    """Base class for objects that can be serialized to XML."""

    def __str__(self) -> str:
        return self.flatten()

    def __add__(self, other: "XMLContent") -> "_XMLSequence":
        return concat(self, other)

    def __radd__(self, other: "XMLContent") -> "_XMLSequence":
        return concat(other, self)

    def _to_fragments(self) -> Iterator[str]:
        """Iterates through the fragments (strings) forming the XML
        serialization of this object: the XML serialization is the
        concatenation of all the fragments.
        """
        raise NotImplementedError

    def flatten(self) -> str:
        """Creates the XML string for this object."""
        return "".join(self._to_fragments())

    def join(self, siblings: Iterable["XMLContent"]) -> "_XMLSequence":
        """Creates an XML sequence containing the given XML objects,
        with itself inserted between each sibling, similar to
        C{str.join()}.
        """
        return _XMLSequence(_join(self, _adapt(siblings)))


XML = _XMLSerializable
XMLContent = Union[str, None, XML, Iterable]


def _join(separator: XML, nodes: Iterable[XML]) -> Iterator[XML]:
    iterator = iter(nodes)
    try:
        yield next(iterator)
    except StopIteration:
        return
    for node in iterator:
        yield separator
        yield node


class _Text(_XMLSerializable):
    def __init__(self, text: str):
        _XMLSerializable.__init__(self)
        self.__text = escape(text, quote=False)

    def _to_fragments(self) -> Iterator[str]:
        yield self.__text


class _Raw(_XMLSerializable):
    def __init__(self, text: str):
        _XMLSerializable.__init__(self)
        self.__text = text

    def _to_fragments(self) -> Iterator[str]:
        yield self.__text


def raw(text: str) -> XML:
    """Creates a segment that will appear in the output without escaping.

    This is useful to insert CDATA sections or CSS and JavaScript when
    outputting HTML that will not be parsed by an XML parser.
    """
    return _Raw(text)


class _XMLSequence(_XMLSerializable):
    def __init__(self, children: Iterable[XML]):
        """Creates an XML sequence.
        The given children, must all be _XMLSerializable instances;
        if that is not guaranteed, use _adapt() to convert.
        """
        _XMLSerializable.__init__(self)
        self.__children = tuple(children)

    def _to_fragments(self) -> Iterator[str]:
        for content in self.__children:
            # pylint: disable=protected-access
            # "content" is an instance of _XMLSerializable, so we are
            # allowed to access protected methods.
            yield from content._to_fragments()


class _XMLElement(_XMLSerializable):
    def __init__(
        self, name: str, attrs: Mapping[str, str], children: Optional[_XMLSequence]
    ):
        _XMLSerializable.__init__(self)
        self.__name = name
        self.__attributes = attrs
        self.__children = children

    def __call__(self, **attributes: Optional[str]) -> "_XMLElement":
        attrs = dict(self.__attributes)
        attrs.update(
            (key.rstrip("_"), escape(str(value)))
            for key, value in attributes.items()
            if value is not None
        )
        return _XMLElement(self.__name, attrs, self.__children)

    def __getitem__(self, index: XMLContent) -> "_XMLElement":
        children = concat(self.__children, index)
        return _XMLElement(self.__name, self.__attributes, children)

    def _to_fragments(self) -> Iterator[str]:
        attribs = self.__attributes
        attrib_str = (
            ""
            if attribs is None
            else "".join(' %s="%s"' % item for item in attribs.items())
        )
        children = self.__children
        if children is None:
            yield f"<{self.__name}{attrib_str} />"
        else:
            yield f"<{self.__name}{attrib_str}>"
            yield from children._to_fragments()  # pylint: disable=protected-access
            yield f"</{self.__name}>"


class _XMLElementFactory:
    """Automatically creates _XMLElement instances for any tag that is
    requested: if an attribute with a certain name is requested, a new
    _XMLElement with that same name is returned.
    """

    def __getattribute__(self, key: str) -> _XMLElement:
        return _XMLElement(key, {}, None)

    def __getitem__(self, key: str) -> _XMLElement:
        return _XMLElement(key, {}, None)


xml = _XMLElementFactory()  # pylint: disable=invalid-name
"""Factory for XML elements.

See the module level documentation for usage instructions.
"""


def _adapt(node: XMLContent) -> Iterator[XML]:
    if isinstance(node, _XMLSerializable):
        yield node
    elif isinstance(node, str):
        yield _Text(node)
    elif node is None:
        pass
    elif hasattr(node, "__iter__"):
        for child in node:
            yield from _adapt(child)
    else:
        raise TypeError(f"cannot handle node of type {type(node).__name__}")


def concat(*siblings: XMLContent) -> _XMLSequence:
    """Creates an XML sequence by concatenating C{siblings}.

    @raise TypeError:
        If one of the C{siblings} is neither an XML object nor convertible
        to XML.
    """
    return _XMLSequence(_adapt(siblings))


__all__ = ("xml", "raw", "concat")
