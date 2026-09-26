from abc import abstractmethod
from typing import Optional, Dict, Any, List

from agent_inspect.core.utils import get_config_or_default
from agent_inspect.metrics.constants import (
    TRIM,
    CASE_SENSITIVE,
    STRING_TRIM_DEFAULT,
    STRING_CASE_SENSITIVE_DEFAULT,
)
from agent_inspect.metrics.validator.validator import Validator
from agent_inspect.models.metrics import ValidationResult


class ExactMatchValidatorAny(Validator):

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)

    @abstractmethod
    def validate(self, candidate: List[Any], ground_truth: Any) -> ValidationResult:
        ...

    @staticmethod
    def exact_match_str(
        candidate: str, ground_truth: str, config: Optional[Dict[str, Any]] = None
    ) -> bool:
        candidate = ExactMatchValidatorAny.format_str(candidate, config)
        ground_truth = ExactMatchValidatorAny.format_str(ground_truth, config)
        return candidate == ground_truth

    @staticmethod
    def exact_match(
        candidate: Any, ground_truth: Any, config: Optional[Dict[str, Any]] = None
    ) -> bool:
        if isinstance(candidate, str) and isinstance(ground_truth, str):
            return ExactMatchValidatorAny.exact_match_str(candidate, ground_truth, config)
        else:
                                                              
            return isinstance(candidate, type(ground_truth)) and candidate == ground_truth

    @staticmethod
    def format_str(str_value: str, config: Optional[Dict[str, Any]] = None) -> str:
        trim = get_config_or_default(config, TRIM, STRING_TRIM_DEFAULT)
        case_sensitive = get_config_or_default(
            config, CASE_SENSITIVE, STRING_CASE_SENSITIVE_DEFAULT
        )
        if trim:
            str_value = str_value.strip()
        if not case_sensitive:
            str_value = str_value.lower()
        return str_value
