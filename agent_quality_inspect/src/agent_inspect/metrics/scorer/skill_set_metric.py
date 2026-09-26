from typing import List, Tuple

from agent_inspect.exception import InvalidInputValueError, ErrorCode
from agent_inspect.metrics.scorer.metric import Metric
from agent_inspect.metrics.validator.skill_call_completion import (
    SkillCallCompletionValidator,
)
from agent_inspect.models.metrics.agent_data_sample import EvaluationSample
from agent_inspect.models.metrics.agent_trace import AgentDialogueTrace
from agent_inspect.models.metrics.metric_score import NumericalScore
from agent_inspect.models.metrics.skill_data_sample import SkillCall


class SkillSetMetric(Metric):

    def get_skill_invocations_from_agent_trace(
        self, agent_trace: AgentDialogueTrace
    ) -> List[SkillCall]:
        validator = SkillCallCompletionValidator(config=self.config)
        turns = agent_trace.turns or []
        steps = []
        for turn in turns:
            steps += turn.steps or []

        skill_invocations: List[SkillCall] = []
        for step in steps:
            for skill_call in step.skill_calls or []:
                if not any(
                    self._is_same_skill_call(kept, skill_call, validator)
                    for kept in skill_invocations
                ):
                    skill_invocations.append(skill_call)
        return skill_invocations

    @staticmethod
    def _is_same_skill_call(
        a: SkillCall,
        b: SkillCall,
        validator: SkillCallCompletionValidator,
    ) -> bool:
        return validator.validate([a], b).is_completed and validator.validate([b], a).is_completed

    @staticmethod
    def count_intersection(
        expected_skill_calls: List[SkillCall],
        skill_invocations: List[SkillCall],
        validator: SkillCallCompletionValidator,
    ) -> Tuple[int, List[str]]:
        if not skill_invocations:
            return 0, []

        count = 0
        explanations = []
        for expected in expected_skill_calls:
            validation = validator.validate(skill_invocations, expected)
            explanations += validation.explanations
            if validation.is_completed:
                count += 1

        return count, explanations

    def evaluate(
        self,
        agent_trace: AgentDialogueTrace,
        evaluation_data_sample: EvaluationSample,
    ) -> NumericalScore:
        if not agent_trace.turns:
            raise InvalidInputValueError(
                internal_code=ErrorCode.MISSING_VALUE.value,
                message="Agent trace has no turns",
            )
        validator = SkillCallCompletionValidator(config=self.config)
        skill_invocations = self.get_skill_invocations_from_agent_trace(agent_trace)

        numerator, explanations = self.count_intersection(
            evaluation_data_sample.expected_skill_calls or [], skill_invocations, validator
        )
        denominator = self._get_denominator(skill_invocations, evaluation_data_sample)
        return NumericalScore(score=round(numerator / denominator, 4), explanations=explanations)

    def _get_denominator(
        self,
        skill_invocations: List[SkillCall],
        evaluation_data_sample: EvaluationSample,
    ) -> int:
        raise NotImplementedError
