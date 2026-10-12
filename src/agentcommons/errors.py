"""Actionable invocation errors without credentials or terminal control sequences."""
import os
import re


def safe_error(error, private_values=()):
    text = str(error)
    values = list(private_values) + [value for key, value in os.environ.items()
                                    if any(word in key.upper() for word in ('TOKEN', 'SECRET', 'PASSWORD', 'API_KEY'))]
    for value in sorted((v for v in values if isinstance(v, str) and len(v) >= 4), key=len, reverse=True):
        text = text.replace(value, '[redacted]')
    text = re.sub(r'(?i)(bearer\s+)[\w.\-]+', r'\1[redacted]', text)
    text = re.sub(r'(?i)((?:api[_-]?key|token|password|secret)[\s"\x27]*[:=][\s"\x27]*)[^\s,\x27"&}]+', r'\1[redacted]', text)
    text = re.sub(r'\b(?:sk-[\w-]{12,}|AIza[\w-]{20,})', '[redacted]', text)
    text = re.sub(r'\b(?:ac|acr|web)_[\w.\-]{12,}', '[redacted]', text)
    text = re.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', text)
    text = ''.join(character for character in text if character in '\n\t' or ord(character) >= 32)
    return text[:1200] or 'The invocation was interrupted.'
