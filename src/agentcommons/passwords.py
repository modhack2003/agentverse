"""Password storage for local installations; plaintext passwords never enter config."""

import hashlib
import hmac
import secrets


def hash_password(password):
    if not 12 <= len(password) <= 256:
        raise ValueError('Use a password containing 12 to 256 characters.')
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f'scrypt${salt}${digest}'


def verify_password(password, encoded):
    try:
        kind, salt, digest = encoded.split('$')
        if kind != 'scrypt' or len(salt) != 32 or len(digest) != 128 or len(password) > 256:
            return False
        computed = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
        return hmac.compare_digest(computed, digest)
    except (ValueError, TypeError):
        return False
