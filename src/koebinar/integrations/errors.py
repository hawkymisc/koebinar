"""Integration error types.

``IntegrationError`` はここで定義し、``integrations.service`` から再 export する
(既存の ``from koebinar.integrations.service import IntegrationError`` は不変)。
``voice_consent`` が service を import せずに派生できるようにするための分離。
"""

from __future__ import annotations


class IntegrationError(Exception):
    def __init__(self, message: str, code: str | None = None, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
