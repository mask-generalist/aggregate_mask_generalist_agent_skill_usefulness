from typing import Literal

from langchain_core.messages import AIMessage
from langgraph.types import Command

from cuga.backend.cuga_graph.nodes.shared.base_agent import create_partial
from cuga.backend.cuga_graph.nodes.shared.base_node import BaseNode
from cuga.backend.cuga_graph.state.agent_state import AgentState
from cuga.backend.activity_tracker.tracker import ActivityTracker, Step

tracker = ActivityTracker()


class SuggestHumanActions(BaseNode):
    def __init__(self):
        super().__init__()
        self.name = "SuggestHumanActions"
        self.node = create_partial(
            SuggestHumanActions.node_handler,
            name=self.name,
        )

    @staticmethod
    async def node_handler(state: AgentState, name: str) -> Command[Literal["WaitForResponse"]]:
        state.messages.append(AIMessage(content=state.hitl_action.model_dump_json()))
        tracker.collect_step(Step(name=name, data=state.hitl_action.model_dump_json()))
        return Command(update=state.model_dump(), goto="WaitForResponse")
