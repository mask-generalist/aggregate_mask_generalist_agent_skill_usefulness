import logging
from typing import Optional

from pydantic import BaseModel

from cuga.backend.browser_env.page_understanding.pu_extractor import PUExtracted
from cuga.backend.browser_env.page_understanding.tranformer_utils.transform_utils import flatten_axtree_to_str


class PuAnswer(BaseModel):
    string_representation: str
    key_value_map: dict
    focused_element_bid: Optional[str] = None
    img: str
    page_content: str


class PageUnderstandingV1:
    def __init__(self):
        pass

    async def transform(self, pu_extracted: PUExtracted, filter_visible_only=True) -> PuAnswer:
        if pu_extracted is None:
            err_msg = "Extracted pu is None please call `.extract()` first"
            logging.error(err_msg)
            raise Exception(err_msg)
        return PuAnswer(
            string_representation=flatten_axtree_to_str(
                AX_tree=pu_extracted.accessibility_tree,
                extra_properties=pu_extracted.extra_properties,
                filter_visible_only=filter_visible_only,
            ),
            focused_element_bid=pu_extracted.focused_element_bid,
            page_content=pu_extracted.page_content_as_str,
            img="data:image/png;base64,{}".format(pu_extracted.img),
            key_value_map={},
        )
