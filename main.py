import os
import random
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from database import db, create_document, get_documents

app = FastAPI(title="Leadflow API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------
# WebSocket connection manager
# ---------------------------
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, project_id: str, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.setdefault(project_id, []).append(websocket)

    def disconnect(self, project_id: str, websocket: WebSocket):
        if project_id in self.active_connections:
            try:
                self.active_connections[project_id].remove(websocket)
            except ValueError:
                pass

    async def broadcast(self, project_id: str, message: dict):
        for ws in list(self.active_connections.get(project_id, [])):
            try:
                await ws.send_json(message)
            except Exception:
                # Best-effort cleanup if send fails
                self.disconnect(project_id, ws)


manager = ConnectionManager()


# ---------------------------
# Utility helpers
# ---------------------------

def to_obj_id(id_str: str):
    from bson import ObjectId

    try:
        return ObjectId(id_str)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid ID format")


# ---------------------------
# Health + Test endpoints
# ---------------------------
@app.get("/")
def read_root():
    return {"message": "Leadflow Backend Running"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": [],
    }

    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name if hasattr(db, "name") else "✅ Connected"
            response["connection_status"] = "Connected"
            try:
                collections = db.list_collection_names()
                response["collections"] = collections[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️  Connected but Error: {str(e)[:50]}"
        else:
            response["database"] = "⚠️  Available but not initialized"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:50]}"

    return response


# ---------------------------
# Demo bootstrap
# ---------------------------
class DemoBootstrapResponse(BaseModel):
    project_id: str
    steps: List[str]
    users: List[dict]
    leads: List[dict]


def ensure_demo_project() -> str:
    """Create a demo project with members and sample leads if missing."""
    # Try to find existing demo project
    project = db["project"].find_one({"name": "Leadflow Demo"})
    if project:
        return str(project["_id"])

    steps = ["Acquisition", "Setter", "Closer", "Vente"]
    project_id = create_document(
        "project", {"name": "Leadflow Demo", "steps": steps, "members": [], "created_at": datetime.now(timezone.utc)}
    )

    # Create users
    users = [
        {"name": "Alice Admin", "email": "admin@leadflow.app", "role": "admin"},
        {"name": "Sam Setter", "email": "setter@leadflow.app", "role": "setter"},
        {"name": "Casey Closer", "email": "closer@leadflow.app", "role": "closer"},
        {"name": "Vera Viewer", "email": "viewer@leadflow.app", "role": "viewer"},
    ]
    user_ids = []
    for u in users:
        uid = create_document("user", {**u, "permissions": [], "leads_assignes": []})
        user_ids.append(uid)

    # Generate random leads
    first_names = [
        "Leo",
        "Maya",
        "Noah",
        "Emma",
        "Liam",
        "Olivia",
        "Ava",
        "Ethan",
        "Sofia",
        "Lucas",
        "Mila",
    ]
    sources = ["Ads", "Referral", "Website", "Outbound", "Event"]
    for i in range(35):
        name = random.choice(first_names) + f" {random.randint(100,999)}"
        step_index = random.choices([0, 1, 2, 3], weights=[5, 4, 3, 2])[0]
        current_step = steps[step_index]
        assigned = random.choice(user_ids[1:3]) if step_index >= 1 else None
        lead = {
            "name": name,
            "source": random.choice(sources),
            "entered_at": datetime.now(timezone.utc),
            "project_id": project_id,
            "current_step": current_step,
            "assigned_to": assigned,
            "status": "active",
            "notes": [],
            "appointments": [],
            "history": [
                {
                    "project_id": project_id,
                    "lead_id": "",
                    "type": "created",
                    "to_step": current_step,
                    "created_at": datetime.now(timezone.utc),
                }
            ],
        }
        create_document("lead", lead)

    # Attach members to project
    db["project"].update_one({"_id": to_obj_id(project_id)}, {"$set": {"members": user_ids}})

    return project_id


