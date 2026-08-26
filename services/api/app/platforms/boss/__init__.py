"""BOSS 直聘 adapter.

This package only handles structured observations from a user-visible browser
page. It never performs HTTP requests, accepts credentials, or uploads browser
state to the API.
"""

from app.platforms.boss.adapter import BossZhipinAdapter

__all__ = ["BossZhipinAdapter"]
