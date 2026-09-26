import asyncio
import backoff
import litellm  # type: ignore (Removed litellm dependency temporarily due to security concerns)
from litellm import acompletion, get_supported_openai_params, supports_response_schema  # type: ignore (Removed litellm dependency temporarily due to security concerns)
from typing import Dict, Any, Optional
import logging

from openai import APIStatusError

from agent_inspect.metrics.constants import (
    STATUS_200,
    STATUS_429,
    MAX_RETRY_ATTEMPTS_EXCEEDED,
    STATUS_500,
    STATUS_404,
)
from agent_inspect.clients.llm_client import LLMClient
from agent_inspect.exception import InvalidInputValueError
from agent_inspect.models.llm_response import LLMResponse
from agent_inspect.models.llm_payload import LLMPayload
from agent_inspect.exception.error_codes import ErrorCode, ClientComponent

logger = logging.getLogger(__name__)


def backoff_handler(details):
    message = (
        f"Backing off {details['target'].__name__} "
        f"(args={details['args']}, kwargs={details['kwargs']}) "
        f"for {details['wait']:.1f}s "
        f"(tries={details['tries']}, elapsed={details['elapsed']:.1f}s, "
        f"exception: {details['exception']})"
    )

    logger.warning(message)


def give_up_handler(details):
    message = (
        f"Max retries reached for {details['target'].__name__} "
        f"(args={details['args']}, kwargs={details['kwargs']}, "
        f"elapsed={details['elapsed']:.1f}s, exception: {details['exception']})"
    )
    logger.error(message)


class LiteLLMClient(LLMClient):

    def __init__(
        self,
        model: str,
        max_tokens: int,
        temperature: float = 0,
        extra_params: Optional[Dict[str, Any]] = None,
    ):
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.extra_params = extra_params or {}

        litellm.set_verbose = False

    @backoff.on_exception(
        backoff.expo,
        (
            litellm.exceptions.RateLimitError,
            litellm.exceptions.ServiceUnavailableError,
            Exception,
        ),
        max_tries=10,
        max_time=300,
        jitter=None,
        on_backoff=backoff_handler,
        on_giveup=give_up_handler,
        giveup=lambda e: isinstance(
            e,
            (
                litellm.exceptions.AuthenticationError,
                litellm.exceptions.BadRequestError,
                litellm.exceptions.NotFoundError,
                litellm.exceptions.PermissionDeniedError,
            ),
        ),
    )
    async def make_llm_request_with_retry(self, prompt: str):
        messages = [{"role": "user", "content": prompt}]
        response_from_llm = await acompletion(
            model=self.model,
            messages=messages,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            **self.extra_params,
        )
        return response_from_llm

    async def make_llm_request(self, prompt: str) -> LLMResponse:

        try:
            response_from_llm = await self.make_llm_request_with_retry(prompt)
            response_to_return = LLMResponse(
                status=STATUS_200,
                completion=response_from_llm.choices[0].message.content,
            )
        except litellm.exceptions.RateLimitError:
            response_to_return = LLMResponse(
                status=STATUS_429,
                completion="",
                error_message=MAX_RETRY_ATTEMPTS_EXCEEDED,
            )
        except APIStatusError as e:
            # Non-retryable errors (4xx) or final failure after all retries
            response_to_return = LLMResponse(
                status=e.status_code,
                completion="",
                error_message=f"Azure OpenAI API Error: {e.message}",
            )
        except Exception as e:
            response_to_return = LLMResponse(
                status=int(getattr(e, "status_code", STATUS_500)),
                completion="",
                error_message=f"Unexpected error: {str(e)}",
            )
        return response_to_return

    async def make_llm_requests(self, prompts: list[str]) -> list[LLMResponse]:
        responses = await asyncio.gather(*(self.make_llm_request(prompt) for prompt in prompts))
        return list(responses)

    def convert_payload_to_raw_request(self, payload: LLMPayload) -> Dict[str, Any]:
        raw_request: Dict[str, Any] = {}
        messages = []
        if payload.system_prompt:
            messages.append({"role": "system", "content": payload.system_prompt})
        messages.append({"role": "user", "content": payload.user_prompt})
        raw_request["model"] = payload.model if payload.model else self.model
        raw_request["messages"] = messages
        raw_request["temperature"] = (
            payload.temperature if payload.temperature else self.temperature
        )
        raw_request["max_tokens"] = payload.max_tokens if payload.max_tokens else self.max_tokens

        params = get_supported_openai_params(model=raw_request["model"])

        if not payload.structured_output:
            return raw_request

        if "response_format" not in params:
            raise InvalidInputValueError(
                internal_code=ErrorCode.UNSUPPORTED_ATTRIBUTION_TYPE.value,
                message="Model does not support response_format parameter.",
                component_code=ClientComponent.CLIENT_ERROR_CODE.value,
            )

        if not supports_response_schema(model=raw_request["model"]):
            raise InvalidInputValueError(
                internal_code=ErrorCode.UNSUPPORTED_ATTRIBUTION_TYPE.value,
                message="Model does not support response schema.",
                component_code=ClientComponent.CLIENT_ERROR_CODE.value,
            )

        raw_request["response_format"] = payload.structured_output
        return raw_request

    @backoff.on_exception(
        backoff.expo,
        (
            litellm.exceptions.RateLimitError,
            litellm.exceptions.ServiceUnavailableError,
            Exception,
        ),
        max_tries=10,
        max_time=300,
        jitter=None,
        on_backoff=backoff_handler,
        on_giveup=give_up_handler,
        giveup=lambda e: isinstance(
            e,
            (
                litellm.exceptions.AuthenticationError,
                litellm.exceptions.BadRequestError,
                litellm.exceptions.NotFoundError,
                litellm.exceptions.PermissionDeniedError,
            ),
        ),
    )
    async def make_request_with_payload_using_retry(self, payload: LLMPayload):
        raw_request = self.convert_payload_to_raw_request(payload)

        response = await acompletion(**raw_request, **self.extra_params)
        return response

    async def make_request_with_payload(self, payload: LLMPayload) -> LLMResponse:
        try:
            response_from_llm = await self.make_request_with_payload_using_retry(payload)
            response_to_return = LLMResponse(
                status=STATUS_200,
                completion=response_from_llm.choices[0].message.content,
            )
        except InvalidInputValueError as e:
            response_to_return = LLMResponse(
                status=STATUS_404, completion="", error_message=e.message
            )
        except litellm.exceptions.RateLimitError:
            response_to_return = LLMResponse(
                status=STATUS_429,
                completion="",
                error_message=MAX_RETRY_ATTEMPTS_EXCEEDED,
            )
        except APIStatusError as e:
            response_to_return = LLMResponse(
                status=e.status_code, completion="", error_message=e.message
            )
        except Exception as e:
            response_to_return = LLMResponse(
                status=int(getattr(e, "status_code", STATUS_500)),
                completion="",
                error_message=f"Unexpected error: {str(e)}",
            )
        return response_to_return
