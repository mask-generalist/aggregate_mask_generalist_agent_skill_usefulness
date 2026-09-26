import json
from typing import Any, Optional

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate

from cuga.backend.cuga_graph.nodes.shared.base_agent import BaseAgent
from cuga.backend.cuga_graph.nodes.answer.final_answer_agent.prompts.load_prompt import (
    FinalAnswerOutput,
)

from cuga.backend.llm.models import LLMManager
from cuga.config import settings

llm_manager = LLMManager()


class GoogleSearchAgent(BaseAgent):
    def __init__(self, prompt_template: Optional[ChatPromptTemplate], llm: BaseChatModel, tools: Any = None):
        super().__init__()
        self.name = "GoogleSearchAgent"
        system_prompt = """
        You are a highly capable assistant who interprets ambiguous or implicit location references and returns **one concise answer** with the following guidelines:
        
        1. **Determine the user’s intent** and decide whether they need:
           - A **specific site or facility** (e.g., “the tallest tower in Dubai” → “Burj Khalifa, Dubai, United Arab Emirates”), or
           - A **city or region** (e.g., “the biggest city in Scotland” → “Glasgow, Scotland”).
        
        2. **Format your final answer** as a single line without extra commentary, in one of these ways:
           - **NameOfPlace, City, State (or Region)** if you know the city/region accurately.
           - **City, State (or Region)** if only a city/region is intended or known.
           - **NameOfPlace** if that is all you can confidently determine.
        
        3. **Do not add placeholders** like “City, State” if you genuinely do not know the city or state. Provide only what you are certain about and omit the rest.
        
        4. **No explanations**—just output the result. Avoid phrases like “I believe” or “this might be.”
        
        5. Expand common abbreviations, such as:
           - “NYC” → “New York City, New York”
           - “LA” → “Los Angeles, California”
           And so on for widely recognized short forms.
        
        6. **Omit guesses**. Only include city or state if you are certain. If you’re unsure, provide just the place name.
        
        7. If there is no real location, or the location is not make sense in this area for example Google site in Alaska, or if the requested info doesn’t exist (e.g., phone number for a fictional place), return “N/A.”
        
        8. **If there is a chain or brand with multiple branches** (e.g., “a certain coffee shop” with many locations) and you cannot pinpoint the exact store address, provide **NameOfChain, MostLikelyCity, State** if the context suggests a city. Otherwise, just give the brand name.
        
        **Overall**: Produce **one single-line location** that aligns with the user’s intent, including city/state or region only when you know it. 
        """

        prompt = ChatPromptTemplate.from_messages([("system", system_prompt), ("human", "{question}")])
        self.graph = prompt | llm

    @staticmethod
    def output_parser(result: FinalAnswerOutput, name) -> Any:
        result = AIMessage(content=json.dumps(result.model_dump()), name=name)
        return result

    async def run(self, question: str) -> AIMessage:
        return await self.graph.ainvoke(question)

    @staticmethod
    def create():
        dyna_model = settings.agent.final_answer.model
        return GoogleSearchAgent(
            prompt_template=None,
            llm=llm_manager.get_model(dyna_model),
        )
