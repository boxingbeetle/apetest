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

_asciiencode = getencoder('ASCII')
_translation = ''.join(
    (' ', chr(c))[c > 32 and c < 127 or c in (9, 10, 13)]
    for c in xrange(0, 256)
    )
def _escapeXML(text):
    '''Converts special characters to XML entities.
    '''
    return _asciiencode(
        text.replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;'),
        'xmlcharrefreplace'
        )[0].translate(_translation)

def _checkType(value, types):
    if not isinstance(value, types):
        raise TypeError(type(value))

def _normalizeValue(value):
    if isinstance(value, basestring):
        return value
    else:
        return str(value)

def validAsXMLChild(obj):
    '''Returns True iff the given object is valid as a child of an XML node.
    '''
    return (
        isinstance(obj, (_XMLSerializable, basestring))
        or hasattr(obj, 'toXML')
        or hasattr(obj, '__iter__')
        or obj is None
        )

class _XMLSerializable(object):
    '''Base class for objects that can be serialized to XML.
    '''

    def __str__(self):
        return self.flatten()

    def _toFragments(self):
        '''Iterates through the fragments (strings) forming the XML
        serialization of this object: the XML serialization is the
        concatenation of all the fragments.
        '''
        raise NotImplementedError

    def flatten(self):
        return ''.join(self._toFragments())

    def flattenIndented(self):
        indentedFragments = []
        indent = '\n'
        prevWasElem = False
        for fragment in self._toFragments():
            close = fragment.startswith('</')
            open_ = not close and fragment.startswith('<')
            if close:
                indent = indent[ : -2]
            if open_ and fragment.endswith('/>'):
                close = True
            thisIsElem = open_ or close
            if prevWasElem and thisIsElem:
                indentedFragments.append(indent)
            indentedFragments.append(fragment)
            if open_ and not close:
                indent += '  '
            prevWasElem = thisIsElem
        indentedFragments.append('\n')
        return ''.join(indentedFragments)

    def join(self, siblings):
        '''Creates an XML sequence with the given siblings as children,
        with itself inserted between each sibling.
        This method is similar to str.join().
        '''
        sequence = _XMLSequence()
        first = True
        for sibling in siblings:
            if not first:
                sequence._addChild(self) # pylint: disable=protected-access
            sequence._addChild(sibling) # pylint: disable=protected-access
            first = False
        return sequence

class Text(_XMLSerializable):

    def __init__(self, text):
        _XMLSerializable.__init__(self)
        self.__text = _escapeXML(text)

    def __cmp__(self, other):
        # pylint: disable=protected-access
        return not isinstance(other, Text) \
            or cmp(self.__text, other.__text)

    def _toFragments(self):
        yield self.__text

class _XMLSequence(_XMLSerializable):

    def __init__(self, children = None):
        '''Creates an XML sequence.
        The given children, if any, must all be _XMLSerializable instances;
        if that is not guaranteed, use _addChild() to add and convert.
        '''
        _XMLSerializable.__init__(self)
        if children is None:
            self.__children = []
        else:
            self.__children = list(children)

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
        self._addChild(other)
        return self

    def _addChild(self, child):
        # Note: If you add a type here, add it in validAsXMLChild as well.
        if isinstance(child, _XMLSerializable):
            self.__children.append(child)
        elif hasattr(child, 'toXML'):
            self.__children.append(child.toXML())
        elif isinstance(child, basestring):
            self.__children.append(Text(child))
        elif hasattr(child, '__iter__'):
            for grandChild in child:
                self._addChild(grandChild)
        elif child is None:
            pass
        else:
            raise TypeError(
                'cannot handle child of type %s' % type(child)
                )

    def _toFragments(self):
        for content in self.__children:
            # pylint: disable=protected-access
            # "content" is an instance of _XMLSerializable, so we are
            # allowed to access protected methods.
            for fragment in content._toFragments():
                yield fragment

