# SPDX-License-Identifier: BSD-3-Clause

"""
Utility to create a SoftFab results file from PyLint's JSON output.

For SoftFab, 'error' means the test results are incomplete, while 'warning'
means the results are complete but the content has problems. So if PyLint
ran successfully but finds errors in the code it examined, that means it did
its job correctly and the SoftFab result will be 'warning'.
"""

from collections import Counter
import json


def results_from_exit_code(exit_code):
    """Return a results dictionary based on PyLint's exit code.

    https://pylint.readthedocs.io/en/latest/user_guide/run.html#exit-codes
    """

    # Incomplete results.
    if exit_code & 32:
        return dict(result='error', summary='PyLint did not complete run')
    if exit_code & 1:
        return dict(result='error', summary='PyLint encountered fatal error')
    if exit_code & ~63:
        return dict(result='error', summary='Unknown PyLint exit code: %d' % exit_code)

    # Content problems, from more to less urgent.
    # I'm putting convention messages before refactor messages because
    # the former can typically be fixed quicker.
    if exit_code & 2:
        return dict(result='warning', summary='PyLint found errors')
    if exit_code & 4:
        return dict(result='warning', summary='PyLint found warnings')
    if exit_code & 16:
        return dict(result='warning', summary='PyLint found broken conventions')
    if exit_code & 8:
        return dict(result='warning', summary='PyLint found refactor candidates')

    return dict(result='ok', summary='PyLint found no issues')

def results_from_json(json_path):
    """Return a results dictionary based on a PyLint JSON output file."""

    # Read and parse JSON file.
    try:
        with open(str(json_path), encoding='utf-8') as inp:
            data = json.load(inp)
    except OSError as ex:
        return dict(result='error', summary='Error reading JSON: %s' % ex)
    except ValueError as ex:
        return dict(result='error', summary='Error parsing JSON: %s' % ex)

    # Count number of issues of each type.
    counts = Counter()
    try:
        if isinstance(data, list):
            # PyLint's native JSON format.
            messages = data
        elif isinstance(data, dict):
            # Extended JSON format from pylint_json2html.
            messages = data['messages']
        else:
            raise TypeError('Bad top-level type: %s' % type(data).__name__)
        for message in messages:
            counts[message['type']] += 1
    except Exception as ex:
        return dict(result='error', summary='Error processing JSON: %s' % ex)

    # In case of a fatal problem, the results may be incomplete, so stop
    # here to avoid reporting incorrect information.
    if counts['fatal']:
        return dict(result='error', summary='PyLint encountered fatal error')

    # Prepare summary and gather mid-level data.
    results = {}
    issues = []
    for msg_type in ('error', 'warning', 'convention', 'refactor'):
        count = counts[msg_type]
        results['data.%s' % msg_type] = str(count)
        if count:
            issues.append('%d %s%s' % (count, msg_type, '' if count == 1 else 's'))

    # Gather more mid-level data when using extended JSON format.
    if isinstance(data, dict):
        try:
            stats = data['stats']
            for key in ('module', 'class', 'method', 'function', 'statement',
                        'undocumented_module', 'undocumented_class',
                        'undocumented_method', 'undocumented_function'):
                results['data.%s' % key] = str(stats[key])
        except Exception as ex:
            return dict(result='error', summary='Error processing extended JSON: %s' % ex)

    # Summarize the findings.
    if issues:
        results['result'] = 'warning'
        results['summary'] = 'PyLint found %s' % ', '.join(issues)
    else:
        results['result'] = 'ok'
        results['summary'] = 'PyLint found no issues'

    return results

def gather_results(json_path, exit_code=0):
    """Return a results dictionary based on PyLint's exit code and
    a PyLint JSON output file.
    """

    results = results_from_exit_code(exit_code)
    if results['result'] != 'error':
        results = results_from_json(json_path)
    return results
