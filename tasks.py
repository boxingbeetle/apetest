from os import makedirs, remove
from os.path import isfile
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
def lint(c):
    """Check sources with PyLint."""
    c.run('pylint apetest', env=SRC_ENV)

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
