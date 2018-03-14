# SPDX-License-Identifier: BSD-3-Clause

class Control(object):
    '''A submittable element in a form.
    The alternative name = None, value = None represents a control not being
    part of the submission, for example an unchecked checkbox.
    '''

    def hasAlternative(self, name, value):
        '''Returns True iff the given name-value combination could be submitted
        by this control.
        Note that for free input controls, it is possible this method returns
        True while the name-value pair is not in the sequence returned by the
        "alternatives" method.
        '''
        raise NotImplementedError

    def alternatives(self):
        '''Returns a sequence containing all alternative name-value pairs of
        the ways this control can be submitted.
        For multiple-choice controls all possible alternatives are considered,
        for free input controls there is an infinite number of alternatives, so
        we just pick a few.
        '''
        raise NotImplementedError

class SingleValueControl(Control):

    def __init__(self, name, value):
        Control.__init__(self)
        self.name = name
        self.value = value

    def hasAlternative(self, name, value):
        return name == self.name and value == self.value

    def alternatives(self):
        yield self.name, self.value

class FileInput(SingleValueControl):
    '''A control for selecting and uploading files.
    '''

    def hasAlternative(self, name, value): # pylint: disable-msg=W0613
        # Any text could be submitted, so we only have to check the name.
        return name == self.name

    def alternatives(self):
        # Today's browsers, as a security precaution, will provide an empty
        # file name input field even if a default value is provided.
        # Since we have no idea what kind of file should be uploaded, we just
        # submit the empty string.
        yield self.name, ''

class HiddenInput(SingleValueControl):
    pass

class TextField(SingleValueControl):

    def hasAlternative(self, name, value): # pylint: disable-msg=W0613
        # Any text could be submitted, so we only have to check the name.
        return name == self.name

    def alternatives(self):
        yield self.name, '' # empty
        yield self.name, self.value # default
        yield self.name, 'ook' # librarian's choice

class TextArea(SingleValueControl):

    def hasAlternative(self, name, value): # pylint: disable-msg=W0613
        # Any text could be submitted, so we only have to check the name.
        return name == self.name

    def alternatives(self):
        yield self.name, '' # empty
        yield self.name, self.value # default
        yield self.name, 'Ook.\nOok? Ook!' # librarian's choice

class Checkbox(SingleValueControl):

    def hasAlternative(self, name, value):
        return (
            (name is None and value is None) or
            (name == self.name and value == self.value)
            )

    def alternatives(self):
        yield None, None # box unchecked
        yield self.name, self.value # box checked

class RadioButton(SingleValueControl):

    def hasAlternative(self, name, value): # pylint: disable-msg=W0613
        assert False, 'radio button "%s" was not merged' % self.name

    def alternatives(self):
        assert False, 'radio button "%s" was not merged' % self.name

class SubmitButton(SingleValueControl):
    pass

class RadioButtonGroup(Control):

    def __init__(self, buttons):
        # Perform sanity check on input and gather values.
        name = buttons[0].name
        values = []
        for button in buttons:
            if not isinstance(button, RadioButton):
                raise TypeError('expected RadioButton, got %s' % type(button))
            if button.name != name:
                raise ValueError(
                    'radio button name "%s" differs from '
                    'first radio button name "%s"'
                    % ( button.name, name )
                    )
            values.append(button.value)

        # Actual construction.
        Control.__init__(self)
        self.name = name
        self.values = values

    def hasAlternative(self, name, value):
        return name == self.name and value in self.values

    def alternatives(self):
        for value in self.values:
            yield self.name, value

class SubmitButtons(Control):

    def __init__(self, buttons):
        Control.__init__(self)
        self.buttons = tuple(
            ( button.name, button.value )
            for button in buttons
            )

    def hasAlternative(self, name, value):
        return ( name, value ) in self.buttons

    def alternatives(self):
        return self.buttons

class SelectMultiple(SingleValueControl):
    '''Pseudo-control which represents an option in a <select> control where
    multiple options can be active at the same time.
    '''

    def hasAlternative(self, name, value):
        return (
            (name is None and value is None) or
            (name == self.name and value == self.value)
            )

    def alternatives(self):
        yield None, None # not selected
        yield self.name, self.value # selected

class SelectSingle(Control):
    '''A <select> control where one option can be active at the same time.
    '''

    def __init__(self, name, options):
        Control.__init__(self)
        self.name = name
        self.options = options

    def hasAlternative(self, name, value):
        return (
            (name is None and value is None) or
            (name == self.name and value in self.options)
            )

    def alternatives(self):
        yield None, None # nothing selected
        for option in self.options:
            yield self.name, option
