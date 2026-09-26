from pydantic import BaseModel
from typing import List
from langchain_core.runnables import Runnable
from langchain_core.output_parsers import PydanticOutputParser

from cuga.backend.cuga_graph.nodes.shared.base_agent import BaseAgent
from cuga.backend.llm.models import LLMManager
from cuga.backend.llm.utils.helpers import load_prompt_simple

llm_manager = LLMManager()


class Attributes(BaseModel):
    thoughts: List[str]
    performs_update: bool
    requires_memory: bool
    requires_loop: bool
    requires_location_search: bool


def classify_task(model_config) -> Runnable:
    # Set up a parser
    parser = PydanticOutputParser(pydantic_object=Attributes)
    llm = llm_manager.get_model(model_config)
    pmt = load_prompt_simple(
        "./prompts/classify_task_system.jinja2",
        "./prompts/classify_task_user.jinja2",
        model_config=model_config,
        format_instructions=BaseAgent.get_format_instructions(parser),
    )
    return BaseAgent.get_chain(pmt, llm, Attributes)
