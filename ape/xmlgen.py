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
- an object that implements "toXML()"; that method should return an XML tree
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

from codecs import getencoder

_ASCII_ENCODER = getencoder('ASCII')
_TRANSLATION = ''.join(
    chr(c) if c > 32 and c < 127 or c in (9, 10, 13) else ' '
    for c in xrange(256)
    )
def _escape_xml(text):
    '''Converts special characters to XML entities.
    '''
    return _ASCII_ENCODER(
        text
        .replace('&', '&amp;')
        .replace('<', '&lt;')
        .replace('>', '&gt;')
        .replace('"', '&quot;'),
        'xmlcharrefreplace'
        )[0].translate(_TRANSLATION)

def _stringify(value):
    return value if isinstance(value, basestring) else str(value)

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
        '''Creates an XML sequence with the given siblings as children,
        with itself inserted between each sibling.
        This method is similar to str.join().
        '''
        sequence = _XMLSequence()
        first = True
        for sibling in siblings:
            if not first:
                sequence._add_child(self) # pylint: disable=protected-access
            sequence._add_child(sibling) # pylint: disable=protected-access
            first = False
        return sequence

class _Text(_XMLSerializable):

    def __init__(self, text):
        _XMLSerializable.__init__(self)
        self.__text = _escape_xml(text)

    def __cmp__(self, other):
        # pylint: disable=protected-access
        return not isinstance(other, _Text) \
            or cmp(self.__text, other.__text)

    def _to_fragments(self):
        yield self.__text

class _XMLSequence(_XMLSerializable):

    def __init__(self, children=None):
        '''Creates an XML sequence.
        The given children, if any, must all be _XMLSerializable instances;
        if that is not guaranteed, use _add_child() to add and convert.
        '''
        _XMLSerializable.__init__(self)
        self.__children = [] if children is None else list(children)

    def __cmp__(self, other):
        # pylint: disable=protected-access
        return not isinstance(other, _XMLSequence) \
            or cmp(self.__children, other.__children)

    def __add__(self, other):
        ret = _XMLSequence(self.__children)
        ret += other
        return ret

    def __radd__(self, other):
        ret = _XMLSequence()
        ret += other
        ret.__children += self.__children # pylint: disable=protected-access
        return ret

    def __iadd__(self, other):
        self._add_child(other)
        return self

    def _add_child(self, child):
        if isinstance(child, _XMLSerializable):
            self.__children.append(child)
        elif hasattr(child, 'toXML'):
            self.__children.append(child.toXML())
        elif isinstance(child, basestring):
            self.__children.append(_Text(child))
        elif hasattr(child, '__iter__'):
            for grand_child in child:
                self._add_child(grand_child)
        elif child is None:
            pass
        else:
            raise TypeError(
                'cannot handle child of type %s' % type(child)
                )

    def _to_fragments(self):
        for content in self.__children:
            # pylint: disable=protected-access
            # "content" is an instance of _XMLSerializable, so we are
            # allowed to access protected methods.
            for fragment in content._to_fragments():
                yield fragment

class _XMLNode(_XMLSerializable):

    __emptySequence = _XMLSequence()

    def __init__(self, name):
        _XMLSerializable.__init__(self)
        self.__name = name
        self.__attributes = None
        self.__children = None

    def __call__(self, **attributes):
        assert self.__attributes is None
        self.__attributes = dict(
            (key.rstrip('_'), _escape_xml(_stringify(value)))
            for key, value in attributes.iteritems()
            if value is not None
            )
        return self

    def __getitem__(self, index):
        # TODO: Consider returning a new object instead of self.
        #       Then we could make _XMLNodes immutable, which enables certain
        #       optimizations, such as precalculating the flattening.
        assert self.__children is None
        self.__children = children = _XMLSequence()
        children._add_child(index) # pylint: disable=protected-access
        return self

    def __cmp__(self, other):
        # Note: None for attributes or children should be considered
        #       equivalent to empty.
        # pylint: disable=protected-access
        return not isinstance(other, _XMLNode) \
            or cmp(self.__name, other.__name) \
            or cmp(self.__attributes or {}, other.__attributes or {}) \
            or cmp(self.__children or self.__emptySequence,
                   other.__children or self.__emptySequence)

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
            ' %s="%s"' % item for item in attribs.iteritems()
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

    def __cmp__(self, other):
        # pylint: disable=protected-access
        return not isinstance(other, _NamedEntity) \
            or cmp(self.__name, other.__name)

    def _to_fragments(self):
        return '&%s;' % self.__name,

class _NumericEntity(_XMLSerializable):

    def __init__(self, number):
        _XMLSerializable.__init__(self)
        self.__number = number

    def __cmp__(self, other):
        # pylint: disable=protected-access
        return not isinstance(other, _NumericEntity) \
            or cmp(self.__number, other.__number)

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
        if not isinstance(text, basestring):
            raise TypeError(
                'text should be a string, got %s' % type(text).__name__
                )
        _XMLSerializable.__init__(self)
        self.__text = text
        self.__comment = bool(comment)

    def __cmp__(self, other):
        # pylint: disable=protected-access
        return not isinstance(other, _CData) \
            or cmp(self.__text, other.__text) \
            or cmp(self.__comment, other.__comment)

    def _to_fragments(self):
        comment = self.__comment
        yield '/*<![CDATA[*/' if comment else '<![CDATA['
        yield self.__text
        yield '/*]]>*/' if comment else ']]>'

def concat(*siblings):
    '''Creates an XML sequence containing the given siblings.
    '''
    sequence = _XMLSequence()
    sequence._add_child(siblings) # pylint: disable=protected-access
    return sequence

# pylint: disable=invalid-name
xml = _XMLNodeFactory()
ent = _EntityFactory()
txt = _Text
cdata = _CData
