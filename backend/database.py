import os
import time
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv

load_dotenv()

# Optional Mongo support
USE_MONGO = bool(os.getenv("DATABASE_URL")) and bool(os.getenv("DATABASE_NAME"))

if USE_MONGO:
    from pymongo import MongoClient
    mongo_client = MongoClient(os.getenv("DATABASE_URL"))
    db = mongo_client[os.getenv("DATABASE_NAME")]
else:
    mongo_client = None
    db = None

class MemoryCollection:
    def __init__(self):
        self.data: List[Dict[str, Any]] = []

    def insert_one(self, doc: Dict[str, Any]):
        self.data.append(doc)
        return type("_R", (), {"inserted_id": doc.get("_id")})

    def find(self, filter_dict: Optional[Dict[str, Any]] = None):
        if not filter_dict:
            for d in list(self.data):
                yield d
            return
        for d in list(self.data):
            ok = True
            for k, v in filter_dict.items():
                if d.get(k) != v:
                    ok = False
                    break
            if ok:
                yield d

    def find_one(self, filter_dict: Dict[str, Any]):
        for d in self.find(filter_dict):
            return d
        return None

    def update_one(self, filter_dict: Dict[str, Any], update_dict: Dict[str, Any]):
        doc = self.find_one(filter_dict)
        if not doc:
            return type("_UR", (), {"matched_count": 0, "modified_count": 0})
        if "$set" in update_dict:
            for k, v in update_dict["$set"].items():
                doc[k] = v
        return type("_UR", (), {"matched_count": 1, "modified_count": 1})

    def count_documents(self, filter_dict: Optional[Dict[str, Any]] = None):
        return len(list(self.find(filter_dict)))

class MemoryDB:
    def __init__(self):
        self._collections: Dict[str, MemoryCollection] = {}

    def __getitem__(self, name: str) -> MemoryCollection:
        if name not in self._collections:
            self._collections[name] = MemoryCollection()
        return self._collections[name]

# Provide a simple helper to get a collection that works with either Mongo or memory

def get_collection(name: str):
    if USE_MONGO:
        return db[name]
    global _MEM_DB
    try:
        _MEM_DB
    except NameError:
        _MEM_DB = MemoryDB()
    return _MEM_DB[name]

# Convenience helpers

def now_ts() -> float:
    return time.time()
