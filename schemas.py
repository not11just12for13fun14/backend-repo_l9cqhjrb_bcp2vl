"""
Database Schemas for Leadflow

Each Pydantic model represents a collection in MongoDB.
Collection name is the lowercase of the class name.

Collections:
- Project
- User
- Lead
- Action
- Note
"""
from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Optional, List, Literal
from datetime import datetime

# ---- Core Schemas ----

Role = Literal["admin", "setter", "closer", "viewer"]
LeadStatus = Literal["new", "active", "won", "lost", "paused"]


class Project(BaseModel):
    name: str = Field(..., description="Project name")
    steps: List[str] = Field(..., description="Ordered pipeline steps (left → right)")
    members: List[str] = Field(default_factory=list, description="User IDs in the project")
    created_at: Optional[datetime] = Field(default=None)


class User(BaseModel):
    name: str
    email: str
    role: Role = Field("viewer")
    permissions: List[str] = Field(default_factory=list)
    leads_assignes: List[str] = Field(default_factory=list, description="List of lead IDs assigned to user")


class Note(BaseModel):
    author_id: str
    content: str
    created_at: Optional[datetime] = None


class Action(BaseModel):
    project_id: str
    lead_id: str
    type: Literal["created", "called", "meeting", "advanced", "won", "lost", "comment"]
    from_step: Optional[str] = None
    to_step: Optional[str] = None
    meta: Optional[dict] = None
    created_at: Optional[datetime] = None


class Lead(BaseModel):
    name: str
    source: Optional[str] = None
    entered_at: Optional[datetime] = None
    project_id: str
    current_step: str
    assigned_to: Optional[str] = None
    status: LeadStatus = Field("new")
    notes: List[Note] = Field(default_factory=list)
    appointments: List[dict] = Field(default_factory=list)
    history: List[Action] = Field(default_factory=list)
