from .JobPath import JobPath
from .json_numpy import NumpyEncoder, NumpyDecoder
from .gathering import gather
from .simpleflock import SimpleFlock
from copy import deepcopy
from pathlib import Path
from datetime import datetime, timedelta
import dateutil.parser
import json


class DatabaseEntry(dict):
    def __init__(self, input_dict, database_path):
        super().__init__(deepcopy(input_dict))
        # convert fields to a genuine json objects
        self["N_runs"] = json.loads(
            json.dumps(self["N_runs"])
        )
        self["args"] = json.loads(
            json.dumps(self["args"], cls=NumpyEncoder),
        )
        self["kwargs"] = json.loads(
            json.dumps(self["kwargs"], cls=NumpyEncoder),
        )
        self.database_path = database_path

    def __eq__(self, other):
        try:
            return all(self[key] == other[key] for key in [
                "function_name", "args", "kwargs", "N_runs", "average_results"
            ])
        except KeyError:
            return all(self[key if key != "average_results" else "average_arrays"] == other[key] for key in [
                "function_name", "args", "kwargs", "N_runs", "average_results"
            ])

    def __ne__(self, other):
        return not self == other

    def __str__(self):
        return (
            f"function_name: {self['function_name']}\n"
            f"args: {self['args']}\n"
            f"kwargs: {self['kwargs']}\n"
            f"N_runs: {self['N_runs']}\n"
            f"average_results: {self['average_results']}"
        )

    @property
    def job_path(self):
        return JobPath(self.output_path.parent)

    @property
    def output_path(self):
        output_path = Path(self["output"])
        return output_path if output_path.is_absolute() else self.database_path.parent / output_path

    @property
    def output(self):
        with open(self.output_path) as f:
            result = json.load(f, cls=NumpyDecoder)
            if "successful_runs" not in result:
                result["successful_runs"] = [0] * result["N_total_runs"]
            return result

    def check_result(self):
        if self["status"] != "completed":
            gather(self)

        output = self.output
        needs_update = False

        num_finished_runs = len(output["successful_runs"]) + len(output["failed_runs"])

        if output["failed_runs"]:
            # legacy
            if isinstance(output["error_message"], str):
                print(
                    f"[ParallelAverage] Warning: {len(output['failed_runs'])} / {num_finished_runs} runs failed!\n"
                    # f"[ParallelAverage] Error message of run {output['run_id']}:\n\n"
                    # f"{output['error_message']['message']}"
                )
            else:
                print(
                    f"[ParallelAverage] Warning: {len(output['failed_runs'])} / {num_finished_runs} runs failed!\n"
                    f"[ParallelAverage] Error message of run {output['error_message']['run_id']}:\n\n"
                    f"{output['error_message']['message']}"
                )
            if "N_failed" not in self or len(output["failed_runs"]) != self["N_failed"]:
                self["N_failed"] = len(output["failed_runs"])
                needs_update = True

        if "N_not_ready" not in self or volume(self["N_runs"]) - num_finished_runs != self["N_not_ready"]:
            self["N_not_ready"] = volume(self["N_runs"]) - num_finished_runs
            needs_update = True

        if self["N_not_ready"] > 0:
            print(f"[ParallelAverage] Warning: {self['N_not_ready']} / {volume(self['N_runs'])} runs are not ready yet!")
        elif self["status"] == "running":
            self["status"] = "completed"
            needs_update = True

        if needs_update:
            self.save()

        return len(output["successful_runs"]) > 0

    def save(self):
        with SimpleFlock(str(self.database_path.parent / "dblock")):
            with open(self.database_path, 'r+') as f:
                if self.database_path.stat().st_size == 0:
                    entries = []
                else:
                    entries = json.load(f)

                entries = [DatabaseEntry(entry, self.database_path) for entry in entries]
                entries = [e for e in entries if e != self]
                entries.append(self)
                f.seek(0)
                json.dump(entries, f, indent=2, cls=NumpyEncoder)
                f.truncate()

    def remove(self):
        with SimpleFlock(str(self.database_path.parent / "dblock")):
            with open(self.database_path, 'r+') as f:
                if self.database_path.stat().st_size == 0:
                    entries = []
                else:
                    entries = json.load(f)

                entries = [DatabaseEntry(entry, self.database_path) for entry in entries]
                entries = [e for e in entries if e != self]
                f.seek(0)
                json.dump(entries, f, indent=2, cls=NumpyEncoder)
                f.truncate()

    @property
    def best_fitting_entries_in_database(self):
        return sorted(load_database(self.database_path), key=lambda db_entry: db_entry.distance_to(self))[:3]

    def distance_to(self, other):
        result = 0
        if self["function_name"] != other["function_name"]:
            return 100
        result += DatabaseEntry.__distance_between_args(self["args"], other["args"])
        result += DatabaseEntry.__distance_between_kwargs(self["kwargs"], other["kwargs"])
        if self["N_runs"] != other["N_runs"]:
            result += 1

        average_resultsA = self["average_results"] if "average_results" in self else self["average_arrays"]
        average_resultsB = other["average_results"] if "average_results" in other else other["average_arrays"]
        if average_resultsA != average_resultsB:
            result += 1

        return result

    @staticmethod
    def __distance_between_args(argsA, argsB):
        result = 0
        result += abs(len(argsA) - len(argsB))
        result += sum(1 if argA != argB else 0 for argA, argB in zip(argsA, argsB))
        return result

    @staticmethod
    def __distance_between_kwargs(kwargsA, kwargsB):
        result = 0
        result += len(set(kwargsA) ^ set(kwargsB))
        result += sum(1 if kwargsA[key] != kwargsB[key] else 0 for key in set(kwargsA) & set(kwargsB))
        return result


def load_database(database_path):
    with SimpleFlock(str(database_path.parent / "dblock")):
        with database_path.open() as f:
            if database_path.stat().st_size == 0:
                entries = []
            else:
                entries = json.load(f)

    return (DatabaseEntry(entry, database_path) for entry in entries)


def volume(x):
    if isinstance(x, int):
        return x

    result = 1
    for x_i in x:
        result *= x_i
    return result


def check_latest_jobs(path='.', weeks=1, days=0):
    since = datetime.now() - timedelta(weeks=weeks) - timedelta(days=days)
    latest_entries = (
        entry for entry in load_database(Path(path) / "parallel_average_database.json")
        if "datetime" in entry and dateutil.parser.parse(entry["datetime"]) > since
    )
    for entry in latest_entries:
        print(f"[ParallelAverage] Info: checking {entry['job_name']}")
        entry.check_result()
