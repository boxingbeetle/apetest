# SPDX-License-Identifier: BSD-3-Clause

"""
APE's plugin infrastructure.

Each plugin is a separate module in the L{apetest.plugin} package.
Plugins can register command line options by defining the
following function::

    def plugin_arguments(parser):
        parser.add_argument('--cow', help='fetchez la vache')

The C{parser} argument is an instance of L{ArgumentParser}.
See the L{argparse} documentation for a detailed description of what
kind of argument parsing it supports.

It is not mandatory to implement C{plugin_arguments()}, but in general
plugins should not activate automatically, so there should at least
be a command line argument to enable them.

To instantiate plugins, the plugin module must define the
following function::

    def plugin_create(args):
        if args.cow is not None:
            yield CatapultPlugin(args.cow)

C{args} is an L{Namespace} that contains the result of the
command line parsing.
Each yielded object must implement the L{Plugin} interface.
If one of the requested plugins cannot be created, L{PluginError} should
be raised with a message that is meaningful to the end user.
"""

from argparse import ArgumentParser, Namespace
from importlib import import_module
from logging import getLogger
from pkgutil import iter_modules
from types import ModuleType
from typing import TYPE_CHECKING, Callable, Iterable, Iterator, List

if TYPE_CHECKING:
    # pylint: disable=cyclic-import
    from apetest.report import Report, Scribe
else:
    Report = Scribe = object


_LOG = getLogger(__name__)


class PluginError(Exception):
    """
    A plugin module can raise this in C{plugin_create()} when it fails
    to create the L{Plugin} instances requested by the command line
    arguments.
    """


class Plugin:
    """
    Plugin interface: your plugin class should inherit this and override
    one or more methods.
    """

    def close(self) -> None:
        """
        Tells the plugin to release any resources (processes, sockets
        etc.) that it may have acquired.

        There will not be any more calls to the plugin after it is closed.
        The default implementation does nothing.
        """

    def resource_loaded(
        self, data: bytes, content_type_header: str, report: Report
    ) -> None:
        """
        Called when a resource has been loaded.

        Plugins can override this method to perform checks on the raw
        resource data. The default implementation does nothing.

        @param data:
            The resource contents.
        @param content_type_header:
            The HTTP C{Content-Type} header received for this resource,
            including C{charset} if the server sent it.
        @param report:
            Report to which problems found in the resource can be logged.
        """

    def report_added(self, report: Report) -> None:
        """
        Called when a L{Report} has been finished.

        Plugins can override this method to act on the report data.
        The default implementation does nothing.
        """

    def postprocess(self, scribe: Scribe) -> None:
        """
        Called when the test run has finished.

        Plugins can override this method to process the results.
        The default implementation does nothing.
        """


if TYPE_CHECKING:
    PluginCollectionBase = Plugin
else:
    PluginCollectionBase = object


class PluginCollection(PluginCollectionBase):
    """
    Keeps a collection of L{Plugin} instances and dispatches calls to
    each of them.
    """

    def __init__(self, plugins: Iterable[Plugin]):
        """Initialize a collection containing C{plugins}."""
        self.plugins = tuple(plugins)

    if not TYPE_CHECKING:

        def __getattr__(self, name):
            if hasattr(Plugin, name):
                return self.__dispatch(name)
            else:
                raise AttributeError(name)

        def __dispatch(self, name):
            def dispatch(*args, **kvargs):
                for plugin in self.plugins:
                    getattr(plugin, name)(*args, **kvargs)

            return dispatch


# Work around mypy not knowing about __path__.
#   https://github.com/python/mypy/issues/1422
if TYPE_CHECKING:
    __path__: List[str]


def load_plugins() -> Iterator[ModuleType]:
    """
    Discover and import plugin modules.

    Errors will be logged to the default logger.

    @return: Yields the imported plugin modules.
    """

    for finder_, name, ispkg_ in iter_modules(__path__, "apetest.plugin."):
        try:
            yield import_module(name)
        except Exception:  # pylint: disable=broad-except
            _LOG.exception('Error importing plugin module "%s":', name)


def add_plugin_arguments(module: ModuleType, parser: ArgumentParser) -> None:
    """
    Ask a plugin module to register its command line arguments.

    Errors will be logged to the default logger.

    @param module:
        Plugin module.
    @param parser:
        Command line parser on which arguments must be registered.
    """

    func: Callable[[ArgumentParser], None]
    try:
        func = getattr(module, "plugin_arguments")
    except AttributeError:
        _LOG.info(
            'Plugin module "%s" does not implement plugin_arguments()', module.__name__
        )
    else:
        try:
            func(parser)
        except Exception:  # pylint: disable=broad-except
            # TODO: Perhaps it is better to disable the plugin when this happens,
            #       since it's unlikely to function correctly.
            _LOG.exception(
                "Error registering command line arguments for " 'plugin module "%s":',
                module.__name__,
            )


def create_plugins(module: ModuleType, args: Namespace) -> Iterator[Plugin]:
    """
    Ask a plugin module to create L{Plugin} objects according to
    the command line arguments.

    Errors will be logged to the default logger.
    Exceptions will be re-raised after logging.

    @param module:
        Plugin module.
    @param args:
        Parsed command line arguments.
    """

    func: Callable[[Namespace], Iterator[Plugin]]
    try:
        func = getattr(module, "plugin_create")
    except AttributeError:
        _LOG.error(
            'Plugin module "%s" does not implement plugin_create()', module.__name__
        )
        raise

    def _log_yield() -> Iterable[object]:
        try:
            yield from func(args)
        except PluginError as ex:
            _LOG.error(
                'Could not instantiate plugin in module "%s": %s', module.__name__, ex
            )
        except Exception:  # pylint: disable=broad-except
            _LOG.exception('Error instantiating plugin module "%s":', module.__name__)

    for plugin in _log_yield():
        if isinstance(plugin, Plugin):
            yield plugin
        else:
            _LOG.error(
                'Module "%s" created a plugin of type "%s", '
                "which does not inherit from the Plugin class.",
                module.__name__,
                plugin.__class__.__name__,
            )
            raise TypeError(plugin.__class__)
