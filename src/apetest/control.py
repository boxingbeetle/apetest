# SPDX-License-Identifier: BSD-3-Clause

"""Models form controls.

This module contains the L{Control} class and its subclasses, which can be
used to model input elements in an (HTML) form.
"""

# TODO: The subclasses currently have an almost 1:1 mapping to HTML,
#       but I'm not sure that is necessary. For example SelectMultiple
#       and Checkbox have the same submission functionality.
#       And SelectSingle and RadioButtonGroup differ only in whether
#       non-selection is possible; when adding support for the HTML5
#       "required" attribute, SelectSingle can become functionally
#       equivalent to RadioButtonGroup.

class Control:
    """Abstract base class for submittable elements in a form."""

    def has_alternative(self, name, value):
        """Return C{True} iff the given name-value combination could be
        submitted by this control.

        Note that for free-input controls, it is possible this method
        returns C{True} while the name-value pair is not in the sequence
        returned by the L{alternatives} method.
        """
        raise NotImplementedError

    def alternatives(self):
        """Yield alternative name-value pairs of the ways this control
        can be submitted.

        For multiple-choice controls all possible alternatives are included.
        For free-input controls there is an infinite number of alternatives,
        so we just pick a few.

        The alternative C{(None, None)} represents a control not being part
        of the submission, for example an unchecked checkbox.
        """
        raise NotImplementedError

class SingleValueControl(Control):
    """Control that produces at most one name-value combination.

    Note that there can be any number of possible values, but in each
    submission of the form, no more than one value is submitted for this
    control.
    """

    def __init__(self, name, value):
        """Initialize control with the given name-value combination."""
        Control.__init__(self)
        self.name = name
        """The name under which this control is submitted."""
        self.value = value
        """The default value for this control.

        Some control types can only submit this value,
        other control types can submit other values as well.
        """

    def has_alternative(self, name, value):
        return name == self.name and value == self.value

    def alternatives(self):
        yield self.name, self.value

class FileInput(SingleValueControl):
    """Control for selecting and uploading files."""

    def has_alternative(self, name, value):
        # Any text could be submitted, so we only have to check the name.
        return name == self.name

    def alternatives(self):
        # Today's browsers, as a security precaution, will provide an empty
        # file name input field even if a default value is provided.
        # Since we have no idea what kind of file should be uploaded, we just
        # submit the empty string.
        yield self.name, ''

class HiddenInput(SingleValueControl):
    """Control that is not visible to the user.

    This control submits its default value.
    """

class TextField(SingleValueControl):
    """Single-line text input."""

    def has_alternative(self, name, value):
        # Any text could be submitted, so we only have to check the name.
        return name == self.name

    def alternatives(self):
        yield self.name, '' # empty
        yield self.name, self.value # default
        yield self.name, 'ook' # librarian's choice

class TextArea(SingleValueControl):
    """Multi-line text input."""

    def has_alternative(self, name, value):
        # Any text could be submitted, so we only have to check the name.
        return name == self.name

    def alternatives(self):
        yield self.name, '' # empty
        yield self.name, self.value # default
        yield self.name, 'Ook.\nOok? Ook!' # librarian's choice

class Checkbox(SingleValueControl):
    """Checkbox.

    This control can submit its default value (box checked)
    or nothing (box unchecked).
    """

    def has_alternative(self, name, value):
        return (
            (name is None and value is None) or
            (name == self.name and value == self.value)
            )

    def alternatives(self):
        yield None, None # box unchecked
        yield self.name, self.value # box checked

class RadioButton(SingleValueControl):
    """Single radio button.

    Radio buttons must be combined in a L{RadioButtonGroup} control.
    """

    def has_alternative(self, name, value):
        assert False, f'radio button "{self.name}" was not merged'

    def alternatives(self):
        assert False, f'radio button "{self.name}" was not merged'

class RadioButtonGroup(Control):
    """Multiple-choice control containing one or more radio buttons."""

    def __init__(self, buttons):
        """Initialize a radio buttons group control containing C{buttons},
        which must be a non-empty sequence of L{RadioButton} objects.
        """

        # Perform sanity check on input and gather values.
        name = buttons[0].name
        values = []
        for button in buttons:
            if not isinstance(button, RadioButton):
                raise TypeError(
                    f'expected RadioButton, got {type(button).__name__}'
                    )
            if button.name != name:
                raise ValueError(
                    f'radio button name "{button.name}" differs from '
                    f'first radio button name "{name}"'
                    )
            values.append(button.value)

        # Actual construction.
        Control.__init__(self)
        self.name = name
        self.values = values

    def has_alternative(self, name, value):
        return name == self.name and value in self.values

    def alternatives(self):
        for value in self.values:
            yield self.name, value

class SubmitButton(SingleValueControl):
    """Single submit button.

    All submit buttons in a form must be combined in a L{SubmitButtons}
    control.
    """

class SubmitButtons(Control):
    """Pseudo-control which contains all submit buttons for a form.

    Only one submit button can be used for submission;
    this pseudo-control models the choice between submit buttons.
    """

    def __init__(self, buttons):
        """Initialize a submit buttons control containing C{buttons},
        which must be a sequence of L{SubmitButton} objects.
        """
        Control.__init__(self)
        self.buttons = tuple((button.name, button.value) for button in buttons)

    def has_alternative(self, name, value):
        return (name, value) in self.buttons

    def alternatives(self):
        yield from self.buttons

class SelectMultiple(SingleValueControl):
    """Pseudo-control which represents an option in a C{<select>} control
    where multiple options can be active at the same time.

    This type of control is typically shown in a browser as a list box.
    """

    def has_alternative(self, name, value):
        return (
            (name is None and value is None) or
            (name == self.name and value == self.value)
            )

    def alternatives(self):
        yield None, None # not selected
        yield self.name, self.value # selected

class SelectSingle(Control):
    """C{<select>} control where one option can be active at the same time.

    This type of control is typically shown in a browser as a drop-down list.
    """

    def __init__(self, name, options):
        """Initialize a single-choice C{<select>} control.

        @param name:
            The name under which this control is submitted.
        @param options:
            Sequence of all possible values for this control.
        """

        Control.__init__(self)
        self.name = name
        self.options = tuple(options)

    def has_alternative(self, name, value):
        return (
            (name is None and value is None) or
            (name == self.name and value in self.options)
            )

    def alternatives(self):
        yield None, None # nothing selected
        for option in self.options:
            yield self.name, option
