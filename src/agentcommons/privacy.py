"""Private local credentials and journals on both POSIX and Windows."""

import getpass
import os
from pathlib import Path

from .processes import external_run


def private_acl(path):
    if os.name == 'nt':
        domain = os.getenv('USERDOMAIN', '')
        user = (domain + '\\' if domain else '') + getpass.getuser()
        executable = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/icacls.exe'
        external_run([str(executable), str(path), '/inheritance:r', '/grant:r', user + ':F'],
                     check=True, capture_output=True)
