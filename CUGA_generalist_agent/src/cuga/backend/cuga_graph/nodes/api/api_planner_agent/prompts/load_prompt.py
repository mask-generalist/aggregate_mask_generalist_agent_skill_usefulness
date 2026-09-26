from typing import List

from pydantic import BaseModel, Field

from cuga.backend.activity_tracker.tracker import ActivityTracker


from typing import Optional, Union
from enum import Enum


# ---------------- Helper Enums and Models ----------------
from typing_extensions import Annotated

# ---------------- Helper Enums and Models ----------------
tracker = ActivityTracker()


class ActionName(str, Enum):
    """Enumeration of possible actions the APIPlanner can decide."""

    CODER_AGENT = "CoderAgent"
    API_FILTERING_AGENT = "ApiShortlistingAgent"
    CONCLUDE_TASK = "ConcludeTask"
    CONSULT_WITH_HUMAN = "ConsultWithHuman"


class ActionNameNoHITL(str, Enum):
    """Enumeration of possible actions without human-in-the-loop."""

    CODER_AGENT = "CoderAgent"
    API_FILTERING_AGENT = "ApiShortlistingAgent"
    CONCLUDE_TASK = "ConcludeTask"


class ConcludeTaskStatus(str, Enum):
    """Status for the ConcludeTask action."""

    SUCCESS = "success"
    FAILURE = "failure"


class ApiDescription(BaseModel):
    """Describes an API endpoint relevant to a CoderAgent task."""

    app_name: str
    api_name: str
    api_description: Optional[str] = None


# ---------------- Action Input Models ----------------


class CoderAgentInput(BaseModel):
    """Input specific to the CoderAgent action."""

    task_description: str
    relevant_apis: List[ApiDescription]
    context_variables_from_history: List[str]


class ApiShortlistingAgentInput(BaseModel):
    """Input specific to the ApiFilteringAgent action."""

    app_name: str
    task_description: str


class ConcludeTaskInput(BaseModel):
    """Input specific to the ConcludeTask action."""

    status: ConcludeTaskStatus
    final_response: str
    summary_of_execution: Optional[str] = None


class ConsultWithHumanInput(BaseModel):
    """Input specific to the ConsultWithHuman action."""

    question: str = Field(description="The question or clarification needed from the human")
    context: Optional[str] = Field(
        None, description="Additional context about why this consultation is needed"
    )
    suggested_options: Optional[List[str]] = Field(
        None, description="Optional list of suggested response options for the human"
    )


APIPlannerInput = Annotated[
    Union[ApiShortlistingAgentInput, CoderAgentInput, ConcludeTaskInput, ConsultWithHumanInput],
    Field(discriminator='agent_type'),
]

# ---------------- Main APIPlanner Output Model ----------------


class APIPlannerOutput(BaseModel):
    """
    Defines the structure of the JSON output from the APIPlanner.
    """

    thoughts: List[str] = Field(
        description="Step-by-step thinking, reflection on history, and reasoning for the chosen action."
    )
    action: ActionName = Field(description="The chosen action to be executed next.")
    action_input_shortlisting_agent: Optional[ApiShortlistingAgentInput] = None
    action_input_coder_agent: Optional[CoderAgentInput] = None
    action_input_conclude_task: Optional[ConcludeTaskInput] = None
    action_input_consult_with_human: Optional[ConsultWithHumanInput] = None


class APIPlannerOutputLite(BaseModel):
    """
    Defines the structure of the JSON output from the APIPlanner.
    """

    action: ActionName = Field(description="The chosen action to be executed next.")
    action_input_shortlisting_agent: Optional[ApiShortlistingAgentInput] = None
    action_input_coder_agent: Optional[CoderAgentInput] = None
    action_input_conclude_task: Optional[ConcludeTaskInput] = None
    action_input_consult_with_human: Optional[ConsultWithHumanInput] = None


class APIPlannerOutputWX(BaseModel):
    """
    Defines the structure of the JSON output from the APIPlanner.
    """

    thoughts: List[str] = Field(
        description="Step-by-step thinking, reflection on history, and reasoning for the chosen action."
    )
    action: ActionName = Field(description="The chosen action to be executed next.")
    action_input_shortlisting_agent: ApiShortlistingAgentInput
    action_input_coder_agent: CoderAgentInput
    action_input_conclude_task: ConcludeTaskInput
    action_input_consult_with_human: ConsultWithHumanInput


class APIPlannerOutputNoHITL(BaseModel):
    """
    Output schema for APIPlanner without human-in-the-loop support.
    """

    thoughts: List[str] = Field(
        description="Step-by-step thinking, reflection on history, and reasoning for the chosen action."
    )
    action: ActionNameNoHITL = Field(description="The chosen action to be executed next.")
    action_input_shortlisting_agent: Optional[ApiShortlistingAgentInput] = None
    action_input_coder_agent: Optional[CoderAgentInput] = None
    action_input_conclude_task: Optional[ConcludeTaskInput] = None


class APIPlannerOutputLiteNoHITL(BaseModel):
    """
    Lite output schema for APIPlanner without human-in-the-loop support.
    """

    action: ActionNameNoHITL = Field(description="The chosen action to be executed next.")
    action_input_shortlisting_agent: Optional[ApiShortlistingAgentInput] = None
    action_input_coder_agent: Optional[CoderAgentInput] = None
    action_input_conclude_task: Optional[ConcludeTaskInput] = None
