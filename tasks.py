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
    return " ".join(str(path) for path in paths)


def remove_dir(path):
    """Recursively removes a directory."""
    if path.exists():
        rmtree(path)


def write_results(results, results_path):
    """Write a results dictionary to file."""
    with open(str(results_path), "w", encoding="utf-8") as out:
        for key, value in results.items():
            escaped = value.replace("\\", "\\\\")
            out.write(f"{key}={escaped}\n")


@task
def clean(c):
    """Clean up our output."""
    print("Cleaning up...")
    remove_dir(DOC_DIR)
    doctest_report = TOP_DIR / "doctest.html"
    if doctest_report.is_file():
        doctest_report.unlink()


@task
def lint(c, src=None, html=None, results=None):
    """Check sources with PyLint."""
    print("Checking sources with PyLint...")
    if results is None:
        report_dir = TOP_DIR
    else:
        # We need to output JSON to produce the results file, but we also
        # need to report the issues, so we have to get those from the JSON
        # output and the easiest way to do so is to enable the HTML report.
        report_dir = Path(results).parent.resolve()
        html = report_dir / "pylint.html"
    cmd = ["pylint", source_arg(src)]
    if html is not None:
        json_file = report_dir / "pylint.json"
        cmd += [
            "--load-plugins=pylint_json2html",
            "--output-format=jsonextended",
            f">{json_file}",
        ]
    with c.cd(str(TOP_DIR)):
        lint_result = c.run(" ".join(cmd), env=SRC_ENV, warn=True, pty=results is None)
    if html is not None:
        c.run(f"pylint-json2html -f jsonextended -o {html} {json_file}")
    if results is not None:
        import sys

        sys.path.append(str(SRC_DIR))
        from pylint_json2sfresults import gather_results

        results_dict = gather_results(json_file, lint_result.exited)
        results_dict["report"] = str(html)
        write_results(results_dict, results)


@task
def types(c, src=None, clean=False, report=False, results=None):
    """Check sources with mypy."""
    if clean:
        print("Clearing mypy cache...")
        remove_dir(TOP_DIR / ".mypy_cache")
    print("Checking sources with mypy...")
    report_dir = None if results is None else Path(results).parent.resolve()
    cmd = ["mypy"]
    if report:
        if report_dir is None:
            mypy_report = TOP_DIR / "mypy-report"
        else:
            mypy_report = report_dir / "mypy-coverage"
        remove_dir(mypy_report)
        cmd.append(f"--html-report {mypy_report}")
    cmd.append(source_arg(src))
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
    if results is not None:
        errors = 0
        with open(out_path, "r", encoding="utf-8") as log:
            for line in log:
                if " error: " in line:
                    errors += 1
        with open(results, "w", encoding="utf-8") as out:
            out.write(f'result={"warning" if errors else "ok"}\n')
            out.write(f"summary=mypy found {errors} errors\n")
            out.write(f"report.{0 if errors else 2}={out_path}\n")
            if report:
                out.write(f"report.1={report_dir}/mypy-coverage\n")


@task
def black(c, src=None):
    """Format source files."""
    print("Formatting sources...")
    with c.cd(str(TOP_DIR)):
        c.run(f"black {source_arg(src)}", pty=True)


@task
def isort(c, src=None):
    """Sort imports."""
    print("Sorting imports...")
    with c.cd(str(TOP_DIR)):
        c.run(f"isort {source_arg(src)}", pty=True)


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
def unittest(c, junit_xml=None, results=None):
    """Run unit tests."""
    if results is not None:
        report_dir = Path(results).parent.resolve()
        junit_xml = report_dir / "pytest-report.xml"
    args = ["pytest"]
    if junit_xml is not None:
        args.append(f"--junit-xml={junit_xml}")
    args.append("tests")
    with c.cd(str(TOP_DIR)):
        c.run(" ".join(args), env=SRC_ENV, pty=results is None)
    if results is not None:
        results_dict = dict(report=str(junit_xml))
        write_results(results_dict, results)


@task(post=[doctest, unittest, lint])
def test(c):
    """Run all tests."""
