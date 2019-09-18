from os import makedirs, remove
from os.path import isfile
from pathlib import Path
from shutil import rmtree

from invoke import task

SRC_ENV = {'PYTHONPATH': 'src'}

def write_results(results, results_path):
    """Write a results dictionary to file."""
    with open(str(results_path), 'w', encoding='utf-8') as out:
        for key, value in results.items():
            out.write('%s=%s\n' % (key, value.replace('\\', '\\\\')))

@task
def clean(c):
    """Clean up our output."""
    print('Cleaning up...')
    rmtree('docs/')
    if isfile('doctest.html'):
        remove('doctest.html')

@task
def lint(c, html=None, results=None):
    """Check sources with PyLint."""
    print('Checking sources with PyLint...')
    if results is None:
        report_dir = Path('.')
    else:
        # We need to output JSON to produce the results file, but we also
        # need to report the issues, so we have to get those from the JSON
        # output and the easiest way to do so is to enable the HTML report.
        report_dir = Path(results).parent.resolve()
        html = report_dir / 'pylint.html'
    cmd = ['pylint', 'apetest']
    if html is None:
        hide = None
    else:
        json_file = report_dir / 'pylint.json'
        hide = 'stdout'
        cmd += ['--load-plugins=pylint_json2html',
                '--output-format=jsonextended',
                '>%s' % json_file]
    lint_result = c.run(' '.join(cmd), env=SRC_ENV, warn=True)
    if html is not None:
        c.run('pylint-json2html -f jsonextended -o %s %s' % (html, json_file))
    if results is not None:
        import sys
        sys.path.append(str(Path('src').resolve()))
        from pylint_json2sfresults import gather_results
        results_dict = gather_results(json_file, lint_result.exited)
        results_dict['report'] = str(html)
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
def unittest(c, junit_xml=None, results=None):
    """Run unit tests."""
    if results is not None:
        report_dir = Path(results).parent.resolve()
        junit_xml = report_dir / 'pytest-report.xml'
    args = ['pytest']
    if junit_xml is not None:
        args.append('--junit-xml=%s' % junit_xml)
    args.append('tests')
    c.run(' '.join(args), env=SRC_ENV, pty=results is None)
    if results is not None:
        results_dict = dict(report=str(junit_xml))
        write_results(results_dict, results)

@task(post=[doctest, unittest, lint])
def test(c):
    """Run all tests."""
