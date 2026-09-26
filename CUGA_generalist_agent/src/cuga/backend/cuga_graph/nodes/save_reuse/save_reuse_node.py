import json
from typing import Literal

from langgraph.types import Command

from cuga.backend.activity_tracker.tracker import ActivityTracker, Step
from cuga.backend.cuga_graph.nodes.shared.base_agent import create_partial
from cuga.backend.cuga_graph.nodes.shared.base_node import BaseNode
from cuga.backend.cuga_graph.state.agent_state import AgentState
from langchain_core.messages import AIMessage

from cuga.backend.cuga_graph.nodes.save_reuse.save_reuse_agent.reuse_agent import ReuseAgent
from cuga.backend.cuga_graph.utils.nodes_names import NodeNames

tracker = ActivityTracker()


class SaveReuseNode(BaseNode):
    def __init__(self, agent: ReuseAgent):
        super().__init__()
        self.name = agent.name
        self.agent = agent
        self.node = create_partial(
            SaveReuseNode.node_handler,
            agent=self.agent,
            name=self.name,
        )

    @staticmethod
    async def node_handler(state: AgentState, agent: ReuseAgent, name: str) -> Command[Literal['__end__']]:
        res: AIMessage = await agent.run(
            state, additional_utterance=f"Or {state.hitl_response.text_response}"
        )
        state.hitl_response = None
        state.final_answer = res.content
        state.sender = name
        state.messages.append(AIMessage(content=json.dumps({"data": res.content})))
        tracker.collect_step(Step(name=name, data=json.dumps({"data": res.content})))
        return Command(update=state.model_dump(), goto=NodeNames.FINAL_ANSWER_AGENT)
