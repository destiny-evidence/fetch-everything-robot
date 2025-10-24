"""Authentication strategies for the Fetch Everything Robot."""

import destiny_sdk

from app.config import Environment, Settings


def auth_strategy_robot(settings: Settings) -> destiny_sdk.auth.HMACAuthMethod:
    """Select the authentication strategy to use on the robot's API endpoints."""
    # If we're running in the local environment, disable endpoint authentication.
    if settings.env in (Environment.LOCAL, Environment.TEST):
        return destiny_sdk.auth.BypassHMACAuth()

    return destiny_sdk.auth.HMACAuth(secret_key=settings.robot_secret)
