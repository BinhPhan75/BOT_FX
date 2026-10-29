# ai_v5/storage/feature_cache.py
import time

class FeatureCache:
    def __init__(self, ttl_seconds=60):
        self.cache = {}
        self.ttl = ttl_seconds

    def get(self, key: str):
        if key in self.cache:
            entry = self.cache[key]
            if time.time() - entry["timestamp"] < self.ttl:
                return entry["data"]
            del self.cache[key]
        return None

    def set(self, key: str, data):
        self.cache[key] = {
            "data": data,
            "timestamp": time.time()
        }

    def clear(self):
        self.cache.clear()