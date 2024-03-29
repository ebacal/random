"""Unit test for Airflow DAG"""

import os
import sys
import re
import shlex
import subprocess
import traceback
from datetime import datetime, timedelta
import requests
from croniter import croniter

TEAM = sys.argv[1]
USER = sys.argv[2]


class Connections(object):
    def __init__(self):
        self.auth = "***"
        self.headers = {
            'Authorization': 'basic ' + self.auth + '',
            'Content-Type': 'application/json; charset=utf-8'}
        self.team = os.path.splitext(os.path.basename(TEAM))[0]
        self.user = USER
        self.git_url = "https://github.paypal.com/api/v3/repos/airflow/"
        self.pull_url = self.git_url + self.team + "/pulls"

    def connection(self, url):
        try:
            req = requests.get(url, headers=self.headers, timeout=3)
            if req.status_code == 200:
                return req.json()
            req.raise_for_status()
        except requests.exceptions.HTTPError as errh:
            print("Http Error:", errh)
            raise
        except requests.exceptions.ConnectionError as errc:
            print("Error Connecting:", errc)
            raise
        except requests.exceptions.Timeout as errt:
            print("Timeout Error:", errt)
            raise
        except requests.exceptions.RequestException as err:
            print("General Error: ", err)
            raise
        finally:
            req.close()

    def execution(self, cmd):
        """General Function that executes the commands."""
        args = shlex.split(cmd)
        try:
            proc = subprocess.Popen(
                args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding='utf8')
            out = proc.stdout.read()
            err = proc.communicate()[1]
            return err, out.strip(), proc.returncode
        except ImportError as err:
            print("The following library is not found/installed. Please update your code.")
            print(traceback.format_exc(err))
            sys.exit(1)
        except subprocess.CalledProcessError as err:
            print("Another error from CalledProcessError")
            print(traceback.format_exc(err))
            print("Status returncode: ", err.returncode)
            print("Status output: ", err.output)
            sys.exit(1)


class Commit_Data(Connections):
    def __init__(self):
        super().__init__()
        self.pull_num, self.pull_sha = self.get_commit_sha()
        self.squash_check()

    def get_commit_sha(self):
        data = self.connection(self.pull_url)
        users = [x['user']['login'] for x in data]
        for pulls in data:
            print("Looping {}/{}/{}".format(self.pull_url, str(pulls['number']), pulls['head']['sha']))
            if pulls['state'] == 'open' and pulls['user']['login'] == self.user:
                pull_num = str(pulls['number'])
                pull_sha = pulls['head']['sha']
                print(" Returning {}/{}".format(pull_num, pull_sha))
                return pull_num, pull_sha
            continue
        print("Did not find any pull requests from your username: {}".format(self.user))
        print("Currently open pulled requests are from: {}".format(users))
        print("Please resubmit your pull request.")
        sys.exit(1)

    def squash_check(self):
        """
        Check for multiple commits in a single pull request.
        Returns the Commit URL for that pull request
        """
        url = "{}/{}/commits".format(self.pull_url, self.pull_num)
        data = self.connection(url)
        if len(data) > 1:
            print("Found {} commits in your Pull Request: {}".format(len(data), self.pull_sha))
            print("Please squash your commits and resubmit your Pull Request")
            print("\n" + "".center(120, "=") + "\n")
            sys.exit(1)

    def get_team(self):
        return self.team

    def get_dag_files(self):
        file_list = []
        commit_url = self.git_url + self.team + "/commits/" + self.pull_sha
        print(commit_url)
        req = self.connection(commit_url)
        for dag_name in req['files']:
            dag_formatted = dag_name['filename'].split('/').pop()
            if dag_name['status'] == "removed" or not dag_formatted.startswith("PPAD"):
                pass
            else:
                if not dag_formatted.endswith(".py"):
                    print("Your DAG name: {} is not a python script or does not end with .py.\n"
                          "Please upload only .py DAG files.".format(dag_formatted))
                    sys.exit(1)
                file_list.append(dag_name['filename'])
        if not file_list:
            print("No DAG files have been found in your Pull Request. If you updated files that are not\n"
                  "DAGS, please contact Admin team in order to review your Pull request manually.")
            sys.exit(0)
        else:
            print("Files Found:")
            print(file_list)
            return file_list

    def locate_dags(self, file):
        """Scan DAG file and Pull out all the DAGS"""
        dag_list = []
        try:
            command = "airflow dags list -o json -S ./{}".format(file)
            print("\nDAGs Detected:")
            err, out, exitcode = self.execution(command)
            print(err)
            if 'ERROR' in out:
                print("Your DAG has ERRORS! Please correct them and resubmit.\n\n")
                print(out)
                print(exitcode)
                sys.exit(1)
            elif not out:
                print("No DAGs in your file where detected. Please review your \
                      DAG or contact Admin team for additional help.")
                sys.exit(1)
            else:
                for each_entry in out.splitlines():
                    if each_entry.startswith("PPAD"):
                        if " " in each_entry:
                            print("There is space in your DAG name. Please resolve it.")
                            sys.exit(1)
                        elif each_entry.endswith(".py") or ".py" in each_entry:
                            print("Your DAG name {} ends with .py.\n"
                                  "Please remove the extension and resubmit.".format(each_entry))
                            sys.exit(1)
                        dag_list.append(each_entry)
                    else:
                        continue
                print(dag_list)
                if not dag_list:
                    print("No DAGs in your file where detected. Please review your DAG \
                          or contact Admin team for additional help.")
                    sys.exit(1)
                return dag_list
        except SyntaxError as err:
            print(err)
            sys.exit(1)
        except Exception as err:
            print(err)
            sys.exit(1)


