# SPDX-License-Identifier: BSD-3-Clause

'''XML generation library: a friendly syntax to create XML in Python.

The syntax is very similar to Nevow's Stan, but the goals and the design are
different:
- Python 2.4 is required
- XML trees are not templates: they are expanded upon initialisation
- more types are accepted as children, including nested sequences,
  and generators
- there are no predefined tag names, so you can define any XML you like,
  not just XHTML
- trailing underscores in attribute names are stripped off, so you can create
  for example a "class" attribute by passing "class_"
TODO: Look again at today's Stan, I think it has changed and there are less
      differences now. The main difference remains though: no templating.

To create an XML tree (data structure consisting of nested XMLNodes):
  from xmlgen import xml
  xml.<tagname>(<attributes>)[<nested elements>]
where attributes are keyword arguments.
If the tag name contains a minus or is not a constant, you can use the
alternative syntax "xml['tag-name']".
The empty XML tree is represented by None.
The nested elements are one or more elements of the following types:
- other XML trees
- a string (unicode or ASCII)
- an iterable object (list, tuple, generator etc)
  the items from the iterable can be of the same types as the nested elements:
  they are added recursively

Sequences of XML trees are also possible:
- separator.join(trees)
- concat(*trees)
- concat(tree1, tree2)
- tree1 + tree2
If you are creating a long sequence, concat() will perform better than addition.
'''

from html import escape

def _stringify(value):
    return value if isinstance(value, str) else str(value)

def _join(separator, nodes):
    iterator = iter(nodes)
    try:
        yield next(iterator)
    except StopIteration:
        return
    for node in iterator:
        yield separator
        yield node

class _XMLSerializable(object):
    '''Base class for objects that can be serialized to XML.
    '''

    def __str__(self):
        return self.flatten()

    def _to_fragments(self):
        '''Iterates through the fragments (strings) forming the XML
        serialization of this object: the XML serialization is the
        concatenation of all the fragments.
        '''
        raise NotImplementedError

    def flatten(self):
        return ''.join(self._to_fragments())

    def join(self, siblings):
        '''Creates an XML sequence with the given XML nodes as children,
        with itself inserted between each sibling.
        This method is similar to str.join().
        '''
        return _XMLSequence(_join(self, _adapt(siblings)))

class _Text(_XMLSerializable):

    def __init__(self, text):
        _XMLSerializable.__init__(self)
        self.__text = escape(text, quote=False)

    def _to_fragments(self):
        yield self.__text

class _XMLSequence(_XMLSerializable):

    def __init__(self, children):
        '''Creates an XML sequence.
        The given children, must all be _XMLSerializable instances;
        if that is not guaranteed, use _adapt() to convert.
        '''
        _XMLSerializable.__init__(self)
        self.__children = tuple(children)

    def __add__(self, other):
        return concat(self, other)

    def __radd__(self, other):
        return concat(other, self)

    def _to_fragments(self):
        for content in self.__children:
            # pylint: disable=protected-access
            # "content" is an instance of _XMLSerializable, so we are
            # allowed to access protected methods.
            for fragment in content._to_fragments():
                yield fragment

class _XMLNode(_XMLSerializable):

    def __init__(self, name):
        _XMLSerializable.__init__(self)
        self.__name = name
        self.__attributes = None
        self.__children = None

    def __call__(self, **attributes):
        assert self.__attributes is None
        self.__attributes = dict(
            (key.rstrip('_'), escape(_stringify(value)))
            for key, value in attributes.items()
            if value is not None
            )
        return self

    def __getitem__(self, index):
        # TODO: Consider returning a new object instead of self.
        #       Then we could make _XMLNodes immutable, which enables certain
        #       optimizations, such as precalculating the flattening.
        assert self.__children is None
        self.__children = _XMLSequence(_adapt(index))
        return self

    def __add__(self, other):
        return concat(self, other)

    def __radd__(self, other):
        return concat(other, self)

    def __iadd__(self, other):
        # Like strings, we consider a single element as a sequence of one.
        return concat(self, other)

    def _to_fragments(self):
        attribs = self.__attributes
        attrib_str = '' if attribs is None else ''.join(
            ' %s="%s"' % item for item in attribs.items()
            )
        children = self.__children
        if children is None:
            yield '<%s%s />' % (self.__name, attrib_str)
        else:
            yield '<%s%s>' % (self.__name, attrib_str)
            for fragment in children._to_fragments(): # pylint: disable=protected-access
                yield fragment
            yield '</%s>' % self.__name

class _XMLNodeFactory(object):
    '''Automatically creates _XMLNode instances for any tag that is requested:
    if an attribute with a certain name is requested, a new _XMLNode with that
    same name is returned.
    '''

    def __getattribute__(self, key):
        return _XMLNode(key)

    def __getitem__(self, key):
        return _XMLNode(key)

class _NamedEntity(_XMLSerializable):

    def __init__(self, name):
        _XMLSerializable.__init__(self)
        self.__name = name

    def _to_fragments(self):
        return '&%s;' % self.__name,

class _NumericEntity(_XMLSerializable):

    def __init__(self, number):
        _XMLSerializable.__init__(self)
        self.__number = number

    def _to_fragments(self):
        return '&#0x%X;' % self.__number,

class _EntityFactory(object):
    '''Automatically creates Entity instances for any entity that is requested:
    if an attribute with a certain name is requested, a new Entity with that
    same name is returned.
    For numerical entities, you can use "ent[number]" instead.
    '''

    def __getattribute__(self, key):
        return _NamedEntity(key)

    def __getitem__(self, key):
        return _NumericEntity(key)

class _CData(_XMLSerializable):
    '''Defines a CDATA section: XML character data that is not parsed to look
    for entities or elements.
    This can be used to embed JavaScript or CSS in pages.
    '''

    def __init__(self, text, comment=False):
        if not isinstance(text, str):
            raise TypeError(
                'text should be a string, got %s' % type(text).__name__
                )
        _XMLSerializable.__init__(self)
        self.__text = text
        self.__comment = bool(comment)

    def _to_fragments(self):
        comment = self.__comment
        yield '/*<![CDATA[*/' if comment else '<![CDATA['
        yield self.__text
        yield '/*]]>*/' if comment else ']]>'

def _adapt(node):
    if isinstance(node, _XMLSerializable):
        yield node
    elif isinstance(node, str):
        yield _Text(node)
    elif hasattr(node, '__iter__'):
        for child in node:
            yield from _adapt(child)
    elif node is None:
        pass
    else:
        raise TypeError('cannot handle node of type %s' % type(node))

def concat(*siblings):
    '''Creates an XML sequence containing the given XML nodes.
    '''
    return _XMLSequence(_adapt(siblings))

# pylint: disable=invalid-name
xml = _XMLNodeFactory()
ent = _EntityFactory()
txt = _Text
cdata = _CData
