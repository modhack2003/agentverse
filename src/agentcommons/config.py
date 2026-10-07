"""AgentVerse settings, with compatibility for existing AgentCommons deployments."""

import os

PRODUCT = "AgentVerse"
VERSION = "0.2.0"
PROTOCOL_VERSION = 1


def setting(name, default=""):
    return os.getenv(f"AGENTVERSE_{name}", os.getenv(f"AGENTCOMMONS_{name}", default))


def identity_env(server, token, model="", settings=None):
    import json
    values = {"SERVER": server, "AGENT_TOKEN": token, "MODEL": model,
              "SETTINGS": json.dumps(settings or {})}
    return {f"{prefix}_{key}": value for prefix in ("AGENTVERSE", "AGENTCOMMONS") for key, value in values.items()}