class XMLNode(_XMLSerializable):

    __emptySequence = _XMLSequence()

    def __init__(self, name):
        _XMLSerializable.__init__(self)
        self.__name = name
        self.__attributes = None
        self.__children = None

    def __call__(self, **attributes):
        assert self.__attributes is None
        self.__attributes = dict(
            ( key.rstrip('_'), _escapeXML(_normalizeValue(value)) )
            for key, value in attributes.iteritems()
            if value is not None
            )
        return self

    def __getitem__(self, index):
        # TODO: Consider returning a new object instead of self.
        #       Then we could make XMLNodes immutable, which enables certain
        #       optimizations, such as precalculating the flattening.
        assert self.__children is None
        self.__children = children = _XMLSequence()
        children._addChild(index) # pylint: disable=protected-access
        return self

    def __cmp__(self, other):
        # Note: None for attributes or children should be considered
        #       equivalent to empty.
        # pylint: disable=protected-access
        return not isinstance(other, XMLNode) \
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

    def _toFragments(self):
        attribs = self.__attributes
        if attribs is None:
            attribStr = ''
        else:
            attribStr = ''.join(
                ' %s="%s"' % item
                for item in attribs.iteritems()
                )
        children = self.__children
        if children is None:
            yield '<%s%s />' % ( self.__name, attribStr )
        else:
            yield '<%s%s>' % ( self.__name, attribStr )
            for fragment in children._toFragments(): # pylint: disable=protected-access
                yield fragment
            yield '</%s>' % self.__name

class XMLNodeFactory(object):
    '''Automatically creates XMLNode instances for any tag that is requested:
    if an attribute with a certain name is requested, a new XMLNode with that
    same name is returned.
    '''

    def __getattribute__(self, key):
        return XMLNode(key)

    def __getitem__(self, key):
        return XMLNode(key)

class NamedEntity(_XMLSerializable):

    def __init__(self, name):
        _XMLSerializable.__init__(self)
        self.__name = name

    def __cmp__(self, other):
        # pylint: disable=protected-access
        return not isinstance(other, NamedEntity) \
            or cmp(self.__name, other.__name)

    def _toFragments(self):
        return '&%s;' % self.__name,

class NumericEntity(_XMLSerializable):

    def __init__(self, number):
        _XMLSerializable.__init__(self)
        self.__number = number

    def __cmp__(self, other):
        # pylint: disable=protected-access
        return not isinstance(other, NumericEntity) \
            or cmp(self.__number, other.__number)

    def _toFragments(self):
        return '&#0x%X;' % self.__number,

class EntityFactory(object):
    '''Automatically creates Entity instances for any entity that is requested:
    if an attribute with a certain name is requested, a new Entity with that
    same name is returned.
    For numerical entities, you can use "ent[number]" instead.
    '''

    def __getattribute__(self, key):
        return NamedEntity(key)

    def __getitem__(self, key):
        return NumericEntity(key)

class CData(_XMLSerializable):
    '''Defines a CDATA section: XML character data that is not parsed to look
    for entities or elements.
    This can be used to embed JavaScript or CSS in pages.
    '''

    def __init__(self, text, comment = False):
        _checkType(text, basestring)
        _checkType(comment, bool)
        _XMLSerializable.__init__(self)
        self.__text = text
        self.__comment = comment

    def __cmp__(self, other):
        # pylint: disable=protected-access
        return not isinstance(other, CData) \
            or cmp(self.__text, other.__text) \
            or cmp(self.__comment, other.__comment)

    def _toFragments(self):
        if self.__comment:
            yield '/*<![CDATA[*/'
        else:
            yield '<![CDATA['
        yield self.__text
        if self.__comment:
            yield '/*]]>*/'
        else:
            yield ']]>'

def concat(*siblings):
    '''Creates an XML sequence containing the given siblings.
    '''
    sequence = _XMLSequence()
    sequence._addChild(siblings) # pylint: disable=protected-access
    return sequence

xml = XMLNodeFactory()
ent = EntityFactory()
txt = Text
cdata = CData
