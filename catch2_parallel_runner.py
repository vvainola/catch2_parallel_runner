import click
import subprocess
import xml.etree.ElementTree as et
from dataclasses import dataclass
import typing as T
import os
import sys
from time import sleep, time

GREEN = '\033[92m'
RED = '\033[91m'
BLUE = '\033[94m'
END_COLOR = '\033[0m'


@dataclass
class TestCase:
    name: str
    tags: str
    name_and_tag: str = ""
    test_process: subprocess.Popen = None


@dataclass
class TestPrinter:
    max_test_name_length = 0
    test_counter = 0
    test_count = 0
    ok_count = 0
    failing_count = 0
    verbose = False
    run_status_idx = 0

    def print_result(self, test_case: TestCase):
        self.test_counter += 1

        status = test_case.test_process.poll()
        # Find line with "===============", previous line has duration
        lines = test_case.test_process.stdout.readlines()
        line = len(lines) - 1
        duration = -1
        while duration < 0 and line > 0:
            if "=====" in lines[line]:
                duration = float(lines[line - 1].split(" s:")[0])
            line -= 1

        test_count_print = f"{self.test_counter}/{self.test_count}"
        test_count_print_len = 2*len(str(self.test_count)) + 1
        if status == 0:
            self.ok_count += 1
            print(f"{test_count_print:{test_count_print_len}} {test_case.name_and_tag:{self.max_test_name_length}} {GREEN}OK{END_COLOR}   {duration:3.3f}s")
            if self.verbose:
                print("".join(lines).strip())
        else:
            self.failing_count += 1
            print(f"{test_count_print:{test_count_print_len}} {test_case.name_and_tag:{self.max_test_name_length}} {RED}FAIL{END_COLOR} {duration:3.3f}s")
            print("".join(lines).strip())
            print()

    def print_run_status(self, running_tests: T.List[TestCase]):
        self.run_status_idx = (self.run_status_idx + 1) % (len(running_tests))
        print('\x1b[K', end="\r")
        print(
            f"{BLUE}Running{END_COLOR} {running_tests[self.run_status_idx].name_and_tag}", end="\r")


@click.command()
@click.argument('test_exe', nargs=1)
@click.argument('test_filter', default='')
@click.option('-v', '--verbose', is_flag=True)
@click.option('-j', '--jobs', default=os.cpu_count() - 1)
def run_tests(test_exe, test_filter, verbose, jobs):
    test_printer = TestPrinter()
    test_printer.verbose = verbose
    max_jobs = jobs

    # Get list of tests
    test_cases_xml = subprocess.run([test_exe, test_filter, '--list-tests',
                                    '--reporter=xml'], check=True, capture_output=True, text=True).stdout
    root = et.fromstring(test_cases_xml)
    test_cases: T.List[TestCase] = []
    for child in root:
        test_case = TestCase(name=child.find("Name").text,
                             tags=child.find("Tags").text)
        test_case.name_and_tag = f"\"{test_case.name}\" {test_case.tags}"
        test_cases.append(test_case)
        test_printer.max_test_name_length = max(
            test_printer.max_test_name_length, len(test_case.name_and_tag))
    test_printer.test_count = len(test_cases)

    if len(test_cases) == 0:
        sys.exit(f"No matching test cases for \"{test_filter}\"")
    else:
        print(f"Running {len(test_cases)} tests")
    start_time = time()

    # Run tests in parallel
    running_tests = []
    for test_case in test_cases:
        while len(running_tests) == max_jobs:
            for running_test in running_tests:
                status = running_test.test_process.poll()
                if status != None:
                    test_printer.print_result(running_test)
                    running_tests.remove(running_test)
                    break
            if len(running_tests) == max_jobs:
                test_printer.print_run_status(running_tests)
                sleep(0.2)
        test_case.test_process = subprocess.Popen([test_exe, test_case.name,
                                                   '--colour-mode=ansi', '--durations=yes', '--order=rand'],
                                                  stdout=subprocess.PIPE,
                                                  stderr=subprocess.STDOUT, text=True)
        running_tests.append(test_case)
    # Wait for remaining jobs
    while len(running_tests) > 0:
        test_printer.print_run_status(running_tests)
        sleep(0.2)
        for running_test in running_tests:
            status = running_test.test_process.poll()
            if status != None:
                test_printer.print_result(running_test)
                running_tests.remove(running_test)
                break

    # Summary
    print()
    total_time = time() - start_time
    print(f'Total time: {total_time:.3f}s')
    print(f"{'OK':5} {test_printer.ok_count}")
    print(f"{'FAIL':5} {test_printer.failing_count}")
    print()
    if test_printer.failing_count == 0:
        print(f"{GREEN}All tests ok{END_COLOR}")
    else:
        print(f"{RED}Failing test cases:{END_COLOR}")
        for test_case in test_cases:
            if test_case.test_process.poll() != 0:
                print(f"\"{test_case.name}\" {test_case.tags}")
    sys.exit(test_printer.failing_count > 0)


if __name__ == '__main__':
    run_tests()
