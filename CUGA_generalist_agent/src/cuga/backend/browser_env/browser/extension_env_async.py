# Copyright 2024 ServiceNow
# Modifications Copyright 2025 CUGA
# Licensed under the Apache License, Version 2.0

import logging
import time
from typing import Any, List, Literal

import gymnasium as gym
import numpy as np

# from browsergym.core.action.base import execute_python_code_async  # Assume async version
from browsergym.core.spaces import AnyBox, AnyDict, Unicode
from langchain_core.messages import AIMessage

from cuga.backend.browser_env.browser.gym_obs.http_stream_comm import ChromeExtensionCommunicatorProtocol

from cuga.backend.browser_env.browser.open_ended_async import AbstractBrowserTask
from cuga.backend.browser_env.page_understanding.pu_extractor_chrome_extension import (
    PageUnderstandingExtractorChromeExtension,
    PageUnderstandingExtractorProtocol,
)
from cuga.backend.browser_env.page_understanding.extension_processor import ExtensionProcessor
from cuga.backend.browser_env.tools.providers import BrowserToolImplProvider, ExtensionToolImplProvider

logger = logging.getLogger(__name__)


class ExtensionEnv:
    """The main BrowserGym class, which encapsulates instruction-following Web browsing into a Gymnasium environment."""

    # gym metadata
    metadata = {"render_modes": None}

    def __init__(
        self,
        task_entrypoint: type[AbstractBrowserTask],
        extension_communicator: ChromeExtensionCommunicatorProtocol,
        task_kwargs: dict = {},
        feedback: List[Any] = [],
        user_data_dir: str | None = None,
        tags_to_mark: Literal["all", "standard_html"] = "standard_html",
        messages: List[AIMessage] | None = None,
        timeout: int | None = None,  # will override the task's timeout
        locale: str | None = None,  # will override the task's locale
        timezone_id: str | None = None,  # will override the task's timezone_id,
        tool_implementation_provider: BrowserToolImplProvider | None = None,
        page_understanding_processor: PageUnderstandingExtractorProtocol | None = None,
    ):
        """
        Instantiate a ready to use BrowserEnv gym environment.

        Args:
            task_entrypoint: a callable that returns a new task object from a seed. Used for creating a new task during `reset()`.
            task_kwargs: additional arguments passed to `task_entrypoint`.
            viewport: desired viewport size. This will override the value defined by the task, which might change its behaviour and difficulty. Should only be set for debugging/testing.
            slow_mo: desired slow_mo value for Playwright. This will override the value defined by the task, which might change its behaviour and difficulty. Should only be set for debugging/testing.
            timeout: desired timeout value for Playwright. This will override the value defined by the task, which might change its behaviour and difficulty. Should only be set for debugging/testing.
            locale: desired user locale for Playwright, for example en-GB, de-DE, etc. This will override the value defined by the task, which might change its behaviour and difficulty.
            timezone_id. desired timezone for Playwright, for example "Pacific/Tahiti". This will override the value defined by the task, which might change its behaviour and difficulty.
            tags_to_mark: which HTML tags should be marked by BrowserGym and receive a bid. Value "all" will mark every element in the page, while "standard_html" (default) will only mark standard html tags.
            interface_mode: which interface to enable - "chat_only", "browser_only", or "both".
            headless: whether the browser should run in headless mode or not. This will affect the viewport size, which might change the behaviour and difficulty of the task. Headless mode should only be disabled for debugging/testing.
            wait_for_user_message: whether the environment should pause and wait for a user message in the chat after a new message is sent by the agent. Useful for running agents in interactive mode.
            resizeable_window: whether the browser window should be resizeable or not. This will affect the viewport size, which might change the behaviour and difficulty of the task. Should only be set for debugging/testing.
            record_video_dir: if set, indicates a directory to which viewport videos will be recorded.
            pw_chromium_kwargs: extra parameters for the playwright Browser. Should only be used for debugging/testing.
            pw_context_kwargs: extra parameters for the playwright BrowserContext. Should only be used for debugging/testing.
            action_mapping: if set, the environment will use this function to map every received action to executable Python code.

        """
        super().__init__()
        self.task_entrypoint = task_entrypoint
        self.user_data_dir = user_data_dir
        self.task_kwargs = dict(**task_kwargs)
        self.messages = messages if messages else []
        self.tags_to_mark = tags_to_mark
        self.extension_communicator = extension_communicator
        self.tool_implementation_provider = tool_implementation_provider or ExtensionToolImplProvider()

        self.timeout = timeout
        self.locale = locale
        self.timezone_id = timezone_id
        self.feedback = feedback

        self.pu_processor = page_understanding_processor or ExtensionProcessor(
            extractor=PageUnderstandingExtractorChromeExtension(
                communicator=self.extension_communicator, tags_to_mark=self.tags_to_mark
            )
        )
        # check argument values
        assert tags_to_mark in ("all", "standard_html")

        # task
        self.task = None

        # playwright
        self.page_history: dict = {}

        # compatiblity
        self.page = None

        # observation space
        self.observation_space = gym.spaces.Dict(
            {
                "chat_messages": gym.spaces.Sequence(
                    gym.spaces.Dict(
                        {
                            "role": Unicode(),
                            "message": Unicode(),
                        }
                    )
                ),
                "goal": Unicode(),
                "goal_object": gym.spaces.Sequence(AnyDict()),
                "open_pages_urls": gym.spaces.Sequence(Unicode()),
                "open_pages_titles": gym.spaces.Sequence(Unicode()),
                "active_page_index": gym.spaces.Box(low=0, high=255, dtype=int),
                "url": Unicode(),
                "screenshot": AnyBox(
                    low=0,
                    high=255,
                    shape=(-1, -1, 3),
                    dtype=np.uint8,
                ),  # swapped axes (height, width, RGB)
                "dom_object": AnyDict(),
                "nocodeui_pu": AnyDict(),
                "axtree_object": AnyDict(),
                "extra_element_properties": AnyDict(),
                "focused_element_bid": Unicode(),
                "last_action": Unicode(),
                "last_action_error": Unicode(),
                "elapsed_time": gym.spaces.Box(low=0, high=np.inf, dtype=float),
            }
        )

        # action space
        self.action_space = Unicode()

    def get_url(self) -> str | None:
        return self.pu_processor.get_page_url()

    async def get_title(self) -> str | None:
        return self.pu_processor.get_page_title()

    async def close(self):
        if self.task:
            # stop the task
            await self.task.teardown()
            self.task = None

    async def reset(self, seed=None, **kwargs):
        self.np_random = None  # make sure all randomness is handled by the task

        if self.task:
            await self.task.teardown()
        # create a new task
        self.task = self.task_entrypoint(seed=seed, **self.task_kwargs)

        task_goal, task_info = await self.task.setup(page=None)

        # process the task goal
        # no goal specified
        if task_goal is None:
            self.goal_object = []
        # convert text-only goal (legacy) to new format
        elif isinstance(task_goal, str):
            self.goal_object = [{"type": "text", "text": task_goal}]
        # new format goal with multiple texts and images (OpenAI style)
        elif isinstance(task_goal, list):
            self.goal_object = task_goal
        else:
            raise ValueError(f"task_goal should be of type str or list, got {task_goal.__class__}")

        # We expect that if we arrived here from the extension the page is ready

        # init start time
        self.start_time = time.time()

        # no action yet
        self.last_action = ""
        self.last_action_error = ""
        self.infeasible_message_received = False

        # extract obs and info from environment
        self.pu_processor = ExtensionProcessor(
            PageUnderstandingExtractorChromeExtension(
                communicator=self.extension_communicator, tags_to_mark=self.tags_to_mark
            )
        )

        obs = await self._get_obs()

        info = {}
        info["task_info"] = task_info

        return obs, info

    async def send_chat_message(self, role: str, content: str):
        await self._send_to_chat(content=f"{role}, {content}")

    async def _send_to_chat(self, content: str):
        if not isinstance(content, str):
            raise ValueError(f"Forbidden value: {content} is not a string")
        # Fire-and-forget via very small timeout. The extension background
        # worker forwards these to the popup but doesn't always reply; we
        # do not want to block here.
        try:
            await self.extension_communicator.send_request(
                {"type": "agent_response", "content": content}, timeout=0.05
            )
        except Exception:
            # It's ok if this times out; the command was queued and the UI
            # will still receive it via the command stream.
            pass

    async def step(self, action: str) -> tuple:
        """Execute one environment step.

        Mirrors the async gym env flow, but relies on the Chrome extension for
        observations and uses the HTTP stream communicator to surface chat messages
        to the UI.
        """
        self.last_action = action

        info: dict[str, Any] = {}
        info["action_exec_start"] = time.time()
        info["action_exec_timeout"] = 0

        async def send_message_to_user(text: str):
            await self._send_to_chat(text)

        async def report_infeasible_instructions(reason: str):
            await self._send_to_chat(reason)
            self.infeasible_message_received = True

        # Execute action if applicable (no-op placeholder for now)
        logger.debug("Executing action (extension env)")
        try:
            # In this environment, actions are executed via higher-level tools
            # that talk to the extension. Nothing to run here yet.
            self.last_action_error = ""
        except Exception as e:
            self.last_action_error = f"{type(e).__name__}: {e}"
        finally:
            info["action_exec_stop"] = time.time()

        # Task-specific validation (no playwright page in extension mode)
        logger.debug("Initiating task validation (extension env)")
        reward, done, user_message, task_info = await self.task.validate(None, self.messages)
        info["task_info"] = task_info
        logger.debug("Task validation done (extension env)")

        # Send any user message emitted by the task to the chat UI
        if user_message:
            await self._send_to_chat(user_message)

        # Extract observation
        obs = await self._get_obs()
        logger.debug("Observation extracted (extension env)")

        terminated = done or self.infeasible_message_received
        truncated = False

        return obs, reward, terminated, truncated, info

    async def _get_obs(self):
        # Initialize default values for browser-dependent fields
        screenshot = None
        pu_output = None
        url = ""
        open_pages_urls = []
        open_pages_titles = []
        # active_page_index = np.asarray([0])
        dom_object = {}
        axtree_object = {}
        extra_properties = {}
        focused_element_bid = ""

        if not await self.extension_communicator.ping():
            return

        # post-extraction cleanup of temporary info in dom
        await self.extension_communicator.unmark_elements()

        # Get browser-specific information
        screenshot = await self.extension_communicator.extract_screenshot()
        pu_output = await self.pu_processor.extract()
        url = await self.extension_communicator.get_active_tab_url()
        # Derive title from PU extractor output to avoid extension command dependency
        title = getattr(pu_output, "page_title", None) or ""

        open_pages_urls = [url]  # For now we support only one url

        open_pages_titles = [title]  # For now we support only one title
        # active_page_index = np.asarray([0]) # TODO: Check if we need this

        # Extract pu_output fields
        dom_object = pu_output.dom_object
        axtree_object = pu_output.accessibility_tree
        extra_properties = pu_output.extra_properties
        focused_element_bid = pu_output.focused_element_bid
        nocodeui_pu = pu_output.nocodeui_pu

        # obs is generic to all tasks
        obs = {
            "chat_messages": [],  # Populate if needed
            # "goal": _try_to_extract_legacy_goal(self.goal_object),  # legacy goal, deprecated
            "goal_object": self.goal_object,  # new goal format, list of messages openai style
            "open_pages_urls": open_pages_urls,
            "open_pages_titles": open_pages_titles,
            # "active_page_index": active_page_index,
            "url": url,  # redundant with "open_pages_urls" and "active_page_index"
            "nocodeui_pu": nocodeui_pu,
            "screenshot": screenshot,
            "dom_object": dom_object,
            "dom_tree": pu_output.dom_tree,
            "axtree_object": axtree_object,
            "extra_element_properties": extra_properties,
            "focused_element_bid": focused_element_bid,
            "last_action": self.last_action,
            "last_action_error": self.last_action_error,
            "elapsed_time": np.asarray([time.time() - self.start_time]),
        }

        return obs
