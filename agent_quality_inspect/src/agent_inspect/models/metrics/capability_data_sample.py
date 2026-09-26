from dataclasses import dataclass
from typing import Optional, List

from agent_inspect.models.metrics.skill_data_sample import SkillCall


@dataclass
class CapabilityOutput:

    check: str


@dataclass
class ExpectedCapability:

    description: str
    capability_name: Optional[str] = None
    expected_output: Optional[CapabilityOutput] = None
    expected_skills: Optional[List[SkillCall]] = None
