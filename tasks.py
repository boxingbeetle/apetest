from itertools import chain
from pathlib import Path
from shutil import rmtree

from invoke import UnexpectedExit, task

TOP_DIR = Path(__file__).parent
DOC_DIR = TOP_DIR / "docs"
SRC_DIR = TOP_DIR / "src"
SRC_ENV = {"PYTHONPATH": str(SRC_DIR)}


def source_arg(pattern):
    """Converts a source pattern to a command line argument."""
    if pattern is None:
        paths = chain(
            SRC_DIR.glob("**/*.py"),
            (TOP_DIR / "tests").glob("**/*.py"),
            [Path(__file__)],
        )
    else:
        paths = Path.cwd().glob(pattern)
    for path in paths:
        yield str(path)


def remove_dir(path):
    """Recursively removes a directory."""
    if path.exists():
        rmtree(path)


@task
def clean(c):
    """Clean up our output."""
    print("Cleaning up...")
    remove_dir(DOC_DIR)
    doctest_report = TOP_DIR / "doctest.html"
    if doctest_report.is_file():
        doctest_report.unlink()


@task
def lint(c, src=None, html=None):
    """Check sources with PyLint."""
    print("Checking sources with PyLint...")
    report_dir = TOP_DIR
    cmd = ["pylint"]
    sources = set(source_arg(src))
    sources.remove(__file__)
    cmd += sources
    if html is not None:
        json_file = report_dir / "pylint.json"
        cmd += [
            "--load-plugins=pylint_json2html",
            "--output-format=jsonextended",
            f">{json_file}",
        ]
    with c.cd(str(TOP_DIR)):
        c.run(" ".join(cmd), env=SRC_ENV, warn=True, pty=True)
    if html is not None:
        c.run(f"pylint-json2html -f jsonextended -o {html} {json_file}")


@task
def types(c, src=None, clean=False, report=False):
    """Check sources with mypy."""
    if clean:
        print("Clearing mypy cache...")
        remove_dir(TOP_DIR / ".mypy_cache")
    print("Checking sources with mypy...")
    report_dir = None
    cmd = ["mypy"]
    if report:
        if report_dir is None:
            mypy_report = TOP_DIR / "mypy-report"
        else:
            mypy_report = report_dir / "mypy-coverage"
        remove_dir(mypy_report)
        cmd.append(f"--html-report {mypy_report}")
    sources = set(source_arg(src))
    sources.remove(__file__)
    cmd += sources
    out_path = None if report_dir is None else report_dir / "mypy-log.txt"
    out_stream = None if out_path is None else open(out_path, "w", encoding="utf-8")
    try:
        with c.cd(str(TOP_DIR)):
            try:
                c.run(" ".join(cmd), env=SRC_ENV, out_stream=out_stream, pty=True)
            except UnexpectedExit as ex:
                if ex.result.exited < 0:
                    print(ex)
    finally:
        if out_stream is not None:
            out_stream.close()


@task
def readme(c):
    """Render README.md to HTML."""
    print("Rendering README...")
    DOC_DIR.mkdir(exist_ok=True)
    c.run(f"markdown_py -f {DOC_DIR / 'README.html'} {TOP_DIR / 'README.md'}")


@task
def apidocs(c):
    """Generate documentation as HTML files."""
    apiDir = DOC_DIR / "api"
    remove_dir(apiDir)
    apiDir.mkdir(parents=True)
    cmd = [
        "pydoctor",
        "--make-html",
        f"--html-output={apiDir}",
        "--project-name=APE",
        "--project-url=https://boxingbeetle.com/tools/ape/",
        "--intersphinx=https://docs.python.org/3/objects.inv",
        f"{SRC_DIR}/apetest",
    ]
    c.run(" ".join(cmd))


@task(post=[apidocs, readme])
def docs(c):
    """Generate documentation as HTML files."""


@task(pre=[apidocs])
def doctest(c):
    """Check our documentation using APE."""
    c.run("apetest --check launch docs/api/apetest doctest.html")


@task
def unittest(c, junit_xml=None):
    """Run unit tests."""
    args = ["pytest"]
    if junit_xml is not None:
        args.append(f"--junit-xml={junit_xml}")
    args.append("tests")
    with c.cd(str(TOP_DIR)):
        c.run(" ".join(args), env=SRC_ENV, pty=True)


@task(post=[doctest, unittest, lint])
def test(c):
    """Run all tests."""
