import importlib
from typing import Any, Dict

from playwright.async_api import BrowserContext, Page

from cuga.config import settings
from cuga.backend.browser_env.page_understanding.pu_extractor import PUExtracted
from cuga.backend.browser_env.page_understanding.pu_transform import PuAnswer


class PageUnderstandingProcessor:
    def __init__(self, extractor: Any):
        self.extractor = extractor
        self._data = None  # Internal state to store extracted data
        self.transformer = None
        self.load_transformer(settings.page_understanding.transformer_path)

    async def extract(self, context: BrowserContext, page: Page, config: Dict = {}) -> PUExtracted:
        """Extract data and store it internally."""
        self._data = await self.extractor.extract(context, page, **config)
        return self._data

    def load_transformer(self, transformer_path: str, transformer_params: Dict = {}) -> None:
        """Dynamically load a transformer class from a module."""
        try:
            module_name, class_name = transformer_path.rsplit(".", 1)
            module = importlib.import_module(module_name)
            transformer_class = getattr(module, class_name)
            self.transformer = transformer_class()
        except (ImportError, AttributeError) as e:
            raise ImportError(f"Could not import transformer '{transformer_path}': {e}")

    async def transform(self, transformer_params: Dict = {}) -> PuAnswer:
        """Transform the previously extracted data."""
        if self._data is None:
            raise ValueError("No data has been extracted yet. Call `extract()` first.")
        if self.transformer is None:
            raise ValueError("No transformer has been loaded. Load a transformer first.")
        return await self.transformer.transform(self._data, **transformer_params)
