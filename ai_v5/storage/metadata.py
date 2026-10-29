# ai_v5/storage/metadata.py
import os
import json
import datetime

class TrainingMetadata:
    def __init__(self, meta_path="ai_v5/models/metadata.json"):
        self.meta_path = meta_path
        os.makedirs(os.path.dirname(self.meta_path), exist_ok=True)
        if not os.path.exists(self.meta_path):
            with open(self.meta_path, "w", encoding="utf-8") as f:
                json.dump([], f)

    def log_run(self, hyperparams: dict, metrics: dict, status="SUCCESS"):
        with open(self.meta_path, "r", encoding="utf-8") as f:
            history = json.load(f)
            
        run_log = {
            "timestamp": datetime.datetime.now().isoformat(),
            "hyperparams": hyperparams,
            "metrics": metrics,
            "status": status
        }
        
        history.append(run_log)
        with open(self.meta_path, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=4)