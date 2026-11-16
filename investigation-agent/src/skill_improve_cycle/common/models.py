"""Inputs and verified output of one email investigation."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field


class InvestigationRequest(BaseModel):
    gmail_sender: EmailStr
    mailbox: EmailStr
    scenario: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,60}$")
    mongo_database: str
    logfire_project: str
    notion_database_name: str
    now_utc: datetime


class Evidence(BaseModel):
    source: Literal["gmail", "mongo", "logfire", "notion"]
    reference: str = Field(description="Exact identifier or URL observed in a tool response.")
    finding: str


class Diagnosis(BaseModel):
    customer: str | None
    status: Literal["ongoing", "recovered", "unknown"]
    summary: str
    likely_cause: str
    evidence: list[Evidence]
    next_steps: list[str]
    notion_page_url: str | None = Field(description="URL confirmed by Notion readback; null when registration could not be completed.")