class Filters():
    """DAG File filters and checks"""
    def __init__(self, dag_file):
        self.dag = os.path.abspath(dag_file)
        self.open_file = open(self.dag).readlines()

    def get_timestamp_from_cron(self, cron):
        """Parses the cron timestamp"""
        macros = ["@hourly", "@daily", "@weekly", "@monthly"]
        if cron in ["@once", "@yearly"]:
            print(cron)
            print("""
                Your schedule_interval is set to '{}'. Unfortunately, we do not allow
                DAGs that run at this interval. Please update your dag to run at batch intervals.
                """.format(cron))
            sys.exit(1)
        elif cron in macros:
            print("Check - schedule_interval: {} - PASSED.".format(cron))
        else:
            base = datetime.combine(datetime.now(), datetime.min.time())
            iterate = croniter(cron, base)
            timestamp = iterate.get_next(datetime)
            difference = timestamp - base
            if difference <= timedelta(minutes=29):
                print("""
                    Your schedule_interval is set to be less than 30 minutes. Unfortunately,
                    we do not allow dags to run at a lower time requency. Please update your dag
                    to run at least 30 minutes or more.
                    """)
                sys.exit(1)
            else:
                print("Check - schedule_interval: {} - PASSED.".format(cron))

    def check_interval(self):
        """Checks schedule_interval variable"""
        string = "schedule_interval"
        pattern = re.compile('(?<=schedule_interval)( )*=( )*[\'\"]([^\"|\']*)')
        match = [s.strip() for s in self.open_file if string in s][0]
        values = (re.search(pattern, match)).group(3)
        self.get_timestamp_from_cron(values)

    def check_start_date(self):
        """Checks start_date variable"""
        pattern = re.compile("datetime.now()")
        string = "start_date"
        match = [s.strip() for s in self.open_file if string in s]
        values = list(filter(pattern.search, match))
        if values:
            print("""
                Your start_date has datetime.now() in it. Please hardcode
                start_date to a date when your dag was first deployed.""")
            sys.exit(1)
        print("Check - {} - PASSED.".format(match))

    def __call__(self):
        # self.check_interval()
        self.check_start_date()


