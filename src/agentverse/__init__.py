"""AgentVerse's public SDK. Existing agentcommons imports remain compatible."""

from agentcommons.config import VERSION as __version__
from agentcommons.client import Client

__all__ = ["Client", "__version__"]
