from os import makedirs, remove
from os.path import isfile
from pathlib import Path
from shutil import rmtree

from invoke import task

SRC_ENV = {'PYTHONPATH': 'src'}

@task
def clean(c):
    """Clean up our output."""
    print('Cleaning up...')
    rmtree('docs/')
    if isfile('doctest.html'):
        remove('doctest.html')

@task
def lint(c, results=None):
    """Check sources with PyLint."""
    print('Checking sources with PyLint...')
    cmd = ['pylint', 'apetest']
    if results is None:
        json_file = None
        hide = None
    else:
        report_dir = Path(results).parent.resolve()
        json_file = report_dir / 'pylint.json'
        hide = 'stdout'
        cmd += ['-f', 'json', '>%s' % json_file]
    lint_result = c.run(' '.join(cmd), env=SRC_ENV, warn=True)
    if results is not None:
        from pylint_json2sfresults import gather_results, write_results
        results_dict = gather_results(json_file, lint_result.exited)
        write_results(results_dict, results)

@task
def readme(c):
    """Render README.md to HTML."""
    print('Rendering README...')
    makedirs('docs/', exist_ok=True)
    c.run('markdown_py -f %s %s' % ('docs/README.html', 'README.md'))

@task
def apidocs(c):
    """Generate documentation as HTML files."""
    print('Generating API docs...')
    c.run('pdoc apetest --html --html-dir docs/api --overwrite', env=SRC_ENV)

@task
def liveapi(c):
    """Serve live API documentation through HTTP."""
    c.run('pdoc --http localhost:8765 apetest', env=SRC_ENV, pty=True)

@task(post=[apidocs, readme])
def docs(c):
    """Generate documentation as HTML files."""

@task(pre=[apidocs])
def doctest(c):
    """Check our documentation using APE."""
    c.run('apetest --check launch docs/api/apetest doctest.html')

@task
def unittest(c):
    """Run unit tests."""
    c.run('pytest tests', env=SRC_ENV, pty=True)

@task(post=[doctest, unittest, lint])
def test(c):
    """Run all tests."""
