"""Run this project's full unittest suite and end-to-end checks from the repo root.

The suite covers the original V1 regression and the V2 highest-surface units.
After it passes, the sample scenario script and the source-severed verification
run in sequence; any non-zero exit propagates so the runtime manifest's single
``verify`` entry reports failure with a non-zero status.
"""
import subprocess
import sys
import unittest


def run_suite():
    suite = unittest.defaultTestLoader.discover('tests', top_level_dir='.')
    if suite.countTestCases():
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    else:
        print('No tests discovered in tests/', file=sys.stderr)
        result = unittest.TestResult()
    for status, failed_cases in (
        ('FAIL', (test for test, _ in result.failures)),
        ('ERROR', (test for test, _ in result.errors)),
        ('UNEXPECTED_SUCCESS', result.unexpectedSuccesses),
    ):
        for test in failed_cases:
            print(f'{status} {test.id()}')
    successful = result.testsRun > 0 and result.wasSuccessful()
    print(f'TEST SUMMARY total={result.testsRun} failures={len(result.failures)} '
          f'errors={len(result.errors)} skipped={len(result.skipped)} '
          f'expected_failures={len(result.expectedFailures)} '
          f'unexpected_successes={len(result.unexpectedSuccesses)} '
          f'result={"PASS" if successful else "FAIL"}')
    return successful


def run_script(name):
    completed = subprocess.run([sys.executable, '-B', name], cwd='.')
    print(f'SCRIPT {name} exit={completed.returncode}')
    return completed.returncode == 0


def main():
    successful = run_suite()
    if successful:
        successful = run_script('surface_examples.py')
    if successful:
        successful = run_script('check_highest.py')
    print(f'PROJECT RESULT {"PASS" if successful else "FAIL"}')
    return 0 if successful else 1


if __name__ == '__main__':
    raise SystemExit(main())
