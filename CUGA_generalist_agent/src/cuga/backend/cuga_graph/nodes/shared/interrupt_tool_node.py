from cuga.backend.activity_tracker.tracker import ActivityTracker
from cuga.backend.cuga_graph.nodes.shared.base_agent import create_partial
from cuga.backend.cuga_graph.nodes.shared.base_node import BaseNode
from cuga.backend.cuga_graph.state.agent_state import AgentState
from langchain_core.runnables import RunnableConfig
from langchain_core.messages import AIMessage
from loguru import logger

tracker = ActivityTracker()


class InterruptToolNode(BaseNode):
    def __init__(self):
        super().__init__()
        self.name = "InterruptToolNode"
        self.node = create_partial(
            InterruptToolNode.node_handler,
            name=self.name,
        )

    @staticmethod
    async def node_handler(state: AgentState, name: str, config: RunnableConfig) -> AgentState:
        logger.warning("Returned to interrupt node")
        if state.tool_call and len(state.messages[-1].tool_calls) == 0:
            msg = AIMessage(content="", name=name)
            msg.tool_calls = [state.tool_call]
            state.sender = name
            state.messages.append(msg)
            state.tool_call = None
        return state
