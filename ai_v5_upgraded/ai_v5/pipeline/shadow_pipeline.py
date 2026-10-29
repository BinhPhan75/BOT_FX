# ai_v5/pipeline/shadow_pipeline.py
import json
import os
import datetime

def log_shadow_decision(symbol: str, pattern: str, ai_prob: float, v4_score: int, action: str):
    log_path = "ai_v5/models/shadow_logs.json"
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    
    entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "symbol": symbol,
        "pattern": pattern,
        "ai_probability": ai_prob,
        "v4_score": v4_score,
        "ai_recommendation": action
    }
    
    history = []
    if os.path.exists(log_path):
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                history = json.load(f)
        except:
            history = []
            
    history.append(entry)
    with open(log_path, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=4)