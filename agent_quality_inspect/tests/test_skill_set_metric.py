"""Unit tests for the shared :obj:`SkillSetMetric` base behavior.

Covers the base's helpers (:meth:`get_skill_invocations_from_agent_trace`,
:meth:`count_intersection`), the abstract :meth:`_get_denominator`, and the input
guards on :meth:`evaluate` that apply to both :obj:`SkillPrecisionMetric` and
:obj:`SkillRecallMetric`.
"""

import pytest

from agent_inspect.exception import InvalidInputValueError
from agent_inspect.metrics.constants import CASE_SENSITIVE
from agent_inspect.metrics.scorer import SkillPrecisionMetric, SkillRecallMetric
from agent_inspect.metrics.scorer.skill_set_metric import SkillSetMetric
from agent_inspect.metrics.validator.constants import (
    SKILL_NAME_MATCHED_EXPLANATION,
    SKILL_NOT_FOUND_EXPLANATION,
)
from agent_inspect.metrics.validator.skill_call_completion import SkillCallCompletionValidator
from agent_inspect.models.metrics.agent_data_sample import EvaluationSample, SubGoal
from agent_inspect.models.metrics.agent_trace import AgentDialogueTrace, Step, TurnTrace
from agent_inspect.models.metrics.skill_data_sample import SkillCall, SkillInputParameter


def _skill_call(skill_id, params=None):
    skill_parameters = (
        [SkillInputParameter(name=n, value=v) for n, v in params.items()] if params else None
    )
    return SkillCall(skill_id=skill_id, skill_parameters=skill_parameters)


def _step(skill_id, params=None):
    """A single invoked skill: a trace step carrying a ``skill_call``."""
    return Step(id=skill_id, parent_ids=[], skill_calls=[_skill_call(skill_id, params)])


def _trace(*steps):
    """A one-turn trace built from the given steps (pass none for an empty turn)."""
    return AgentDialogueTrace(turns=[TurnTrace(id="t1", agent_input="hi", steps=list(steps))])


def _sample(*expected_skill_calls):
    return EvaluationSample(
        sub_goals=[SubGoal(details="done")],
        expected_skill_calls=list(expected_skill_calls),
    )


def test_get_skill_invocations_collects_every_step():
    trace = _trace(_step("a"), _step("b"))
    invocations = SkillPrecisionMetric().get_skill_invocations_from_agent_trace(trace)
    assert [call.skill_id for call in invocations] == ["a", "b"]


def test_get_skill_invocations_empty_when_no_steps():
    trace = _trace()
    assert SkillPrecisionMetric().get_skill_invocations_from_agent_trace(trace) == []


def test_get_skill_invocations_dedupes_matching_calls():
    # Same skill_id + same params -> one entry; differing params kept separately.
    trace = _trace(
        _step("a", {"x": 1}),
        _step("a", {"x": 1}),
        _step("a", {"x": 2}),
        _step("b"),
        _step("b"),
    )
    invocations = SkillPrecisionMetric().get_skill_invocations_from_agent_trace(trace)
    assert [call.skill_id for call in invocations] == ["a", "a", "b"]
    assert invocations[0].skill_parameters[0].value == 1
    assert invocations[1].skill_parameters[0].value == 2


def test_count_intersection_counts_satisfied_ground_truth():
    validator = SkillCallCompletionValidator()
    invocations = [_skill_call("a")]
    # Expected "a" is satisfied by the invocation; "z" is not -> count 1, with an
    # explanation line for each ground-truth call it checked.
    expected = [_skill_call("a"), _skill_call("z")]
    count, explanations = SkillSetMetric.count_intersection(expected, invocations, validator)
    assert count == 1
    assert SKILL_NAME_MATCHED_EXPLANATION.format(skill_id="a") in explanations
    assert SKILL_NOT_FOUND_EXPLANATION.format(skill_id="z") in explanations


def test_count_intersection_zero_when_no_invocations():
    validator = SkillCallCompletionValidator()
    count, explanations = SkillSetMetric.count_intersection([_skill_call("a")], [], validator)
    assert count == 0
    assert explanations == []


