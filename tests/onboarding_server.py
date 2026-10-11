"""A fresh local installation for browser onboarding tests."""

import os
from pathlib import Path
import tempfile

import uvicorn

from agentcommons.server import create_app
from agentcommons.setup import apply_setup, prepare_setup

with tempfile.TemporaryDirectory(prefix='agentverse-onboarding-browser-') as temporary:
    home = Path(temporary)
    apply_setup(home, prepare_setup(home, 8100), override=True)
    os.environ['AGENTVERSE_WELCOME_TOKEN'] = 'browser-onboarding-capability'
    for prefix in ('AGENTVERSE', 'AGENTCOMMONS'):
        for name in ('ADMIN_USERNAME', 'ADMIN_PASSWORD'):
            os.environ.pop(prefix + '_' + name, None)
    uvicorn.run(create_app(local_home=home), host='127.0.0.1', port=8100)
