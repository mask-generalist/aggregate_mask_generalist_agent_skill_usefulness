from abc import ABC
from typing import Optional, Any, Dict


class Validator(ABC):
    """
    Abstract class which should be extended for actual implementation of validators.

    :param config: configuration for validator initialization. Default to ``None``.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
