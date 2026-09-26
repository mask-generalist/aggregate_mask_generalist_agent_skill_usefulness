from pydantic import BaseModel
from typing import List
from langchain_core.runnables import Runnable
from langchain_core.output_parsers import PydanticOutputParser

from cuga.backend.cuga_graph.nodes.shared.base_agent import BaseAgent
from cuga.backend.llm.models import LLMManager
from cuga.backend.llm.utils.helpers import load_prompt_simple

llm_manager = LLMManager()


class Paraphrase(BaseModel):
    thoughts: List[str]
    rephrased_intent: str


def paraphrase_task(model_config) -> Runnable:
    parser = PydanticOutputParser(pydantic_object=Paraphrase)
    llm = llm_manager.get_model(model_config)
    pmt = load_prompt_simple(
        "./prompts/paraphrase_system.jinja2",
        "./prompts/paraphrase_user.jinja2",
        model_config=model_config,
        format_instructions=BaseAgent.get_format_instructions(parser),
    )
    return BaseAgent.get_chain(pmt, llm, Paraphrase)
