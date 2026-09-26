import json

from langchain_core.messages import AIMessage

from cuga.backend.activity_tracker.tracker import ActivityTracker, Step
from cuga.backend.cuga_graph.nodes.shared.base_agent import create_partial
from cuga.backend.cuga_graph.nodes.shared.base_node import BaseNode
from cuga.backend.cuga_graph.state.agent_state import AgentState
from cuga.backend.cuga_graph.nodes.browser.qa_agent.prompts.load_prompt import QaAgentOutput
from cuga.backend.cuga_graph.nodes.browser.qa_agent.qa_agent import QaAgent

tracker = ActivityTracker()


class QaNode(BaseNode):
    def __init__(self, qa_agent: QaAgent):
        super().__init__()
        self.qa_agent = qa_agent
        self.node = create_partial(QaNode.node_handler, agent=self.qa_agent, name=self.qa_agent.name)

    @staticmethod
    async def node_handler(state: AgentState, agent: QaAgent, name: str):
        result: AIMessage = await agent.run(state)
        qa_output = QaAgentOutput(**json.loads(result.content))
        tracker.collect_step(step=Step(name=name, data=qa_output.model_dump_json()))
        state.stm_steps_history.append("Response of (QaAgent): " + qa_output.name + ": " + qa_output.answer)
        state.messages.append(result)
        return state
