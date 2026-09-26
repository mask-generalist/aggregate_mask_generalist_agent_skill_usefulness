from typing import List, Literal

from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field

from cuga.backend.activity_tracker.tracker import ActivityTracker

tracker = ActivityTracker()


class Step(BaseModel):
    step_description: str = Field(
        ...,
        description="A natural language representation of the next step that the action agent will perform.",
    )
    rationale: str = Field(
        ...,
        description="Reasoning based on the analysis to justify why this step is necessary.",
    )


class Metadata(BaseModel):
    estimated_steps: int = Field(
        ...,
        description="Estimated number of steps (clicks or types or answer) needed to perform by the action agent.",
    )
    confidence_level: float = Field(
        ...,
        description="Confidence level in the accuracy of the plan, represented as a float between 0 and 1.",
    )


class NextAgentPlan(BaseModel):
    thoughts: List[str] = Field(
        ...,
        description="A list of step by step thoughts.",
    )
    next_agent: Literal['ActionAgent', 'MemorizeAgent', 'QaAgent', 'ConcludeTaskAgent']
    instruction: str


parser = PydanticOutputParser(pydantic_object=NextAgentPlan)
