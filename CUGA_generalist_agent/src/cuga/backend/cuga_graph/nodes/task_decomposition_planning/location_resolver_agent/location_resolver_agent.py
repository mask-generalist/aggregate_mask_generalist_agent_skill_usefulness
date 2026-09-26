import asyncio
import json
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate

from cuga.backend.cuga_graph.nodes.shared.base_agent import BaseAgent
from cuga.backend.cuga_graph.nodes.answer.final_answer_agent.prompts.load_prompt import (
    FinalAnswerOutput,
    load_prompt,
)

from langchain_core.tools import tool

from cuga.backend.cuga_graph.nodes.task_decomposition_planning.location_resolver_agent.google_search_agent import (
    GoogleSearchAgent,
)
from cuga.backend.llm.models import LLMManager
from cuga.config import settings
from langgraph.prebuilt import create_react_agent
from langchain_core.runnables import RunnableConfig
from loguru import logger

llm_manager = LLMManager()


@tool
async def search_google(implicit_location: str, config: RunnableConfig):
    """Use this to search location in google, can only return location of implicit location"""
    agent = config.get("configurable", {}).get("google_search_agent")
    res = await agent.run(implicit_location)
    return res


# @tool
# def conclude_intent(resolved_intent: str):
#     """Use this to get conclude intent after all implicit locations has been replaced"""
#     interrupt(
#         {"question": "is it ok to continue?"},
#     )
#     return "Done!"


class LocationResolverAgent(BaseAgent):
    def __init__(self, prompt_template: ChatPromptTemplate, llm: BaseChatModel, tools: Any = None):
        super().__init__()
        self.name = "LocationResolverAgent"
        system_prompt = """
You are an expert in resolving implicit locations to explicit locations in a given intent. You can use google search tool to search for explicit location, iteratively until you have resolved all locations. finally return the final resolved intent.
## Input:
1. Intent: An intent describing a task for maps application

## Instructions:
* Do not use your own knowledge to answer.

## Definitions:
1. Implicit locations: If the intent includes shortcuts or ambiguous locations, or something like GCG etc..
2. Explicit locations:  Location name in natural language.

##Available tools:
1. search_google(implicit_location: str): Search google for any location name only. can only return location name.

## Final output instructions:
- Return Resolved intent with the implicit locations replaced by explicit locations.
- The Resolved intent must not include the initial implicit locations.

        """

        tools = [search_google]
        prompt = ChatPromptTemplate.from_messages([("system", system_prompt), ("placeholder", "{messages}")])
        self.graph = create_react_agent(llm, tools=tools, prompt=prompt)

    @staticmethod
    def output_parser(result: FinalAnswerOutput, name) -> Any:
        result = AIMessage(content=json.dumps(result.model_dump()), name=name)
        return result

    async def run(self, intent) -> AIMessage:
        inputs = {"messages": [("user", intent)]}
        stream = self.graph.astream(
            inputs,
            stream_mode="values",
            config={"configurable": {"google_search_agent": GoogleSearchAgent.create()}},
        )
        async for s in stream:
            message = s["messages"][-1]
            if isinstance(message, tuple):
                logger.info(f"\n{message}")
            else:
                logger.info(f"\n{message.pretty_repr()}")
        res_output = intent
        if isinstance(message, AIMessage):
            conclude_output = message.content
            logger.info(f"\nResolved intent:\n {conclude_output}")
            res_output = str(conclude_output)
        return AIMessage(content=res_output)

    @staticmethod
    def create():
        dyna_model = settings.agent.final_answer.model
        return LocationResolverAgent(
            prompt_template=load_prompt(),
            llm=llm_manager.get_model(dyna_model),
        )


# ------------------ UNIT TEST CODE ------------------
async def run_internal_mapping_tests():
    """
    This function tests the internal location mapping available in GoogleSearchAgent.
    Each test case checks if the expected explicit location is part of the agent's answer.
    """
    test_cases = {
        "the home stadium of Philadelphia 76ers": "Wells Fargo Center",
        "home of the 1980 Super Bowl champions": "Pittsburgh",
        "home of the 1991 Super Bowl champions": "New York",
        "the page of the place where Mr. Rogers was filmed on the map": "Oakland, Pittsburgh",
        "SCS CMU in Pittsburgh": "School of Computer Science, Carnegie Mellon University",
        "the location where the Declaration of Independence and Constitution were signed": "Independence Hall",
        "the nearest cold stone ice cream": "Cold Stone Creamery, Pittsburgh",
        "closest national park to boston": "Acadia National Park",
        # "closest national park to boston": "Minute Man National Historical Park",
        "the childhood home of Barack Obama": "Honolulu, Hawaii",
        "the city of MIT": "Cambridge, Massachusetts",
        "the birthplace of John F. Kennedy": "Brookline, Massachusetts",
        "the city of Princeton University": "Princeton, New Jersey",
        "the location of NASA's Johnson Space Center": "Houston, Texas",
        "the home stadium of the University of Michigan football team": "Michigan Stadium",
        "the main campus of UC Berkeley": "University of California, Berkeley",
        "the city of Harvard Law School": "Cambridge, Massachusetts",
        "the city of Duquesne University": "Pittsburgh",
        "the city of Chatham University": "Pittsburgh",
        "the phone number of Hogwarts Castle": "N/A",
        "the city of Frodo Baggins": "N/A",
        "the coordinates of Jurassic Park in DD format": "N/A",
    }

    agent = GoogleSearchAgent.create()

    success_count = 0
    total_count = len(test_cases)
    failed_cases = []

    logger.info("=== Starting Internal Mapping Unit Tests ===")

    # Run each test case.
    for query, expected in test_cases.items():
        logger.info(f"Testing query: '{query}' (expecting output to contain: '{expected}')")
        try:
            result: AIMessage = await agent.run(query)
            result_content = result.content.strip()
        except Exception as e:
            logger.exception(f"Exception occurred for query '{query}': {e}")
            failed_cases.append((query, expected, f"Exception: {e}"))
            continue

        if expected.lower() in result_content.lower():
            success_count += 1
            logger.info(f"Test PASSED for query: '{query}' -> Got: '{result_content}'")
        else:
            failed_cases.append((query, expected, result_content))
            logger.error(
                f"Test FAILED for query: '{query}'. Expected to contain: '{expected}', Got: '{result_content}'"
            )

    summary = f"\n=== Summary: {success_count}/{total_count} tests passed. ==="
    logger.info(summary)

    if failed_cases:
        failed_details = "Failed test cases:\n"
        for query, expected, output in failed_cases:
            failed_details += f"Query: {query}\nExpected: {expected}\nOutput: {output}\n\n"
        logger.error(failed_details)
        print(failed_details)


async def main():
    await run_internal_mapping_tests()


if __name__ == '__main__':
    asyncio.run(main())
