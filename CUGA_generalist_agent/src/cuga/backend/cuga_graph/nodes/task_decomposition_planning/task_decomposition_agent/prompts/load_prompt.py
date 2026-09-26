from typing import List, Literal

from langchain_core.output_parsers import PydanticOutputParser
from pydantic import BaseModel, Field


class DecomposedTask(BaseModel):
    task: str = Field(..., description="task")
    app: str = Field(..., description="app name")
    type: Literal['api', 'web'] = Field(..., description="app name")


class TaskDecompositionPlan(BaseModel):
    thoughts: str = Field(..., description="your thoughts")
    task_decomposition: List[DecomposedTask] = Field(..., description="the subtask decomposition")

    def format_as_list(self):
        return [
            "{} (type = '{}', app='{}')".format(p.task, p.type, p.app[:30]) for p in self.task_decomposition
        ]


parser = PydanticOutputParser(pydantic_object=TaskDecompositionPlan)


class TaskDecompositionMultiOutput(BaseModel):
    thoughts: List[str] = Field(..., description="your thoughts")
    app_1: Literal['shopping_admin', 'shopping', 'wikipedia', 'reddit', 'gitlab', 'map'] = Field(
        ..., description="site 1 name"
    )
    task_1_description: str
    app_2: Literal['shopping_admin', 'shopping', 'wikipedia', 'reddit', 'gitlab', 'map'] = Field(
        ..., description="site 2 name"
    )
    task_2_description: str
