# Copyright 2024 ServiceNow
# Modifications Copyright 2025 CUGA
# Licensed under the Apache License, Version 2.0
import asyncio
import logging
import re
import time
from abc import ABC
from pathlib import Path
from typing import Any, List, Literal, Optional

import gymnasium as gym
import numpy as np

# from browsergym.core.action.base import execute_python_code_async  # Assume async version
from browsergym.core.action.highlevel import HighLevelActionSet
from browsergym.core.constants import BROWSERGYM_ID_ATTRIBUTE
from browsergym.core.spaces import AnyBox, AnyDict, Unicode
from langchain_core.messages import AIMessage
from playwright.async_api import Browser, BrowserContext
from playwright.async_api import Error as PlaywrightError
from playwright.async_api import Page, Playwright

from cuga.backend.browser_env.browser.chat_async import Chat
from cuga.backend.browser_env.browser.gym_obs.obs_async import (
    _post_extract,
    extract_screenshot,
)
from cuga.backend.browser_env.browser.open_ended_async import AbstractBrowserTask
from cuga.backend.browser_env.browser.utils_async import _get_global_playwright_async
from cuga.backend.browser_env.page_understanding.pu_extractor import PageUnderstandingExtractor
from cuga.backend.browser_env.page_understanding.pu_processor import PageUnderstandingProcessor
from cuga.backend.browser_env.tools.providers import BrowserToolImplProvider, PlaywrightToolImplProvider

logger = logging.getLogger(__name__)


def _try_to_extract_legacy_goal(goal: list):
    legacy_goal_strings = []
    for message in goal:
        if message["type"] == "text":
            legacy_goal_strings.append(message["text"])
        else:
            logger.debug(
                f"Message type {repr(message['type'])} present in the goal, cannot be converted to legacy text-only format."
            )
            legacy_goal_strings.append(
                'WARNING: This goal cannot be converted to a text-only goal format. Use the new goal format instead ("goal_object" field). Any agent reading this should abort immediately.'
            )
            break
    legacy_goal = "\n".join(legacy_goal_strings)

    return legacy_goal


