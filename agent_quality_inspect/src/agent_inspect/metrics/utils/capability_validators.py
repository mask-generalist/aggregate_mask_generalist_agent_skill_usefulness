from agent_inspect.exception.error_codes import ErrorCode
from agent_inspect.exception import InvalidInputValueError
from agent_inspect.models.metrics.capability_data_sample import ExpectedCapability


class ExpectedCapabilityValidator:

    @staticmethod
    def validate_expected_capability(expected_capability: ExpectedCapability) -> None:
        if not expected_capability.description or not expected_capability.description.strip():
            raise InvalidInputValueError(
                internal_code=ErrorCode.MISSING_VALUE.value,
                message="The ExpectedCapability is missing a description for judge to evaluate.",
            )
        if expected_capability.expected_output:
            expected_output = expected_capability.expected_output
            if not expected_output.check or not expected_output.check.strip():
                raise InvalidInputValueError(
                    internal_code=ErrorCode.MISSING_VALUE.value,
                    message="The CapabilityOutput is missing a check for judge to evaluate.",
                )