@app.get("/api/demo/bootstrap", response_model=DemoBootstrapResponse)
def demo_bootstrap():
    project_id = ensure_demo_project()
    project = db["project"].find_one({"_id": to_obj_id(project_id)})
    users = list(db["user"].find({"_id": {"$in": [to_obj_id(u) for u in project.get("members", [])]}}))
    for u in users:
        u["id"] = str(u.pop("_id"))
    leads = list(db["lead"].find({"project_id": project_id}))
    for l in leads:
        l["id"] = str(l.pop("_id"))
    return {
        "project_id": project_id,
        "steps": project.get("steps", []),
        "users": users,
        "leads": leads,
    }


# ---------------------------
# Projects & Leads
# ---------------------------
@app.get("/api/projects")
def list_projects():
    projects = list(db["project"].find())
    for p in projects:
        p["id"] = str(p.pop("_id"))
    return projects


@app.get("/api/projects/{project_id}")
def get_project(project_id: str):
    project = db["project"].find_one({"_id": to_obj_id(project_id)})
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    project["id"] = str(project.pop("_id"))
    return project


@app.get("/api/leads")
def get_leads(project_id: Optional[str] = None, assigned_to: Optional[str] = None):
    query: Dict = {}
    if project_id:
        query["project_id"] = project_id
    if assigned_to:
        query["assigned_to"] = assigned_to
    leads = list(db["lead"].find(query))
    for l in leads:
        l["id"] = str(l.pop("_id"))
    return leads


@app.get("/api/leads/{lead_id}")
def get_lead(lead_id: str):
    lead = db["lead"].find_one({"_id": to_obj_id(lead_id)})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    lead["id"] = str(lead.pop("_id"))
    return lead


class AdvanceRequest(BaseModel):
    to_step: Optional[str] = None


@app.post("/api/leads/{lead_id}/advance")
async def advance_lead(lead_id: str, payload: AdvanceRequest):
    lead = db["lead"].find_one({"_id": to_obj_id(lead_id)})
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")

    project = db["project"].find_one({"name": "Leadflow Demo"}) if not lead.get("project_id") else db["project"].find_one({"_id": to_obj_id(lead["project_id"])})
    if not project:
        raise HTTPException(status_code=400, detail="Project not found for lead")
    steps = project.get("steps", [])

    current_step = lead.get("current_step")
    if payload.to_step and payload.to_step in steps:
        new_step = payload.to_step
    else:
        try:
            idx = steps.index(current_step)
            new_step = steps[min(idx + 1, len(steps) - 1)]
        except ValueError:
            new_step = steps[0] if steps else current_step

    status = lead.get("status", "active")
    if new_step == steps[-1]:
        status = "won"

    db["lead"].update_one(
        {"_id": to_obj_id(lead_id)},
        {
            "$set": {"current_step": new_step, "status": status, "updated_at": datetime.now(timezone.utc)},
            "$push": {
                "history": {
                    "project_id": str(project.get("_id")),
                    "lead_id": lead_id,
                    "type": "advanced",
                    "from_step": current_step,
                    "to_step": new_step,
                    "created_at": datetime.now(timezone.utc),
                }
            },
        },
    )

    # Broadcast event
    await manager.broadcast(
        str(project.get("_id")),
        {"type": "lead_advanced", "lead_id": lead_id, "from": current_step, "to": new_step},
    )

    updated = db["lead"].find_one({"_id": to_obj_id(lead_id)})
    updated["id"] = str(updated.pop("_id"))
    return updated


@app.post("/api/projects/{project_id}/advance-random")
async def advance_random(project_id: str):
    leads = list(db["lead"].find({"project_id": project_id}))
    if not leads:
        raise HTTPException(status_code=404, detail="No leads in project")
    lead = random.choice(leads)
    return await advance_lead(str(lead["_id"]))


# ---------------------------
# WebSocket for realtime updates
# ---------------------------
@app.websocket("/ws/projects/{project_id}")
async def websocket_endpoint(websocket: WebSocket, project_id: str):
    await manager.connect(project_id, websocket)
    try:
        while True:
            # We don't expect messages from client for now; keep alive
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(project_id, websocket)


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
