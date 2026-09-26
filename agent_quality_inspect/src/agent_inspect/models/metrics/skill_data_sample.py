from dataclasses import dataclass
from typing import Optional, List, Any


@dataclass
class SkillInputParameter:

    name: str
    value: Optional[Any] = None


@dataclass
class SkillCall:

    skill_id: str
    skill_name: Optional[str] = None
    skill_parameters: Optional[List[SkillInputParameter]] = None