###############################
# _is_same_skill_call
###############################


def _same(a, b, validator=None):
    """Whether two skill calls are equivalent under the (default) validator."""
    return SkillSetMetric._is_same_skill_call(a, b, validator or SkillCallCompletionValidator())


def test_is_same_skill_call_true_for_identical_id_no_params():
    assert _same(_skill_call("a"), _skill_call("a"))


def test_is_same_skill_call_false_for_different_id():
    assert not _same(_skill_call("a"), _skill_call("b"))


def test_is_same_skill_call_true_for_identical_id_and_params():
    assert _same(_skill_call("a", {"x": 1}), _skill_call("a", {"x": 1}))


def test_is_same_skill_call_false_when_param_value_differs():
    assert not _same(_skill_call("a", {"x": 1}), _skill_call("a", {"x": 2}))


def test_is_same_skill_call_false_when_param_name_differs():
    assert not _same(_skill_call("a", {"x": 1}), _skill_call("a", {"y": 1}))


def test_is_same_skill_call_false_when_param_count_differs():
    assert not _same(_skill_call("a", {"x": 1}), _skill_call("a", {"x": 1, "y": 2}))


def test_is_same_skill_call_asymmetric_param_presence_a_bare():
    # One call carries params, the other does not. A single-direction validator
    # check would call these "same" (a bare ground truth matches on id alone);
    # the two-direction check must reject them.
    assert not _same(_skill_call("a"), _skill_call("a", {"x": 1}))


def test_is_same_skill_call_asymmetric_param_presence_b_bare():
    # Same as above with the arguments swapped: the result must not depend on
    # which side carries the params.
    assert not _same(_skill_call("a", {"x": 1}), _skill_call("a"))


def test_is_same_skill_call_is_symmetric_for_mismatched_params():
    # Swapping the two calls yields the same verdict for mismatched param values.
    a = _skill_call("a", {"x": 1})
    b = _skill_call("a", {"x": 2})
    assert _same(a, b) == _same(b, a)


def test_is_same_skill_call_id_comparison_is_case_sensitive():
    # Skill id is always matched case-sensitively, independent of config, so ids
    # differing only in case are never the same call.
    assert not _same(_skill_call("A"), _skill_call("a"))


def test_is_same_skill_call_param_value_case_insensitive_by_default():
    # Default config (case_sensitive=False): param values differing only in case
    # are still the same call.
    assert _same(_skill_call("a", {"x": "Cats"}), _skill_call("a", {"x": "cats"}))


def test_is_same_skill_call_param_value_respects_case_sensitive_config():
    # With case_sensitive=True the same param values are treated as different.
    validator = SkillCallCompletionValidator(config={CASE_SENSITIVE: True})
    assert not _same(_skill_call("a", {"x": "Cats"}), _skill_call("a", {"x": "cats"}), validator)


def test_base_get_denominator_is_abstract():
    # SkillSetMetric leaves the denominator to its subclasses.
    with pytest.raises(NotImplementedError):
        SkillSetMetric()._get_denominator([_skill_call("a")], _sample(_skill_call("a")))


@pytest.mark.parametrize("metric", [SkillPrecisionMetric, SkillRecallMetric])
def test_raises_when_trace_has_no_turns(metric):
    trace = AgentDialogueTrace(turns=[])
    sample = _sample(_skill_call("a"))
    with pytest.raises(InvalidInputValueError, match="Agent trace has no turns"):
        metric().evaluate(trace, sample)


def test_precision_scores_zero_when_no_expected_skill_calls():
    trace = _trace(_step("a"))
    sample = _sample()
    assert SkillPrecisionMetric().evaluate(trace, sample).score == 0.0


def test_recall_raises_when_no_expected_skill_calls():
    trace = _trace(_step("a"))
    sample = _sample()
    with pytest.raises(InvalidInputValueError, match="No expected skill calls"):
        SkillRecallMetric().evaluate(trace, sample)
