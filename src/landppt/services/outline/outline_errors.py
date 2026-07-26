"""Outline-generation error types.

Deliberately dependency-free so any layer can catch these without importing the
outline services (which pull in research/AI/image stacks).
"""

from __future__ import annotations

from typing import List


class OutlineRepairFailedError(Exception):
    """Raised when an outline cannot be made valid.

    Callers must surface this rather than persisting the invalid outline: doing the
    latter marked projects "completed" with an unusable outline.
    """

    def __init__(self, validation_errors: List[str]):
        self.validation_errors = list(validation_errors or [])
        detail = "; ".join(self.validation_errors) or "未知校验错误"
        super().__init__(f"大纲校验未通过且自动修复失败：{detail}")
