from typing import Optional

from pydantic import BaseModel

from cuga.backend.cuga_graph.nodes.task_decomposition_planning.task_analyzer_agent.tasks.classify_task import (
    Attributes,
)
from cuga.backend.cuga_graph.nodes.task_decomposition_planning.task_analyzer_agent.tasks.navigation_paths_task import (
    Approaches,
)


class AnalyzeTaskOutput(BaseModel):
    attrs: Optional[Attributes] = None
    paraphrased_intent: Optional[str] = None
    navigation_paths: Optional[Approaches] = None
    resolved_intent: Optional[str] = None
