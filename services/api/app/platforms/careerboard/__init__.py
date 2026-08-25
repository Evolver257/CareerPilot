"""CareerBoard platform adapter prototype.

This package is deliberately isolated from the generic BrowserTask workflow.
It contains only local, user-session-safe parsing and action descriptions;
it never handles credentials or attempts to bypass platform controls.
"""

from app.platforms.careerboard.adapter import CareerBoardAdapter

__all__ = ["CareerBoardAdapter"]
