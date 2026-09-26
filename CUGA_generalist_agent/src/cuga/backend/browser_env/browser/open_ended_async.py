# Copyright 2024 ServiceNow
# Modifications Copyright 2025 CUGA
# Licensed under the Apache License, Version 2.0

from abc import ABC, abstractmethod
from typing import Tuple

import numpy as np
import playwright.async_api


class AbstractBrowserTask(ABC):
    """
    Abstract class for browsergym tasks.

    """

    @classmethod
    @abstractmethod
    def get_task_id(cls):
        pass

    def __init__(self, seed: int | None) -> None:
        # initiate a random number generator
        self.random = np.random.RandomState(seed)
        # task properties, will be used to set up the browsergym environment
        # default values, can be overriden in children classes
        self.viewport = {"width": 1280, "height": 720}
        self.slow_mo = 1000  # ms
        self.timeout = 5000  # ms
        self.locale = (
            None  # see https://playwright.dev/python/docs/api/class-browser#browser-new-context-option-locale
        )
        self.timezone_id = None  # see https://playwright.dev/python/docs/api/class-browser#browser-new-context-option-timezone-id

    @abstractmethod
    async def setup(self, page: playwright.async_api.Page | None) -> tuple[str, dict]:
        """
        Set up everything needed to execute the task.

        Args:
            page: the active playwright page.

        Returns:
            goal: str, goal of the task.
            info: dict, custom information from the task.
        """

    @abstractmethod
    async def teardown(self) -> None:
        """
        Tear down the task and clean up any ressource / data created by the task.

        """

    @abstractmethod
    async def validate(
        self, page: playwright.async_api.Page, chat_messages: list[str]
    ) -> Tuple[float, bool, str, dict]:
        """
        Validate the task was completed successfully

        Args:
            page: the active playwright page.
            chat_messages: the chat messages.

        Returns:
            reward: float, the reward obtained since last call to validate().
            done: boolean flag, indicates if the task has finished or not (be it success or fail).
            message: string, a new user message for the chat.
            info: dictionnary, custom information from the task.

        """

    async def cheat(self, page: playwright.async_api.Page, chat_messages: list[str]) -> None:
        """
        Solve the task using a pre-defined solution (optional).

        """
        raise NotImplementedError


class OpenEndedTaskAsync(AbstractBrowserTask):
    @classmethod
    def get_task_id(cls):
        return "openended"

    def __init__(self, seed: int, start_url: str, goal: str | None = None) -> None:
        """
        Args:
            seed: random seed.
            start_url: str, the url for the starting page.
            goal: str, the initial goal.

        """
        super().__init__(seed)
        self.start_url = start_url
        self.goal = goal

    async def setup(self, page: playwright.async_api.Page | None) -> tuple[str, dict]:
        if page:
            await page.goto(self.start_url, timeout=30000)
        return self.goal, {}

    async def teardown(self) -> None:
        pass

    async def validate(
        self, page: playwright.async_api.Page, chat_messages: list[str]
    ) -> Tuple[float, bool, str, dict]:
        reward, done, msg, info = 0, False, "", {}

        # for message in chat_messages:
        #
        #     if message["role"] == "user" and message["message"] == "exit":
        #         done = True
        #         break

        return reward, done, msg, info
