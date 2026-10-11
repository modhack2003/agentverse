"""Optional signing using repository-owner certificates; passwords never enter logs."""

import base64
import os
from pathlib import Path
import subprocess
import tempfile


def windows_sign(path):
    certificate = os.getenv('WINDOWS_SIGNING_PFX')
    if not certificate:
        return False
    candidates = list(Path('C:/Program Files (x86)/Windows Kits/10/bin').glob('*/x64/signtool.exe'))
    if not candidates:
        raise ValueError('Windows signing was requested but signtool was not found.')
    with tempfile.TemporaryDirectory() as temporary:
        pfx = Path(temporary) / 'certificate.pfx'
        pfx.write_bytes(base64.b64decode(certificate))
        command = [str(sorted(candidates)[-1]), 'sign', '/fd', 'SHA256', '/f', str(pfx),
                   '/p', os.getenv('WINDOWS_SIGNING_PASSWORD', ''), '/tr', 'http://timestamp.digicert.com', '/td', 'SHA256', str(path)]
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode:
            raise ValueError('Windows code signing failed. Check the certificate, password and timestamp service.')
    return True


def macos_certificate():
    certificate = os.getenv('MACOS_SIGNING_P12')
    if not certificate:
        return None
    keychain = Path(os.environ.get('RUNNER_TEMP', tempfile.gettempdir())) / 'agentverse-build.keychain-db'
    # Capture subprocess output and expose only a generic error if credential import fails.
    import secrets
    password = secrets.token_urlsafe(24)
    def run(command):
        result = subprocess.run(command, capture_output=True)
        if result.returncode:
            raise ValueError('macOS certificate import failed. Check the signing secrets.')
    with tempfile.TemporaryDirectory() as temporary:
        p12 = Path(temporary) / 'certificate.p12'
        p12.write_bytes(base64.b64decode(certificate))
        run(['security', 'create-keychain', '-p', password, str(keychain)])
        run(['security', 'unlock-keychain', '-p', password, str(keychain)])
        run(['security', 'import', str(p12), '-k', str(keychain), '-P', os.getenv('MACOS_SIGNING_PASSWORD', ''), '-T', '/usr/bin/codesign'])
        run(['security', 'set-key-partition-list', '-S', 'apple-tool:,apple:', '-s', '-k', password, str(keychain)])
        run(['security', 'list-keychains', '-d', 'user', '-s', str(keychain)])
    return keychain


def notarize(dmg):
    key = os.getenv('MACOS_NOTARY_KEY_P8')
    if key:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'AuthKey.p8'
            path.write_bytes(base64.b64decode(key))
            result = subprocess.run(['xcrun', 'notarytool', 'submit', str(dmg), '--key', str(path),
                '--key-id', os.environ['MACOS_NOTARY_KEY_ID'], '--issuer', os.environ['MACOS_NOTARY_ISSUER'], '--wait'], capture_output=True)
            if result.returncode:
                raise ValueError('Apple notarization failed. Check the API key secrets.')
        subprocess.run(['xcrun', 'stapler', 'staple', str(dmg)], check=True)
        return True
    profile = os.getenv('MACOS_NOTARY_PROFILE')
    if not profile:
        return False
    # Profile is preconfigured by the repository owner; credentials are not accepted through CLI output.
    result = subprocess.run(['xcrun', 'notarytool', 'submit', str(dmg), '--keychain-profile', profile, '--wait'], capture_output=True)
    if result.returncode:
        raise ValueError('Apple notarization failed. Check the notary profile.')
    subprocess.run(['xcrun', 'stapler', 'staple', str(dmg)], check=True)
    return True
