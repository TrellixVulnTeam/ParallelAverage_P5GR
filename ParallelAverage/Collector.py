"""
This class produces a total result from every individual task result it finds in the 'data_output' folder.
The total result has the same structure as an individual result.
"""


from pathlib import Path
from collections import defaultdict
import json
from .Dataset import Dataset
from .simpleflock import SimpleFlock


class Collector:
    def __init__(self, database_entry, database_path, encoder, decoder):
        self.database_entry = database_entry
        self.job_path = Path(database_entry["output"]).parent
        self.input_path = self.job_path / "input"
        self.data_path = self.job_path / "data_output"
        self.data_path.mkdir(exist_ok=True)
        self.task_files = [t for t in self.data_path.iterdir() if str(t).endswith("_task_output.json")]

        self.average_results = database_entry["average_results"]
        self.encoder = encoder
        self.decoder = decoder

        self.total_result = defaultdict(lambda: Dataset())
        self.successful_runs = []
        self.failed_runs = []
        self.error_message = ""
        self.error_run_id = -1
        self.raw_results_map = {}

    def run(self):
        # try legacy code first
        if [f for f in Path(self.database_entry["output"]).parent.iterdir() if f.is_dir() and f.name[:1].isdigit()]:
            import os
            from subprocess import run

            package_path = Path(os.path.abspath(__file__)).parent
            average_collector_file = package_path / "legacy" / "average_collector.sh"
            run([str(average_collector_file), str(self.job_path.resolve()), str(package_path)])

            with open(Path(self.database_entry["output"])) as f:
                output = json.load(f)
            output["successful_runs"] = list(set(range(output["N_total_runs"])) - set(output["failed_runs"]))
            with open(Path(self.database_entry["output"]), 'w') as f:
                json.dump(output, f, indent=2)

            return

        for task_file in self.task_files:
            with SimpleFlock(str(task_file) + ".lock"):
                with open(task_file, 'r') as f:
                    task_output = json.load(f)

            if task_output["successful_runs"]:
                self.successful_runs += task_output["successful_runs"]

                if self.average_results is not None:
                    for i, r in enumerate(task_output["task_result"]):
                        if self.to_be_averaged(i):
                            self.total_result[i] += Dataset.from_json(r)
                        else:
                            self.total_result[i] = json.loads(json.dumps(r), cls=self.decoder)

            if task_output["failed_runs"]:
                self.failed_runs += task_output["failed_runs"]
                self.error_message = task_output["error_message"]["message"]
                self.error_run_id = task_output["error_message"]["run_id"]

            self.raw_results_map.update(task_output["raw_results_map"] or {})

        self.dump()

    def to_be_averaged(self, i):
        return self.average_results is not None and (self.average_results == 'all' or i in self.average_results)

    def dump(self):
        total_result_list = [self.total_result[i] for i in sorted(self.total_result)]

        output = {
            "successful_runs": self.successful_runs,
            "failed_runs": self.failed_runs,
            "error_message": self.error_message,
            "error_run_id": self.error_run_id,
            "raw_results_map": self.raw_results_map
        }
        if self.average_results is not None:
            output.update({
                "result": polish([
                    r.mean if self.to_be_averaged(i) else r
                    for i, r in enumerate(total_result_list)
                ]),
                "estimated_error": polish([
                    r.estimated_error if self.to_be_averaged(i) else None
                    for i, r in enumerate(total_result_list)
                ]),
                "estimated_variance": polish([
                    r.estimated_variance if self.to_be_averaged(i) else None
                    for i, r in enumerate(total_result_list)
                ]),
                "total_weight": polish([
                    r.total_weight if self.to_be_averaged(i) else None
                    for i, r in enumerate(total_result_list)
                ])
            })

        with open(self.job_path / "output.json", 'w') as f:
            json.dump(output, f, indent=2, cls=self.encoder)


def polish(x):
    if isinstance(x, (list, tuple)) and len(x) == 1:
        x = x[0]
    return x