class Verification():
    """Collection of methods that verify the DAG file is valid."""
    def __init__(self, dag_file):
        self.dag = dag_file  # Full name of DAG file that is being checked
        self.dag_name = os.path.splitext(self.dag)[0]  # Name of the actual DAG, without extension
        self.workdir = os.getcwd()  # Current working directory where DAGs are stored
        self.start = datetime.combine(datetime.today(), datetime.min.time())
        self.error_list = []
        self.error_list.append(str(self.dag))
        self.execute = Connections()
        self.flake_test()
        self.pylint_test()

    def headers(self, value, test):
        """Main print statements"""
        print(" TESTING - {} ".format(value).center(120, "="))
        print("\n")
        print("Running {} Code Syntax Test".format(test).center(120, "="))
        print("".center(120, "=") + "\n")

    def exitcode(self, error, output, code, test):
        """Main exit print statements"""
        print(error)
        print(output)
        if not code:
            print("There are no errors. Total: {}".format(code))
            return self.error_list.append("{} Syntax TEST - PASSED".format(test))
        print("There are errors in your syntax. Total: {}".format(code))
        return self.error_list.append("{} Syntax TEST - FAILED".format(test))

    def flake_test(self):
        """Running the process for Flake8 test"""
        self.headers(self.dag, 'Flake8')
        command = 'flake8 --count --ignore=W191,E126 --max-line-length=160 {}'.format(self.dag)
        err, out, exitcode = self.execute.execution(command)
        self.exitcode(err, out, exitcode, 'Flake8')

    def pylint_test(self):
        """Running the process for PyLint test"""
        self.headers(self.dag, 'PyLint')
        command = 'pylint -E --max-line-length=160 {}'.format(self.dag)
        err, out, exitcode = self.execute.execution(command)
        self.exitcode(err, out, exitcode, 'PyLint')

    def locate_tasks(self, dag_name):
        """Scan DAG file and Pull out all the tasks"""
        command = 'airflow tasks list -S {} {}'.format(self.dag, dag_name)
        output = self.execute.execution(command)
        out_formated = output[1].splitlines()[2:]
        print("\nTasks Detected for DAG: " + dag_name + "\n")
        print(out_formated)
        print("\n" + "".center(120, "=") + "\n")
        return out_formated

    def analyze_data(self, each_dag):
        """Run Test on the Tasks"""
        print("\n" + "Running AirFlow DAG Test".center(120, "="))
        print("".center(120, "="))
        err_code_list = []
        task_test = self.locate_tasks(each_dag)
        for task in task_test:
            test_task = "airflow test -dr -sd {}/{} {} {} '{}'".format(
                self.workdir, self.dag, each_dag, task, self.start)
            render_task = "airflow render -sd {}/{} {} {} '{}'".format(
                self.workdir, self.dag, each_dag, task, self.start)
            err, out, exitcode = self.execute.execution(test_task)
            err_2, out_2, exitcode_2 = self.execute.execution(render_task)
            if "ERROR" in out or len(err) > 1:
                print(err)
                print("{} {}".format(out, exitcode))
                err_code_list.append(1)
            else:
                print(out)
            if "ERROR" in out_2 or len(err_2) > 1:
                print(err_2)
                print("{} {}".format(out_2, exitcode_2))
                err_code_list.append(1)
            else:
                print(out_2)
            err_code_list.append(exitcode)
            err_code_list.append(exitcode_2)
        if any(x != 0 for x in err_code_list):
            self.error_list.append("AirFlow DAG Test - FAILED")
        else:
            self.error_list.append("AirFlow DAG Test - PASSED")
        self.error_list.insert(1, each_dag)

    def __iter__(self):
        return iter([i for i in self.error_list])


if __name__ == "__main__":
    print("".center(120, "="))
    print("\n\n" + "NEW TEST".center(120, "=") + "\n\n")
    OUTPUT_ERROR_LIST = []
    FINAL_LIST = []
    GIT_DATA = Commit_Data()
    GIT_TEAM = GIT_DATA.get_team()
    DAG_FILES = GIT_DATA.get_dag_files()
    for result in DAG_FILES:
        try:
            filter_check = Filters(result)
            filter_check()
            all_dags = GIT_DATA.locate_dags(result)
            testing = Verification(result)
            for dag in all_dags:
                testing.analyze_data(dag)
                if any("FAILED" in item for item in testing):
                    FINAL_LIST.append(1)
                else:
                    FINAL_LIST.append(0)
                OUTPUT_ERROR_LIST.append(testing)
        except FileNotFoundError:
            print("A FileNotFoundError occurred")
            if GIT_TEAM == "paz_radd_mo" or GIT_TEAM == "hrz_radd" or GIT_TEAM == "paz_dmp_do":
                print("skipping exception for paz_radd_mo and hrz_radd")
            else:
                raise
    print("\n\n" + "TEST RESULTS".center(120, "=") + "\n")
    for test_results in OUTPUT_ERROR_LIST:
        print([test for test in test_results])
    if any(x != 0 for x in FINAL_LIST):
        print("\nYour Pull Request has FAILED. Please review the log file and correct the errors\n"
              "and resubmit your Pull request by typing 'please rebuild' in Conversation under\n"
              "GitHub Pull Request tab.")
        print("".center(120, "=") + "\n")
        sys.exit(1)
    else:
        print("\nYour Pull Request PASSED. The pull request has been automatically merged.\n")
        print("".center(120, "=") + "\n")
        sys.exit(0)
