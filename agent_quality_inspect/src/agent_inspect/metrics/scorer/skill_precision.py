from typing import List

from agent_inspect.exception import InvalidInputValueError, ErrorCode
from agent_inspect.metrics.scorer.skill_set_metric import SkillSetMetric
from agent_inspect.models.metrics.agent_data_sample import EvaluationSample
from agent_inspect.models.metrics.agent_trace import AgentDialogueTrace
from agent_inspect.models.metrics.metric_score import NumericalScore
from agent_inspect.models.metrics.skill_data_sample import SkillCall


class SkillPrecisionMetric(SkillSetMetric):

    def evaluate(
        self,
        agent_trace: AgentDialogueTrace,
        evaluation_data_sample: EvaluationSample,
    ) -> NumericalScore:
        return super().evaluate(agent_trace, evaluation_data_sample)

    def _get_denominator(
        self,
        skill_invocations: List[SkillCall],
        evaluation_data_sample: EvaluationSample,
    ) -> int:
        if not skill_invocations:
            raise InvalidInputValueError(
                internal_code=ErrorCode.MISSING_VALUE.value,
                message="Agent trace contains no skill invocations",
            )
        return len(skill_invocations)
