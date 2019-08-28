from .simpleflock import SimpleFlock
from copy import deepcopy
import json


class DatabaseEntry(dict):
    def __init__(self, input_dict, encoder=None):
        super().__init__(deepcopy(input_dict))
        self.encoder = encoder

        # convert 'args' and 'kwargs' into a genuine json object
        self["args"] = json.loads(
            json.dumps(self["args"], cls=encoder),
        )
        self["kwargs"] = json.loads(
            json.dumps(self["kwargs"], cls=encoder),
        )

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
        average_results = self['average_results'] if 'average_results' in self else (
            self['average_arrays'] if 'average_arrays' in self else None
        )

        return (
            f"function_name: {self['function_name']}\n"
            f"args: {self['args']}\n"
            f"kwargs: {self['kwargs']}\n"
            f"N_runs: {self['N_runs']}\n"
            f"average_results: {average_results}"
        )

    def save(self, database_path):
        with SimpleFlock(str(database_path.parent / "dblock")):
            with open(database_path, 'r+') as f:
                if database_path.stat().st_size == 0:
                    entries = []
                else:
                    entries = json.load(f)

                entries = [DatabaseEntry(entry) for entry in entries]
                entries = [e for e in entries if e != self]
                entries.append(self)
                f.seek(0)
                json.dump(entries, f, indent=2, cls=self.encoder)
                f.truncate()

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

    return [DatabaseEntry(entry) for entry in entries]