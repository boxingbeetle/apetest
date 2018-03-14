# SPDX-License-Identifier: BSD-3-Clause

class Plugin(object):
    '''Abstract plugin: your plugin class should inherit this and override
    one or more methods.
    '''

    def __init__(self):
        pass

    def reportAdded(self, report):
        pass

    def postProcess(self, scribe):
        pass

class PluginError(Exception):
    '''Raised when plugin loading or initialisation fails.
    '''
    pass

def loadPlugins(pluginSpec):
    '''Load and initialise plugins according to the given spec string.
    The spec string has the format <module>(#<name>=<value>)*.
    Generates instances of the plugin classes.
    Raises PluginError if a plugin could not be loaded and initialised.
    '''
    # Parse spec string.
    parts = pluginSpec.split('#')
    pluginName = parts[0]
    args = {}
    for part in parts[1 : ]:
        try:
            name, value = part.split('=')
        except ValueError:
            raise PluginError(
                'Invalid argument for plugin "%s": '
                'expected "<name>=<value>", got "%s"'
                % (pluginName, part)
                )
        args[name] = value

    # Load plugin module.
    try:
        pluginModule = __import__(pluginName)
    except ImportError, ex:
        raise PluginError(
            'Could not load plugin module: "%s".\n'
            '  %s'
            % (pluginName, ex)
            )

    # Search module for plugin classes.
    newPlugins = []
    for attrName in dir(pluginModule):
        attr = getattr(pluginModule, attrName)
        try:
            if issubclass(attr, Plugin) and attr is not Plugin:
                newPlugins.append(attr)
        except TypeError:
            pass
    if not newPlugins:
        raise PluginError(
            'No subclasses of "Plugin" found in module "%s"' % pluginName
            )

    # Build a list of all arguments accepted by plugin constructors.
    acceptedArgs = set()
    for plugin in newPlugins:
        ctor = plugin.__init__
        ctorArgs = ctor.func_code.co_varnames[ : ctor.func_code.co_argcount]
        if ctorArgs[0] != 'self':
            raise PluginError(
                'First argument to constructor of "%s.%s" '
                'is "%s" instead of "self"'
                % (pluginName, plugin.__name__, ctorArgs[0])
                )
        acceptedArgs |= set(ctorArgs[1 : ])

    # Check for arguments that are not accepted by any constructor.
    for name in sorted(args.iterkeys()):
        if name not in acceptedArgs:
            raise PluginError(
                'No plugin constructor in "%s" accepts argument "%s"'
                % (pluginName, name)
                )

    # Instantiate plugin classes.
    for plugin in newPlugins:
        ctor = plugin.__init__
        nrCtorArgs = ctor.func_code.co_argcount
        nrMandatoryCtorArgs = nrCtorArgs - len(ctor.func_defaults or ())
        ctorArgs = ctor.func_code.co_varnames[ : nrCtorArgs]
        missingArgs = set(
            arg
            for arg in ctorArgs[1 : nrMandatoryCtorArgs]
            if arg not in args
            )
        if missingArgs:
            raise PluginError(
                'Missing mandatory argument%s '
                'for plugin constructor "%s.%s": %s'
                % (
                    '' if len(missingArgs) == 1 else 's',
                    pluginName, plugin.__name__,
                    ', '.join('"%s"' % arg for arg in sorted(missingArgs))
                    )
                )
        filteredArgs = dict(
            (name, value)
            for name, value in args.iteritems()
            if name in ctorArgs[1 : ]
            )
        instance = plugin(**filteredArgs)
        yield instance
