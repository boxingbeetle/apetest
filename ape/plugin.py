# SPDX-License-Identifier: BSD-3-Clause

class Plugin(object):
    '''Abstract plugin: your plugin class should inherit this and override
    one or more methods.
    '''

    def __init__(self):
        pass

    def report_added(self, report):
        pass

    def postprocess(self, scribe):
        pass

class PluginError(Exception):
    '''Raised when plugin loading or initialisation fails.
    '''
    pass

def load_plugins(spec):
    '''Load and initialise plugins according to the given spec string.
    The spec string has the format <module>(#<name>=<value>)*.
    Generates instances of the plugin classes.
    Raises PluginError if a plugin could not be loaded and initialised.
    '''
    # Parse spec string.
    parts = spec.split('#')
    module_name = parts[0]
    args = {}
    for part in parts[1 : ]:
        try:
            name, value = part.split('=')
        except ValueError:
            raise PluginError(
                'Invalid argument for plugin "%s": '
                'expected "<name>=<value>", got "%s"'
                % (module_name, part)
                )
        args[name] = value

    # Load plugin module.
    try:
        module = __import__(module_name)
    except ImportError as ex:
        raise PluginError(
            'Could not load plugin module: "%s".\n'
            '  %s'
            % (module_name, ex)
            )

    # Search module for plugin classes.
    new_plugins = []
    for name in dir(module):
        attr = getattr(module, name)
        try:
            if issubclass(attr, Plugin) and attr is not Plugin:
                new_plugins.append(attr)
        except TypeError:
            pass
    if not new_plugins:
        raise PluginError(
            'No subclasses of "Plugin" found in module "%s"' % module_name
            )

    # Build a list of all arguments accepted by plugin constructors.
    accepted_args = set()
    for plugin in new_plugins:
        ctor = plugin.__init__
        ctor_args = ctor.func_code.co_varnames[ : ctor.func_code.co_argcount]
        if ctor_args[0] != 'self':
            raise PluginError(
                'First argument to constructor of "%s.%s" '
                'is "%s" instead of "self"'
                % (module_name, plugin.__name__, ctor_args[0])
                )
        accepted_args |= set(ctor_args[1 : ])

    # Check for arguments that are not accepted by any constructor.
    for name in sorted(args.iterkeys()):
        if name not in accepted_args:
            raise PluginError(
                'No plugin constructor in "%s" accepts argument "%s"'
                % (module_name, name)
                )

    # Instantiate plugin classes.
    for plugin in new_plugins:
        ctor = plugin.__init__
        num_ctor_args = ctor.func_code.co_argcount
        num_mandatory_ctor_args = num_ctor_args - len(ctor.func_defaults or ())
        ctor_args = ctor.func_code.co_varnames[:num_ctor_args]
        missing_args = set(
            arg
            for arg in ctor_args[1:num_mandatory_ctor_args]
            if arg not in args
            )
        if missing_args:
            raise PluginError(
                'Missing mandatory argument%s '
                'for plugin constructor "%s.%s": %s'
                % (
                    '' if len(missing_args) == 1 else 's',
                    module_name, plugin.__name__,
                    ', '.join('"%s"' % arg for arg in sorted(missing_args))
                    )
                )
        filtered_args = dict(
            (name, value)
            for name, value in args.iteritems()
            if name in ctor_args[1 : ]
            )
        instance = plugin(**filtered_args)
        yield instance
