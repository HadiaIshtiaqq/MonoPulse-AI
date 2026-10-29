"""Keeping credentials out of everything MonoPlus writes or shows: logs, error messages on
screen, errors saved with posts, jobs and research, and MCP replies.

Secrets are first kept out of places they could leak from (tokens travel in headers, never in
URLs). This is the second line: anything that turns an exception or a response into text runs it
through redact(), which hides every configured key and anything shaped like a credential
("access_token=…", "Bearer …"), even ones MonoPlus doesn't know about.
"""
from __future__ import annotations

import logging
import os
import re

from . import config

HIDDEN = "[hidden]"
# Settings whose values are credentials. Read fresh each time, so a key set while running is covered.
SECRET_SETTINGS = (
    "NEBIUS_API_KEY", "TAVILY_API_KEY", "PEXELS_API_KEY", "MONOPLUS_ACCESS_KEY", "ACCESS_KEY", "META_ACCESS_TOKEN",
    "LINKEDIN_ACCESS_TOKEN", "X_USER_ACCESS_TOKEN", "PUBLISH_WEBHOOK_URL", "AWS_SECRET_ACCESS_KEY", "AWS_ACCESS_KEY_ID",
    "AWS_SESSION_TOKEN", "MCP_TOKEN",
)
SHAPES = [
    # key=value pairs in URLs, form bodies and messages
    (re.compile(r"(?i)\b(access_token|refresh_token|id_token|client_secret|api[_-]?key|apikey|token|key|secret|password|"
                r"signature|sig|x-amz-signature|x-amz-credential|x-amz-security-token)=([^&\s'\"<>]+)"), r"\1=" + HIDDEN),
    # Authorization headers and their echoes
    (re.compile(r"(?i)\b(bearer|basic|oauth)\s+[A-Za-z0-9._~+/=\-]{8,}"), r"\1 " + HIDDEN),
    (re.compile(r"(?i)(['\"]?(?:authorization|x-access-key|x-api-key)['\"]?\s*[:=]\s*['\"]?)[^'\",}\s]+"), r"\1" + HIDDEN),
    # well-known key formats
    (re.compile(r"\b(sk-[A-Za-z0-9_\-]{16,}|tvly-[A-Za-z0-9_\-]{10,}|EAA[A-Za-z0-9]{30,}|AKIA[A-Z0-9]{16}|ghp_[A-Za-z0-9]{30,}|"
                r"xox[abpr]-[A-Za-z0-9\-]{10,}|AIza[A-Za-z0-9_\-]{30,})\b"), HIDDEN),
]


def known_secrets() -> list[str]:
    values = set()
    for name in SECRET_SETTINGS:
        for v in (getattr(config, name, None), os.environ.get(name)):
            if isinstance(v, str) and len(v.strip()) >= 6:
                values.add(v.strip())
    return sorted(values, key=len, reverse=True)  # longest first, so a key inside a URL goes whole


def redact(text: object) -> str:
    """The text with every credential replaced by [hidden]."""
    s = text if isinstance(text, str) else str(text)
    if not s:
        return s
    for secret in known_secrets():
        if secret in s:
            s = s.replace(secret, HIDDEN)
    for rx, repl in SHAPES:
        s = rx.sub(repl, s)
    return s


_installed = False


def install_log_redaction() -> None:
    """Redact every log record as it's created, whoever logs it: MonoPlus, uvicorn's access log
    (which prints each request's address), httpx, openai. Done at creation because a filter on
    one logger misses records that other loggers' handlers write."""
    global _installed
    if _installed:
        return
    old = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = old(*args, **kwargs)
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - a malformed record: leave it for logging to report
            return record
        clean = redact(message)
        if clean != message:
            if isinstance(record.args, tuple):  # keep the shape formatters expect, with each value cleaned
                record.args = tuple(redact(a) if isinstance(a, str) else a for a in record.args)
                record.msg = redact(record.msg) if isinstance(record.msg, str) else record.msg
                try:
                    if record.getMessage() != clean:
                        raise ValueError
                except Exception:  # noqa: BLE001 - cleaning per value didn't add up: fall back to the whole line
                    record.msg, record.args = clean, ()
            else:
                record.msg, record.args = clean, ()
        if record.exc_info and record.exc_info[1] is not None:
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return record

    logging.setLogRecordFactory(factory)
    _installed = True
