"""Deterministic test peer. The real worker still uses real Git and the live API."""

import json
import subprocess
import sys
from pathlib import Path

prompt = Path(sys.argv[1]).read_text()
context = json.loads(prompt.split("PROJECT CONTEXT\n", 1)[1])
task = context["task"]
if "Review the checked-out submission" in prompt:
    assert Path("feature.txt").read_text() == "Built by an independent remote teammate.\n"
    result = {"decision": "approve", "comment": "Inspected feature.txt on the submitted commit; content verified."}
elif task["kind"] == "planning":
    result = {"summary": "One bounded implementation task.", "tasks": [{"title": "Create feature.txt", "description": "Commit the feature file."}]}
else:
    Path("feature.txt").write_text("Built by an independent remote teammate.\n")
    subprocess.run(["git", "add", "feature.txt"], check=True)
    subprocess.run(["git", "commit", "-m", "Add collaborative feature"], check=True)
    result = {"summary": "Feature committed and content checked.", "memory": [{"title": "Feature handoff", "content": "feature.txt is the entry point.", "tags": ["handoff"]}]}
print("```agentcommons\n" + json.dumps(result) + "\n```")
