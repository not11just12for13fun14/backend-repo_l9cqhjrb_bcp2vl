import os
import random
import string
import time
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from database import get_collection, now_ts

app = FastAPI(title="Leadflow API")

# CORS: allow all during demo
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# ---- Models ----
class Lead(BaseModel):
    _id: str
    project_id: str
    name: str
    email: str
    step: str
    source: str
    assigned_to: Optional[str] = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

class User(BaseModel):
    _id: str
    project_id: str
    name: str
    role: str  # admin, setter, closer

class Project(BaseModel):
    _id: str
    name: str

# ---- Util ----
STEPS = ["New", "Qualified", "Meeting", "Closed"]
SOURCES = ["ads", "events", "referral", "inbound"]
ROLES = ["admin", "setter", "closer"]


def sid(prefix: str = "") -> str:
    rand = "".join(random.choices(string.ascii_lowercase + string.digits, k=10))
    return f"{prefix}{rand}"


# ---- WebSocket manager ----
class ConnectionManager:
    def __init__(self):
        self.rooms: Dict[str, List[WebSocket]] = {}

    async def connect(self, project_id: str, websocket: WebSocket):
        await websocket.accept()
        self.rooms.setdefault(project_id, []).append(websocket)

    def disconnect(self, project_id: str, websocket: WebSocket):
        if project_id in self.rooms and websocket in self.rooms[project_id]:
            self.rooms[project_id].remove(websocket)

    async def emit(self, project_id: str, event: str, payload: Dict[str, Any]):
        if project_id not in self.rooms:
            return
        for ws in list(self.rooms[project_id]):
            try:
                await ws.send_json({"type": event, "data": payload})
            except Exception:
                pass

manager = ConnectionManager()

# ---- Routes ----
@app.get("/")
def root():
    return {"ok": True, "service": "Leadflow API"}

@app.get("/test")
def test():
    return {"status": "ok", "time": time.time()}

@app.get("/api/demo/bootstrap")
def bootstrap():
    projects = get_collection("projects")
    users = get_collection("users")
    leads = get_collection("leads")

    proj = projects.find_one({"name": "Leadflow Demo"})
    if not proj:
        proj = {"_id": sid("proj_"), "name": "Leadflow Demo"}
        projects.insert_one(proj)

    # create users if missing
    existing_users = list(users.find({"project_id": proj["_id"]}))
    if not existing_users:
        for i, role in enumerate(["admin", "setter", "setter", "closer"]):
            users.insert_one({
                "_id": sid("usr_"),
                "project_id": proj["_id"],
                "name": ["Ava", "Ben", "Chloe", "Diego"][i],
                "role": role,
            })
        existing_users = list(users.find({"project_id": proj["_id"]}))

    # create ~120 leads if missing
    existing_lead_count = leads.count_documents({"project_id": proj["_id"]})
    if existing_lead_count < 100:
        for i in range(120):
            leads.insert_one({
                "_id": sid("lead_"),
                "project_id": proj["_id"],
                "name": f"Lead {i+1}",
                "email": f"lead{i+1}@example.com",
                "step": random.choice(STEPS),
                "source": random.choice(SOURCES),
                "assigned_to": None,
                "created_at": time.time(),
                "updated_at": time.time(),
            })

    return {
        "project": proj,
        "steps": STEPS,
        "users": list(users.find({"project_id": proj["_id"]})),
        "leads": list(leads.find({"project_id": proj["_id"]})),
    }

class AdvanceRequest(BaseModel):
    lead_id: str

@app.post("/api/advance")
def advance(req: AdvanceRequest):
    leads = get_collection("leads")
    lead = leads.find_one({"_id": req.lead_id})
    if not lead:
        return {"ok": False, "error": "lead_not_found"}
    idx = STEPS.index(lead["step"]) if lead["step"] in STEPS else 0
    idx = min(idx + 1, len(STEPS) - 1)
    lead["step"] = STEPS[idx]
    lead["updated_at"] = time.time()
    return {"ok": True, "lead": lead}

class AssignRequest(BaseModel):
    lead_id: str
    user_id: Optional[str] = None

@app.post("/api/assign")
def assign(req: AssignRequest):
    leads = get_collection("leads")
    lead = leads.find_one({"_id": req.lead_id})
    if not lead:
        return {"ok": False, "error": "lead_not_found"}
    lead["assigned_to"] = req.user_id
    lead["updated_at"] = time.time()
    return {"ok": True, "lead": lead}

@app.post("/api/advance-random")
def advance_random():
    leads = get_collection("leads")
    all_leads = list(leads.find())
    if not all_leads:
        return {"ok": False, "count": 0}
    changed = 0
    for _ in range(random.randint(1, 4)):
        lead = random.choice(all_leads)
        idx = STEPS.index(lead["step"]) if lead["step"] in STEPS else 0
        if idx < len(STEPS) - 1:
            lead["step"] = STEPS[idx + 1]
            lead["updated_at"] = time.time()
            changed += 1
    return {"ok": True, "count": changed}

# WebSocket
@app.websocket("/ws/projects/{project_id}")
async def ws_project(websocket: WebSocket, project_id: str):
    await manager.connect(project_id, websocket)
    try:
        while True:
            await websocket.receive_text()  # keepalive or ignore
    except WebSocketDisconnect:
        manager.disconnect(project_id, websocket)

