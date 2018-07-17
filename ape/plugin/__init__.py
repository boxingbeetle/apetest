# SPDX-License-Identifier: BSD-3-Clause

"""APE's plugin infrastructure.

Each plugin is a separate module in the "ape.plugin" package.
Plugins can register command line options by defining the following
function:

    def plugin_arguments(parser):
        parser.add_argument('--cow', help='fetchez la vache')

The ``parser`` argument is an instance of `argparse.ArgumentParser`.
See the `argparse` documentation for a detailed description of what
kind of argument parsing it supports.

It is not mandatory to implement ``plugin_arguments()``, but in general
plugins should not activate automatically, so there should at least
be a command line argument to enable them.

To instantiate plugins, the plugin module must define the following
function:

    def plugin_create(args):
        if args.cow is not None:
            yield CatapultPlugin(args.cow)

`args` is an `argparse.Namespace` that contains the result of the
command line parsing.
Each yielded object must implement the `Plugin` interface.
If one of the requested plugins cannot be created, `PluginError` should
be raised with a message that is meaningful to the end user.
"""

from importlib import import_module
from logging import getLogger
from pkgutil import iter_modules

_LOG = getLogger(__name__)

class PluginError(Exception):
    """A plugin module can raise this in `plugin_create` when it fails
    to create the `Plugin` instances requested by the command line
    arguments.
    """
    pass

class Plugin:
    """Plugin interface: your plugin class should inherit this and override
    one or more methods.
    """

    def resource_loaded(self, data, content_type_header, report):
        """Called when a resource has been loaded.
        The resource contents are passed in `data` as `bytes`,
        while `content_type_header` is a `str` containing the full
        Content-Type header (including charset, if the server sent it).
        Plugins can override this method to perform checks on the raw
        resource data.
        The default implementation does nothing.
        """
        pass

    def report_added(self, report):
        """Called when the APE core has finished a `Report`.
        Plugins can override this method to act on the report data.
        The default implementation does nothing.
        """
        pass

    def postprocess(self, scribe):
        """Called when the APE core has finished a test run.
        Plugins can override this method to process the results.
        The default implementation does nothing.
        """
        pass

def load_plugins():
    """Finds and imports plugin modules, then yields the modules.
    Errors will be logged.
    """
    for finder_, name, ispkg_ in iter_modules(__path__, 'ape.plugin.'):
        try:
            yield import_module(name)
        except Exception: # pylint: disable=broad-except
            _LOG.exception('Error importing plugin module "%s":', name)

def add_plugin_arguments(module, parser):
    """Asks plugin `module` to register the plugin's command line arguments
    on `parser`, which is an instance of `argparse.ArgumentParser`.
    Errors will be logged.
    """
    try:
        func = getattr(module, 'plugin_arguments')
    except AttributeError:
        _LOG.info('Plugin module "%s" does not implement plugin_arguments()',
                  module.__name__)
    else:
        try:
            func(parser)
        except Exception: # pylint: disable=broad-except
            _LOG.exception('Error registering command line arguments for '
                           'plugin module "%s":', module.__name__)

def create_plugins(module, args):
    """Asks plugin `module` to create `Plugin` objects for the given
    command line arguments in `args` (`argparse.Namespace`).
    Errors will be logged and propagated.
    """
    try:
        func = getattr(module, 'plugin_create')
    except AttributeError:
        _LOG.error('Plugin module "%s" does not implement plugin_create()',
                   module.__name__)
        raise

    def _log_yield():
        try:
            yield from func(args)
        except PluginError as ex:
            _LOG.error('Could not instantiate plugin in module "%s": %s',
                       module.__name__, ex)
            raise
        except Exception: # pylint: disable=broad-except
            _LOG.exception('Error instantiating plugin module "%s":',
                           module.__name__)
            raise

    for plugin in _log_yield():
        if isinstance(plugin, Plugin):
            yield plugin
        else:
            _LOG.error('Module "%s" created a plugin of type "%s", '
                       'which does not inherit from the Plugin class.',
                       module.__name__, plugin.__class__.__name__)
            raise TypeError(plugin.__class__)
