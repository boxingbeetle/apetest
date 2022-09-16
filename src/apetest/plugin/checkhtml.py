# SPDX-License-Identifier: BSD-3-Clause

"""
Plugin that checks HTML and optionally CSS.

The actual checking is done by the Nu Html Checker (v.Nu).
Download the checker from U{https://validator.github.io/}
or install the C{html5validator} package with C{pip}.

The checker is written in Java, so you must have a Java runtime (JRE)
installed to run it.
"""

from argparse import ArgumentParser, Namespace
from cgi import parse_header
from http.client import HTTPException
from logging import ERROR, INFO, WARNING
from pathlib import Path
from socket import AF_INET, SOCK_STREAM, socket  # pylint: disable=no-name-in-module
from subprocess import DEVNULL, Popen
from typing import TYPE_CHECKING, Any, Container, Iterator, Mapping, Optional, Tuple

from apetest.plugin import Plugin, PluginError
from apetest.report import Checked
from apetest.vnuclient import VNUClient
from apetest.xmlgen import XMLContent, concat, xml

if TYPE_CHECKING:
    # pylint: disable=cyclic-import
    from apetest.report import Report
else:
    Report = object


def plugin_arguments(parser: ArgumentParser) -> None:
    parser.add_argument(
        "--check",
        metavar="PORT|URL|launch",
        help="check HTML using v.Nu web service at PORT (localhost) or "
        "URL (remote), or launch a new instance",
    )
    parser.add_argument(
        "--css", action="store_true", help="check CSS using v.Nu web service as well"
    )


def _pick_port() -> int:
    """
    Returns an unused TCP port.
    While we can not guarantee it will stay unused, it is very unlikely
    that it will become used within a few seconds.
    """
    with socket(AF_INET, SOCK_STREAM) as sock:
        sock.bind(("", 0))
        port: int = sock.getsockname()[1]
        return port


def _find_vnujar() -> Path:
    """Returns the full path to "vnu.jar".
    Raises PluginError if "vnu.jar" cannot be found.
    """
    try:
        import vnujar  # pylint: disable=import-outside-toplevel
    except ImportError as ex:
        raise PluginError(
            'Please install the "vnujar" module, for example using '
            '"pip3 install html5validator"'
        ) from ex
    jar_path = Path(vnujar.__file__).with_name("vnu.jar")
    if not jar_path.exists():
        raise PluginError('The "vnujar" module exists, but does not contain "vnu.jar"')
    return jar_path


def _launch_service(jar_path: str) -> Tuple["Popen[bytes]", str]:
    port = _pick_port()
    args = (
        "java",
        "-Xss4m",
        "-Dnu.validator.servlet.bind-address=localhost",
        "-cp",
        str(jar_path),
        "nu.validator.servlet.Main",
        str(port),
    )
    try:
        proc = Popen(args, stdin=DEVNULL)  # pylint: disable=consider-using-with
    except OSError as ex:
        raise PluginError(f"Failed to launch v.Nu checker servlet: {ex}") from ex
    return proc, f"http://localhost:{port:d}"


def plugin_create(args: Namespace) -> Iterator[Plugin]:
    content_types = {"text/html", "application/xhtml+xml", "image/svg+xml"}
    if args.css:
        content_types.add("text/css")

    url = args.check
    if url is not None:
        launch = False
        if url == "launch":
            url = _find_vnujar()
            launch = True
        elif url.isdigit():
            url = "http://localhost:" + url
        yield HTMLValidator(url, launch, content_types)


class HTMLValidator(Plugin):
    """Runs the Nu Html Checker on loaded documents."""

    def __init__(self, service_url: str, launch: bool, content_types: Container[str]):
        """
        Initialize a validator using the given checker web service.

        @param service_url:
            URL for the checker web service.
        @param launch:
            If C{True}, the validator should be launched using
            the JAR file specified by C{service_url}.
            If C{False}, C{service_url} is the URL of an externally
            started web service.
        @param content_types:
            Documents of these types will be checked,
            other documents will be ignored.
        """
        self.content_types = content_types
        if launch:
            service, service_url = _launch_service(service_url)
            self.service: Optional["Popen[bytes]"] = service
        else:
            self.service = None
        self.client = VNUClient(service_url)

    def close(self) -> None:
        self.client.close()
        if self.service is not None:
            self.service.terminate()

    def resource_loaded(
        self, data: bytes, content_type_header: str, report: Report
    ) -> None:
        content_type, args_ = parse_header(content_type_header)
        if content_type not in self.content_types:
            return

        try:
            for message in self.client.request(data, content_type_header):
                _process_message(message, report)
        except (HTTPException, OSError) as ex:
            report.exception("Request to HTML checker failed: %s", ex)
        except ValueError as ex:
            report.exception("Parsing reply from HTML checker failed: %s", ex)

        report.checked = Checked.CHECKED


def _process_message(message: Mapping[str, Any], report: Report) -> None:
    msg_type: Optional[str] = message.get("type")
    subtype: Optional[str] = message.get("subtype")
    text: str = message.get("message", "(no message)")

    if msg_type == "info":
        level = WARNING if subtype == "warning" else INFO
    elif msg_type == "error":
        level = ERROR
    elif msg_type == "non-document-error":
        subtype = subtype or "general"
        text = f"{subtype.capitalize()} error in checker: {text}"
        level = ERROR
    else:
        text = f'Undocumented message type "{msg_type}": {text}'
        level = ERROR

    lines = "-".join(
        str(message[attr]) for attr in ("firstLine", "lastLine") if attr in message
    )
    if lines:
        text = f"line {lines}: {text}"

    html: XMLContent = text

    if msg_type == "error" and subtype == "fatal":
        html = concat(
            html, xml.br, xml.b["Fatal:"], " This error blocks further checking."
        )

    extract = message.get("extract")
    if extract:
        start = message.get("hiliteStart")
        length = message.get("hiliteLength")
        if isinstance(start, int) and isinstance(length, int):
            end = start + length
            if 0 <= start < end <= len(extract):
                extract = (
                    extract[:start],
                    xml.span(class_="extract")[extract[start:end]],
                    extract[end:],
                )
        html = concat(html, xml.br, xml.code[extract])

    report.log(level, text, extra={"html": html})
