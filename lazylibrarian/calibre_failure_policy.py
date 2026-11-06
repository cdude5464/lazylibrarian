"""Recognize a witnessed Calibre subprocess crash without relaxing content policy."""
import re


def calibre_command_crashed(reason):
    if not isinstance(reason, str):
        return False
    reason = re.sub(r'^destination:\s*', '', reason, flags=re.I)
    return bool(re.fullmatch(r'calibredb rc -11 from /(?:[^/\r\n]+/)*calibredb', reason))
