# MIT License
# 
# Copyright (c) 2023 vvainola
# 
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# 
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
# 
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import click
import subprocess
import xml.etree.ElementTree as et
from dataclasses import dataclass
import typing as T
import os
import sys
import enum
import re
import copy
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
    quiet = False
    run_status_idx = 0
    test_log = None

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
            self.log(f"{test_count_print:{test_count_print_len}} {test_case.name_and_tag:{self.max_test_name_length}} {GREEN}OK{END_COLOR}   {duration:3.3f}s",
                     condition=not (self.quiet))
            self.log("".join(lines).strip(), self.verbose)
        else:
            self.failing_count += 1
            self.log(f"{test_count_print:{test_count_print_len}} {test_case.name_and_tag:{self.max_test_name_length}} {RED}FAIL{END_COLOR} {duration:3.3f}s",
                     condition=True)
            self.log("".join(lines).strip())
            self.log()

    def print_run_status(self, running_tests: T.List[TestCase]):
        test_count_print = f"{self.test_counter}/{self.test_count}"
        test_count_print_len = 2*len(str(self.test_count)) + 1
        self.run_status_idx = (self.run_status_idx + 1) % (len(running_tests))
        self.log('\x1b[K', end="\r")
        self.log(
            f"{BLUE}Running {test_count_print:{test_count_print_len}}{END_COLOR} {running_tests[self.run_status_idx].name_and_tag}", end="\r")

    def log(self, s: str = '',
            condition: bool = True,
            end="\n"):
        if condition:
            print(s, end=end)
        if end == "\n":
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            s = ansi_escape.sub('', s)
            self.test_log.write(s + '\n')


@click.command()
@click.argument('test_exe', nargs=1)
@click.argument('test_filter', default='')
@click.option('-v', '--verbose', is_flag=True)
@click.option('-q', '--quiet', is_flag=True)
@click.option('-j', '--jobs', default=os.cpu_count() - 1)
@click.option('-r', '--repeat', default=1)
@click.option('--log', default="testlog.txt")
def run_tests(test_exe, test_filter, verbose, quiet, jobs, repeat, log):
    test_printer = TestPrinter()
    test_printer.verbose = verbose
    test_printer.quiet = quiet
    if quiet and verbose:
        sys.exit('Can not be both quiet and verbose at the same time.')
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
        test_printer.test_log = open(log, 'w')
    test_cases_repeat = []
    for _ in range(repeat):
        for test_case in test_cases:
            test_cases_repeat.append(copy.deepcopy(test_case))
    test_cases = test_cases_repeat
    test_printer.test_count = len(test_cases)

    if len(test_cases) == 0:
        sys.exit(f"No matching test cases for \"{test_filter}\"")
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
                                                   '--colour-mode=ansi', '--durations=yes'],
                                                  stdout=subprocess.PIPE,
                                                  stderr=subprocess.STDOUT, text=True)
        running_tests.append(test_case)
    # Wait for remaining jobs
    while len(running_tests) > 0:
        test_printer.print_run_status(running_tests)
        for running_test in running_tests:
            status = running_test.test_process.poll()
            if status != None:
                test_printer.print_result(running_test)
                running_tests.remove(running_test)
                break
            sleep(0.2)

    # Summary
    test_printer.log('\x1b[K', end="\r")
    test_printer.log()
    total_time = time() - start_time
    test_printer.log(f'Total time: {total_time:.3f}s')
    test_printer.log(f"{'OK':5} {test_printer.ok_count}")
    test_printer.log(f"{'FAIL':5} {test_printer.failing_count}")
    test_printer.log()
    if test_printer.failing_count == 0:
        test_printer.log(f"{GREEN}All tests ok{END_COLOR}")
    else:
        test_printer.log(f"{RED}Failing test cases:{END_COLOR}")
        for test_case in test_cases:
            if test_case.test_process.poll() != 0:
                test_printer.log(f"\"{test_case.name}\" {test_case.tags}")

    print()
    print(f'Full test log written to {os.path.abspath(log)}')
    sys.exit(test_printer.failing_count > 0)


if __name__ == '__main__':
    run_tests()
