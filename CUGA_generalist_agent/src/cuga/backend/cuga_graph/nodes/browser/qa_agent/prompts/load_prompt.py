from typing import List

from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field


class QaAgentOutput(BaseModel):
    thoughts: List[str] = Field(..., description="List of thoughts")
    name: str = Field(..., description="Give the answer a meaningful name")
    answer: str = Field(..., description="Final answer")


parser = PydanticOutputParser(pydantic_object=QaAgentOutput)
