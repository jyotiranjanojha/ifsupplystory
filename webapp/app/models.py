from typing import List, Optional

from pydantic import BaseModel, Field


class Scope(BaseModel):
    product: Optional[str] = None
    site: Optional[str] = None
    customer: Optional[str] = None
    node: Optional[str] = None


class ValidationRequest(BaseModel):
    week_id: Optional[str] = None
    scenario_id: Optional[str] = None
    scope: Scope = Field(default_factory=Scope)
    focus_areas: List[str] = Field(default_factory=lambda: ["master_data", "bom", "parameters", "output_sanity"])


class CompareRequest(BaseModel):
    week_id: Optional[str] = None
    base_scenario_id: Optional[str] = None
    compare_scenario_id: Optional[str] = None
    scope: Scope = Field(default_factory=Scope)
    metrics: List[str] = Field(default_factory=lambda: ["unmet_demand", "capacity_utilization", "lateness"])


class RootCauseRequest(BaseModel):
    week_id: Optional[str] = None
    scenario_id: Optional[str] = None
    demand_id: Optional[str] = None
    scope: Scope = Field(default_factory=Scope)


class ChatMessage(BaseModel):
    role: str
    content: str


class KnowledgeGraphRequest(BaseModel):
    week_id: Optional[str] = None
    scenario_id: Optional[str] = None
    item_id: Optional[str] = None
    scope: Scope = Field(default_factory=Scope)


class ChatRequest(BaseModel):
    question: str
    week_id: Optional[str] = None
    scenario_id: Optional[str] = None
    llm_enabled: bool = True
    llm_model: Optional[str] = None
    history: List[ChatMessage] = Field(default_factory=list)
    scope: Scope = Field(default_factory=Scope)
