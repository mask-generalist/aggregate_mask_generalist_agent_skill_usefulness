import uuid
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

TCommand = TypeVar("TCommand", bound=BaseModel)
TResponse = TypeVar("TResponse")


class Rule(BaseModel):
    color: str
    name: str
    type: str


class DOMRect(BaseModel):
    x: float
    y: float
    width: float
    height: float


class Html(BaseModel):
    attributes: dict
    boundingRect: DOMRect
    outerText: str
    tagName: str


class Match(BaseModel):
    rule: Rule
    selector: str


class Text(BaseModel):
    value: str
    source: str


class ElementSelector(BaseModel):
    generated: str

    model_config = ConfigDict(extra="allow")


class InterestingElement(BaseModel):
    id: str
    html: Html
    match: Match
    selectors: ElementSelector
    text: Text
    nearbyLabels: list["InterestingElement"]


class AnalyzePageResponse(BaseModel):
    output: dict
    map: dict[str, InterestingElement]


class BrowserTab(BaseModel):
    id: int
    index: int
    active: bool
    url: Optional[str] = None
    title: Optional[str] = None
    windowId: Optional[int] = None


class StateResponse(BaseModel):
    tab: Optional[BrowserTab] = None
    pageAnalysis: Optional["AnalyzePageResponse"] = None


class StateCommand(BaseModel):
    rules: Optional[list[dict]] = None
    tabId: Optional[int]
    windowId: Optional[int]
    timeout: Optional[float]
    type: str
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))

    model_config = ConfigDict(use_enum_values=True)

    def __init__(
        self,
        tabId: Optional[int] = None,
        windowId: Optional[int] = None,
        timeout: Optional[float] = None,
        rules: Optional[list[dict]] = None,
    ) -> None:
        """Cretes the state command.
        Args:
            ``tabId``: The tab id to perform the command.
            ``windowId``: The window id to perform the command. If ``tabId`` is specified, then ``windowId`` is ignored.
            ``timeout``: The timeout in seconds to wait for the response.
        """
        super().__init__(
            type="pu.browser.state",
            tabId=tabId,
            windowId=windowId,
            timeout=timeout * 1000 if timeout else None,
            rules=rules,
        )


class Response(BaseModel, Generic[TResponse]):
    id: str
    error: Optional[Any] = None
    data: Optional[TResponse] = None


_JS_CODE = """
async (command) => {
    command = JSON.parse(command);
    console.log(`Executing command '${command.type}':`, command);
    const response = await globalThis.ibm.runtime.execute(command);
    console.log(`Command '${command.type}' returned:`, response);
    return JSON.stringify(response);
}
"""
