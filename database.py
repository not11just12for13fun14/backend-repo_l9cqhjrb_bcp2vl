"""
Database Helper Functions with In-Memory Fallback

Uses MongoDB when DATABASE_URL and DATABASE_NAME are provided.
If not available, falls back to an in-memory store that mimics the subset of
PyMongo APIs used by the app (find, find_one, insert_one, update_one, list_collection_names).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional, Union
import os

from dotenv import load_dotenv
from pydantic import BaseModel

# Load env
load_dotenv()

# Try Mongo first
from pymongo import MongoClient

_client = None
_db = None

database_url = os.getenv("DATABASE_URL")
database_name = os.getenv("DATABASE_NAME")

if database_url and database_name:
    try:
        _client = MongoClient(database_url, serverSelectionTimeoutMS=2000)
        # Trigger a server selection to fail fast if not reachable
        _client.server_info()
        _db = _client[database_name]
    except Exception:
        _client = None
        _db = None


# ---------------------------
# In-Memory Fallback classes
# ---------------------------
class _InsertOneResult:
    def __init__(self, inserted_id: str):
        self.inserted_id = inserted_id


class MemoryCollection:
    def __init__(self, name: str, store: Dict[str, Dict[str, Any]]):
        self.name = name
        self.store = store  # id -> doc
        self._auto = 0

    def _gen_id(self) -> str:
        self._auto += 1
        return f"mem_{self.name}_{self._auto}"

    def find(self, filter_dict: Optional[Dict[str, Any]] = None) -> Iterator[Dict[str, Any]]:
        filter_dict = filter_dict or {}
        for doc in list(self.store.values()):
            if _match_filter(doc, filter_dict):
                yield dict(doc)

    def find_one(self, filter_dict: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        for doc in self.find(filter_dict):
            return dict(doc)
        return None

    def insert_one(self, data: Dict[str, Any]) -> _InsertOneResult:
        _id = self._gen_id()
        to_insert = dict(data)
        to_insert["_id"] = _id
        self.store[_id] = to_insert
        return _InsertOneResult(_id)

    def update_one(self, filter_dict: Dict[str, Any], update_doc: Dict[str, Any]):
        # Very small subset: supports $set and $push
        doc = self.find_one(filter_dict)
        if not doc:
            return
        current = self.store[doc["_id"]]
        if "$set" in update_doc:
            for k, v in update_doc["$set"].items():
                current[k] = v
        if "$push" in update_doc:
            for k, v in update_doc["$push"].items():
                current.setdefault(k, [])
                current[k].append(v)
        self.store[doc["_id"]] = current


class MemoryDB:
    def __init__(self, name: str = "memory"):
        self.name = name
        self._collections: Dict[str, MemoryCollection] = {}
        self._raw: Dict[str, Dict[str, Dict[str, Any]]] = {}

    def __getitem__(self, collection_name: str) -> MemoryCollection:
        if collection_name not in self._collections:
            self._raw.setdefault(collection_name, {})
            self._collections[collection_name] = MemoryCollection(collection_name, self._raw[collection_name])
        return self._collections[collection_name]

    def list_collection_names(self) -> List[str]:
        return list(self._collections.keys())


def _match_filter(doc: Dict[str, Any], filt: Dict[str, Any]) -> bool:
    for k, v in filt.items():
        if isinstance(v, dict) and "$in" in v:
            if doc.get(k) not in v["$in"]:
                return False
        else:
            if doc.get(k) != v:
                return False
    return True


# Exposed handle: either real Mongo DB or memory DB
if _db is None:
    db = MemoryDB()
else:
    db = _db


# ---------------------------
# Helper functions (work for both backends)
# ---------------------------

def create_document(collection_name: str, data: Union[BaseModel, dict]) -> str:
    if isinstance(data, BaseModel):
        data_dict = data.model_dump()
    else:
        data_dict = dict(data)

    now = datetime.now(timezone.utc)
    data_dict.setdefault("created_at", now)
    data_dict["updated_at"] = now

    result = db[collection_name].insert_one(data_dict)
    return str(result.inserted_id)


def get_documents(collection_name: str, filter_dict: Optional[dict] = None, limit: Optional[int] = None) -> List[dict]:
    cursor = db[collection_name].find(filter_dict or {})
    docs = list(cursor)
    if limit:
        docs = docs[:limit]
    return docs
