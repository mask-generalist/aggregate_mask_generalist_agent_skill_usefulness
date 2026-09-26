from cuga.backend.browser_env.page_understanding.pu_extractor_chrome_extension import (
    PUExtractedChromeExtension,
    PageUnderstandingExtractorProtocol,
)
from cuga.backend.browser_env.page_understanding.pu_transform import PuAnswer
from cuga.backend.browser_env.page_understanding.tranformer_utils.dom_transform_utils import (
    flatten_domtree_to_str,
)
from cuga.backend.browser_env.page_understanding.tranformer_utils.transform_utils import flatten_axtree_to_str


from typing import Dict


class ExtensionProcessor:
    def __init__(self, extractor: PageUnderstandingExtractorProtocol) -> None:
        self.extractor = extractor

    async def extract(self, config: Dict = {}) -> PUExtractedChromeExtension:
        """Extract data and store it internally."""
        self._data = await self.extractor.extract(**config)
        return self._data

    def get_page_url(self) -> str | None:
        pu_extracted: PUExtractedChromeExtension = self._data
        if pu_extracted is None:
            raise ValueError("Extracted PU is None, call .extract() first")

        return pu_extracted.url

    def get_page_title(self) -> str | None:
        pu_extracted: PUExtractedChromeExtension = self._data
        if pu_extracted is None:
            raise ValueError("Extracted PU is None, call .extract() first")

        return getattr(pu_extracted, "page_title", None)

    async def transform(self, **kwargs) -> PuAnswer:
        pu_extracted = self._data
        if pu_extracted is None:
            raise ValueError("Extracted PU is None, call .extract() first")

        dom_tree = pu_extracted.dom_tree
        if dom_tree is not None:
            rep = flatten_domtree_to_str(
                dom_tree=dom_tree,
                extra_properties=pu_extracted.extra_properties or {},
                filter_visible_only=kwargs.get("filter_visible_only", False),
            )
        else:
            rep = flatten_axtree_to_str(
                AX_tree=pu_extracted.accessibility_tree,
                extra_properties=pu_extracted.extra_properties or {},
                filter_visible_only=kwargs.get("filter_visible_only", False),
            )

        if not pu_extracted.page_content_as_str:
            raise ValueError("No page_content_as_str found")

        return PuAnswer(
            string_representation=rep,
            focused_element_bid=pu_extracted.focused_element_bid,
            page_content=pu_extracted.page_content_as_str,
            img=f"data:image/png;base64,{pu_extracted.img}",
            key_value_map={},
        )
