import json
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from langchain_openai import AzureChatOpenAI

from cuga.backend.cuga_graph.nodes.shared.base_agent import BaseAgent
from cuga.backend.cuga_graph.state.agent_state import AgentState
from cuga.backend.cuga_graph.nodes.browser.qa_agent.prompts.load_prompt import QaAgentOutput, parser
from cuga.backend.llm.models import LLMManager
from cuga.backend.llm.utils.helpers import load_prompt_simple
from cuga.config import settings

llm_manager = LLMManager()


class QaAgent(BaseAgent):
    def __init__(
        self,
        prompt_template: ChatPromptTemplate,
        llm: AzureChatOpenAI,
        tools: Any = None,
    ):
        super().__init__()
        self.name = "QaAgent"
        parser = RunnableLambda(QaAgent.output_parser)
        self.chain = self.chain = BaseAgent.get_chain(prompt_template, llm, QaAgentOutput) | (
            parser.bind(name=self.name)
        )

    @staticmethod
    def output_parser(result: QaAgentOutput, name) -> Any:
        result = AIMessage(content=json.dumps(result.model_dump()), name=name)
        return result

    async def run(self, input_variables: AgentState) -> AIMessage:
        return await self.chain.ainvoke(input_variables.model_dump())

    @staticmethod
    def create():
        model = llm_manager.get_model(settings.agent.qa.model)
        return QaAgent(
            prompt_template=load_prompt_simple(
                "./prompts/system.jinja2",
                "./prompts/user_msg.jinja2",
                model_config=settings.agent.qa.model,
                format_instructions=BaseAgent.get_format_instructions(parser=parser),
            ),
            llm=model,
        )
