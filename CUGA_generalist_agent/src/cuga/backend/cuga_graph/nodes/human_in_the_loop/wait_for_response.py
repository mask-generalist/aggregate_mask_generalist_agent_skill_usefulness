from typing import Literal, Optional

from langchain_core.messages import HumanMessage
from langgraph.types import Command, interrupt
from loguru import logger

from cuga.backend.cuga_graph.nodes.shared.base_agent import create_partial
from cuga.backend.cuga_graph.nodes.shared.base_node import BaseNode
from cuga.backend.cuga_graph.nodes.human_in_the_loop.followup_model import ActionResponse, FollowUpAction
from cuga.backend.cuga_graph.state.agent_state import AgentState
from cuga.backend.activity_tracker.tracker import ActivityTracker, Step

tracker = ActivityTracker()


class WaitForResponse(BaseNode):
    def __init__(self):
        super().__init__()
        self.name = "WaitForResponse"
        self.node = create_partial(
            WaitForResponse.node_handler,
        )

    @staticmethod
    def _build_hitl_message_content(response: ActionResponse, action: Optional[FollowUpAction]) -> str:
        """Build a human-readable content string for the HITL response message."""
        action_name = action.action_name if action else "Unknown Action"

        # Primary label based on response type
        if response.text_response:
            label = response.text_response
        elif response.confirmed is True:
            label = f"[HITL: Approved] {action_name}"
        elif response.confirmed is False:
            label = f"[HITL: Denied] {action_name}"
        elif response.selected_values:
            label = f"[HITL: Selected] {', '.join(response.selected_values)}"
        else:
            label = f"[HITL Response] {action_name}"

        return label

    @staticmethod
    async def node_handler(
        state: AgentState,
    ) -> Command[Literal["__end__", "FinalAnswerAgent", "ChatAgent", "APIPlannerAgent", "CugaLite"]]:
        response = interrupt(state.hitl_action.model_dump())
        state.hitl_response = ActionResponse(**response)
        tracker.collect_step(Step(name="WaitForResponse", data=state.hitl_response.model_dump_json()))
        prev_sender = state.sender
        state.sender = "WaitForResponse"
        state.hitl_response.additional_data = state.hitl_action.additional_data

        # Record HITL response in chat_messages for trace persistence
        hitl_content = WaitForResponse._build_hitl_message_content(state.hitl_response, state.hitl_action)
        hitl_metadata = {
            "hitl": True,
            "action_id": state.hitl_response.action_id,
            "response_type": state.hitl_response.response_type,
            "timestamp": state.hitl_response.timestamp,
        }
        if state.hitl_response.confirmed is not None:
            hitl_metadata["confirmed"] = state.hitl_response.confirmed
        if state.hitl_response.text_response:
            hitl_metadata["text_response"] = state.hitl_response.text_response

        hitl_human_msg = HumanMessage(
            content=hitl_content,
            additional_kwargs={"metadata": hitl_metadata},
        )
        if state.chat_messages is None:
            state.chat_messages = []
        state.chat_messages.append(hitl_human_msg)
        logger.info(f"Recorded HITL response in chat_messages: action_id={state.hitl_response.action_id}")

        state.hitl_action = None
        return Command(update=state.model_dump(), goto=prev_sender)