class BrowserEnvGymAsync(gym.Env, ABC):
    """The main BrowserGym class, which encapsulates instruction-following Web browsing into a Gymnasium environment."""

    # gym metadata
    metadata = {"render_modes": None}

    def __init__(
        self,
        # task-related arguments
        task_entrypoint: type[AbstractBrowserTask],
        task_kwargs: dict = {},
        feedback: List[Any] = [],
        enable_playwright_tracing: Optional[bool] = False,
        user_data_dir: Optional[str] = None,
        viewport: Optional[dict] = None,  # will override the task's viewport
        slow_mo: Optional[int] = None,  # will override the task's slow_mo
        timeout: Optional[int] = None,  # will override the task's timeout
        locale: Optional[str] = None,  # will override the task's locale
        timezone_id: Optional[str] = None,  # will override the task's timezone_id
        tags_to_mark: Literal["all", "standard_html"] = "standard_html",
        interface_mode: Literal["chat_only", "browser_only", "both", "none"] = "both",
        messages: List[AIMessage] = None,
        channel: Optional[str] = None,
        # interactive / debugging arguments
        headless: bool = True,
        wait_for_user_message: bool = False,
        terminate_on_infeasible: bool = True,
        resizeable_window: bool = False,
        record_video_dir: Optional[str] = None,
        pw_chromium_kwargs: dict = {},
        pw_context_kwargs: dict = {},
        enable_nocodeui_pu: bool = False,
        pw_extra_args: list = [],
        # agent-related arguments
        action_mapping: Optional[callable] = HighLevelActionSet().to_python_code,
        tool_implementation_provider: BrowserToolImplProvider | None = None,
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
        self.tool_implementation_provider = tool_implementation_provider or PlaywrightToolImplProvider()
        self.task_entrypoint = task_entrypoint
        self.user_data_dir = user_data_dir
        self.task_kwargs = dict(**task_kwargs)
        self.interface_mode = interface_mode
        self.enable_chat = interface_mode in ["chat_only", "both"]
        self.enable_browser = interface_mode in ["browser_only", "both"]
        self.messages = messages if messages else []
        self.viewport = viewport
        self.pu_processor = None
        self.slow_mo = slow_mo
        self.channel = channel
        self.timeout = timeout
        self.locale = locale
        self.enable_playwright_tracing = enable_playwright_tracing
        self.timezone_id = timezone_id
        self.tags_to_mark = tags_to_mark
        self.headless = headless
        self.wait_for_user_message = wait_for_user_message
        self.terminate_on_infeasible = terminate_on_infeasible
        self.resizeable_window = resizeable_window
        self.record_video_dir = record_video_dir
        self.pw_chromium_kwargs = pw_chromium_kwargs
        self.pw_context_kwargs = pw_context_kwargs
        self.action_mapping = action_mapping
        self.feedback = feedback
        # check argument values
        assert tags_to_mark in ("all", "standard_html")
        assert interface_mode in ("chat_only", "browser_only", "both", "none")
        self.enable_nocodeui_pu = enable_nocodeui_pu
        self.pw_extra_args = pw_extra_args

        # task
        self.task = None

        # playwright
        self.playwright: Playwright = None
        self.browser: Browser = None
        self.context: BrowserContext = None
        self.page: Page = None
        self.page_history: dict = {}

        # chat
        self.chat: Chat = None

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

    async def get_title(self) -> str | None:
        return await self.page.title()

    async def close(self):
        if self.task:
            # stop the task
            await self.task.teardown()
            # close the chat
            if self.enable_chat and self.chat:
                await self.chat.close()
            # close the browser context
            if self.enable_browser and self.context:
                await self.context.close()
            # close the browser
            if self.enable_browser and self.browser:
                await self.browser.close()
            self.task = None
        # if self.playwright:
        #     await self.playwright.stop()

    async def reset(self, seed=None, **kwargs):
        super().reset(seed=seed, **kwargs)
        self.np_random = None  # make sure all randomness is handled by the task

        if self.task:
            await self.task.teardown()
            if self.enable_browser and self.context:
                await self.context.close()
            if self.enable_chat and self.chat:
                await self.chat.close()
            if self.enable_browser and self.browser:
                await self.browser.close()

        # create a new task
        self.task = self.task_entrypoint(seed=seed, **self.task_kwargs)

        def override_property(task, env, property):
            """Extract property value from env if not None, otherwise from task."""
            env_value = getattr(env, property)
            task_value = getattr(task, property)
            if env_value is None:
                return task_value
            else:
                if task_value is not None:
                    logger.warning(
                        f"Overriding the task's {property} parameter ({repr(task_value)} => {repr(env_value)}). This might change the task's behaviour and difficulty."
                    )
                return env_value

        # fetch task's desired parameters for browser setup
        viewport = override_property(self.task, self, "viewport")
        slow_mo = override_property(self.task, self, "slow_mo")
        timeout = override_property(self.task, self, "timeout")
        locale = override_property(self.task, self, "locale")
        timezone_id = override_property(self.task, self, "timezone_id")

        # use the global Playwright instance
        self.playwright = await _get_global_playwright_async()

        # important: change playwright's test id attribute from "data-testid" to "bid"
        self.playwright.selectors.set_test_id_attribute(BROWSERGYM_ID_ATTRIBUTE)

        # Only set up browser if it's enabled
        if self.enable_browser:
            # create a new browser context for pages
            current_args = (
                [f"--window-size={viewport['width']},{viewport['height']}"]
                if self.resizeable_window
                else None
            )

            if len(self.pw_extra_args) > 0 and current_args:
                current_args.extend(self.pw_extra_args)
            else:
                current_args = self.pw_extra_args if len(self.pw_extra_args) > 0 else None

            # create a new browser context for pages
            self.context = await self.playwright.chromium.launch_persistent_context(
                self.user_data_dir if self.user_data_dir else "",
                channel=self.channel,
                no_viewport=True if self.resizeable_window else None,
                headless=self.headless,
                slow_mo=slow_mo,
                args=(current_args),
                # viewport=viewport,
                record_video_dir=(
                    Path(self.record_video_dir) / "task_video" if self.record_video_dir else None
                ),
                record_video_size=viewport,
                locale=locale,
                timezone_id=timezone_id,
                # will raise an Exception if above args are overriden
                **self.pw_chromium_kwargs,
                **self.pw_context_kwargs,
            )
            if self.enable_playwright_tracing:
                await self.context.tracing.start(screenshots=True, snapshots=True)
            self.browser = self.context

            # set default timeout
            self.context.set_default_timeout(timeout)

            # hack: keep track of the active page with a javascript callback
            # there is no concept of active page in playwright
            # https://github.com/microsoft/playwright/issues/2603
            await self.context.expose_binding(
                "browsergym_page_activated",
                lambda source: asyncio.create_task(self._activate_page_from_js(source["page"])),
            )
            await self.context.add_init_script(
                """
    window.browsergym_page_activated();
    window.addEventListener("focus", () => {window.browsergym_page_activated();}, {capture: true});
    window.addEventListener("focusin", () => {window.browsergym_page_activated();}, {capture: true});
    window.addEventListener("load", () => {window.browsergym_page_activated();}, {capture: true});
    window.addEventListener("pageshow", () => {window.browsergym_page_activated();}, {capture: true});
    window.addEventListener("mousemove", () => {window.browsergym_page_activated();}, {capture: true});
    window.addEventListener("mouseup", () => {window.browsergym_page_activated();}, {capture: true});
    window.addEventListener("mousedown", () => {window.browsergym_page_activated();}, {capture: true});
    window.addEventListener("wheel", () => {window.browsergym_page_activated();}, {capture: true});
    window.addEventListener("keyup", () => {window.browsergym_page_activated();}, {capture: true});
    window.addEventListener("keydown", () => {window.browsergym_page_activated();}, {capture: true});
    window.addEventListener("input", () => {window.browsergym_page_activated();}, {capture: true});
    window.addEventListener("touchstart", () => {window.browsergym_page_activated();}, {capture: true});
    window.addEventListener("touchend", () => {window.browsergym_page_activated();}, {capture: true});
    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "visible") {
            window.browsergym_page_activated();
        }
    }, {capture: true});

    window.__last_alert = null;
    window.alert = (message) => {
       window.__last_alert = message;
       // Optionally, log the intercepted alert message
       console.log("Intercepted alert: " + message);
    };
    """
            )

            # create a new page
            self.page = self.context.pages[0]

        recording_start_time = time.time()

        # create the chat if it's enabled
        if self.enable_chat:
            self.chat = Chat(
                headless=self.headless,
                chat_size=(500, max(viewport["height"] if viewport else 800, 800)),
                record_video_dir=self.record_video_dir,
            )
            await self.chat.init()

        # setup the task - if browser-only mode, we might need to adjust this
        # based on your task architecture
        if self.enable_browser:
            task_goal, task_info = await self.task.setup(page=self.page)
        else:
            # In chat-only mode, we might need a special setup path
            # This depends on your task implementation
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

        # initialize the chat if enabled
        if self.enable_chat:
            await self.chat.add_message(
                role="assistant",
                msg="Hi! I am your UI assistant, I can perform web tasks for you. What can I help you with?",
            )

            # send task goal (if any) to the chat
            for message in self.goal_object:
                match message["type"]:
                    case "text":
                        await self.chat.add_message(role="user", msg=message["text"])
                    case "image_url":
                        image_src = message["image_url"]
                        if isinstance(image_src, dict):
                            image_src = image_src["url"]
                        await self.chat.add_message(role="user_image", msg=image_src)
                    case _:
                        raise ValueError(f"Unknown message type {repr(message['type'])} in the task goal.")

        # Wait for DOM to load if browser is enabled
        if self.enable_browser:
            await self._wait_dom_loaded()

            # after the task's setup, the active page might have changed
            # perform a safety check
            await self._active_page_check()

        # init start time
        self.start_time = time.time()

        # no action yet
        self.last_action = ""
        self.last_action_error = ""
        self.infeasible_message_received = False

        # if asked, wait for user message (if chat is enabled)
        if self.enable_chat:
            await self._wait_for_user_message()

        # extract obs and info from environment
        if self.enable_browser:
            self.pu_processor = PageUnderstandingProcessor(
                PageUnderstandingExtractor(tags_to_mark=self.tags_to_mark)
            )

        obs = await self._get_obs()

        info = {}
        info["task_info"] = task_info

        # Video recording info if enabled
        if self.record_video_dir:
            info["recording_start_time"] = recording_start_time
            if self.enable_browser and self.page and self.page.video:
                info["recording_file"] = str(await self.page.video.path())
            if self.enable_chat and self.chat:
                info["chat"] = {
                    "recording_start_time": self.chat.recording_start_time,
                    "recording_file": str(await self.chat.page.video.path()),
                }

        return obs, info

    async def step(self, action: str) -> tuple:
        self.last_action = action

        info = {}
        info["action_exec_start"] = time.time()
        info["action_exec_timeout"] = 0

        async def send_message_to_user(text: str):
            if not isinstance(text, str):
                raise ValueError(f"Forbidden value: {text} is not a string")
            if self.enable_chat:
                await self.chat.add_message(role="assistant", msg=text)

        async def report_infeasible_instructions(reason: str):
            if not isinstance(reason, str):
                raise ValueError(f"Forbidden value: {reason} is not a string")
            if self.enable_chat:
                await self.chat.add_message(role="infeasible", msg=reason)
            self.infeasible_message_received = True

        # try to execute the action if browser is enabled
        logger.debug("Executing action")
        try:
            if self.enable_browser:
                # Placeholder for action execution code:
                # if self.action_mapping:
                #     code = self.action_mapping(action)
                # else:
                #     code = action
                # await execute_python_code_async(
                #     code,
                #     self.page,
                #     send_message_to_user=send_message_to_user,
                #     report_infeasible_instructions=report_infeasible_instructions,
                # )
                pass
            self.last_action_error = ""
        except Exception as e:
            self.last_action_error = f"{type(e).__name__}: {e}"
            match = re.match(r"TimeoutError: Timeout ([0-9]+)ms exceeded.", self.last_action_error)
            if match:
                info["action_exec_timeout"] = float(match.groups()[0]) / 1000  # ms to sec
        logger.debug("Action executed")
        info["action_exec_stop"] = time.time()

        if self.enable_browser:
            # wait a bit (for the JavaScript callback to set the active page)
            await asyncio.sleep(0.5)  # wait for JS events to be fired (half a second)
            await self.context.cookies()  # trigger all waiting Playwright callbacks on the stack (hack)

            # wait for the network to idle before extracting the observation, reward etc.
            await self._wait_dom_loaded()

            # after the action is executed, the active page might have changed
            # perform a safety check
            await self._active_page_check()
            logger.debug("Active page checked")

        # if asked, wait for user message (if chat is enabled)
        if self.enable_chat:
            await self._wait_for_user_message()
            logger.debug("User message done")

        logger.debug("Initiating task validation")
        # extract reward, done, user_message, info (task-specific)
        reward, done, user_message, task_info = await self._task_validate()
        info["task_info"] = task_info
        logger.debug("Task validation done")

        # add any user message sent by the task to the chat
        if user_message and self.enable_chat:
            await self.chat.add_message(role="user", msg=user_message)

        # extract observation (generic)
        obs = await self._get_obs()
        logger.debug("Observation extracted")

        # new step API wants a 5-tuple (gymnasium)
        terminated = done or (
            self.terminate_on_infeasible and self.infeasible_message_received
        )  # task or agent can terminate the episode
        truncated = False

        return obs, reward, terminated, truncated, info

    async def _task_validate(self):
        # back-up these in case validate() navigates pages and messes the history
        if self.enable_browser:
            prev_active_page = self.page
            prev_page_history = self.page_history.copy()

        # call validate
        if self.enable_browser:
            reward, done, user_message, info = await self.task.validate(self.page, self.messages)
        else:
            # In chat-only mode, we might need a special validation path
            reward, done, user_message, info = await self.task.validate(None, self.messages)

        # safety fix, in case validate() did mess up the active page and/or page history
        if self.enable_browser and (prev_active_page != self.page or prev_page_history != self.page_history):
            logger.info(
                "The active page and / or page history has changed during task.validate(). A recovery fix will be applied."
            )
            self.page = prev_active_page
            self.page_history = prev_page_history

        return reward, done, user_message, info

    async def _wait_for_user_message(self):
        # if last message is from the assistant, wait for a user message to continue
        if self.enable_chat:
            if self.chat.messages[-1]["role"] == "assistant" and self.wait_for_user_message:
                await self.chat.wait_for_user_message()

    async def _wait_dom_loaded(self):
        if not self.enable_browser:
            return

        for page in self.context.pages:
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=15000)
            except PlaywrightError:
                pass
            for frame in page.frames:
                try:
                    await frame.wait_for_load_state("domcontentloaded", timeout=15000)
                except PlaywrightError:
                    pass

    async def _activate_page_from_js(self, page: Page):
        if not self.enable_browser:
            return

        logger.debug(f"_activate_page_from_js(page) called, page={str(page)}")
        if not page.context == self.context:
            raise RuntimeError(
                f"Unexpected: activating a page that belongs to a different browser context ({page})."
            )

        # add the activated page to the page history (or move it to last which is the most recent)
        if page in self.page_history:
            self.page_history[page] = self.page_history.pop(page)  # move page to the end of dictionary
        else:
            self.page_history[page] = None  # add page to the end of dictionary

        self.page = page

    async def _active_page_check(self):
        if not self.enable_browser:
            return

        # make sure there is always a page open
        # if all pages have been closed, create a new page
        if len(self.context.pages) == 0:
            logger.warning("All pages are closed, opening a new page.")
            self.page = await self.context.new_page()

        # if the active page got closed, get the last active page from the history
        while self.page_history and (self.page.is_closed() or self.page not in self.context.pages):
            self.page_history.pop(self.page)  # remove active page from history
            if self.page_history:
                self.page = list(self.page_history.keys())[-1]  # set last active page as the active page
            else:
                self.page = await self.context.new_page()

        # active page should share the same browser context with the environment
        if self.page not in self.context.pages:
            raise RuntimeError(
                f"Unexpected: active page is not part of the browser context's open pages ({self.page})."
            )

        # active page should not be closed
        if self.page.is_closed():
            raise RuntimeError(f"Unexpected: active page has been closed ({self.page}).")

    def get_url(self) -> str | None:
        if self.page:
            return getattr(self.page, "url", None)
        return None

    async def send_chat_message(self, role: str, content: str):
        await self.chat.add_message(role, content)

    async def _get_obs(self):
        # for retries_left in reversed(range(EXTRACT_OBS_MAX_TRIES)):
        #     try:
        #         # pre-extraction, mark dom elements (set bid, set dynamic attributes like value and checked)
        #         await _pre_extract(self.page, tags_to_mark=self.tags_to_mark, lenient=(retries_left == 0))
        #
        #         dom = await extract_dom_snapshot(self.page)
        #         axtree = await extract_merged_axtree(self.page)
        #         focused_element_bid = await extract_focused_element_bid(self.page)
        #         extra_properties = extract_dom_extra_properties(dom)
        #     except (PlaywrightError, MarkingError) as e:
        #         err_msg = str(e)
        #         # try to add robustness to async events (detached / deleted frames)
        #         if retries_left > 0 and (
        #             "Frame was detached" in err_msg
        #             or "Frame with the given frameId is not found" in err_msg
        #             or "Execution context was destroyed" in err_msg
        #             or "Frame has been detached" in err_msg
        #             or "Cannot mark a child frame without a bid" in err_msg
        #         ):
        #             logger.warning(
        #                 f"An error occurred while extracting the dom and axtree. Retrying ({retries_left}/{EXTRACT_OBS_MAX_TRIES} tries left).\n{repr(e)}"
        #             )
        #             # post-extract cleanup (ARIA attributes)
        #             await _post_extract(self.page)
        #             await asyncio.sleep(0.5)
        #             continue
        #         else:
        #             raise e
        #     break

        # Initialize default values for browser-dependent fields
        screenshot = None
        pu_output = None
        url = ""
        open_pages_urls = []
        open_pages_titles = []
        active_page_index = np.asarray([0])
        dom_object = {}
        axtree_object = {}
        extra_properties = {}
        focused_element_bid = ""

        if self.enable_browser:
            # post-extraction cleanup of temporary info in dom
            await _post_extract(self.page)

            # Get browser-specific information
            screenshot = await extract_screenshot(self.page)
            pu_output = await self.pu_processor.extract(page=self.page, context=self.context)
            url = self.page.url
            open_pages_urls = [page.url for page in self.context.pages]
            open_pages_titles = [await page.title() for page in self.context.pages]
            active_page_index = np.asarray([self.context.pages.index(self.page)])

            # Extract pu_output fields
            dom_object = pu_output.dom_object
            axtree_object = pu_output.accessibility_tree
            extra_properties = pu_output.extra_properties
            focused_element_bid = pu_output.focused_element_bid
            nocodeui_pu = pu_output.nocodeui_pu
        else:
            nocodeui_pu = {}

        # obs is generic to all tasks
        obs = {
            "chat_messages": [],  # Populate if needed
            "goal": _try_to_extract_legacy_goal(self.goal_object),  # legacy goal, deprecated
            "goal_object": self.goal_object,  # new goal format, list of messages openai style
            "open_pages_urls": open_pages_urls,
            "open_pages_titles": open_pages_titles,
            "active_page_index": active_page_index,
            "url": url,  # redundant with "open_pages_urls" and "active_page_index"
            "nocodeui_pu": nocodeui_pu,
            "screenshot": screenshot,
            "dom_object": dom_object,
            "axtree_object": axtree_object,
            "extra_element_properties": extra_properties,
            "focused_element_bid": focused_element_bid,
            "last_action": self.last_action,
            "last_action_error": self.last_action_error,
            "elapsed_time": np.asarray([time.time() - self.start_time]),
        }

        return obs
