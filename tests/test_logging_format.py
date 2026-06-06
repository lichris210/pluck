"""Tests that the global log format (WHERE + WHAT) is configured and applied."""

import logging

from api.main import LOG_FORMAT, configure_logging


def test_log_format_includes_where_and_what():
    """The format renders level, name:funcName:lineno (WHERE), and message (WHAT)."""
    formatter = logging.Formatter(LOG_FORMAT)
    record = logging.LogRecord(
        name="pluck.sample", level=logging.INFO, pathname=__file__, lineno=42,
        msg="decided: actor=%s", args=("apify/x",), exc_info=None, func="my_func",
    )
    out = formatter.format(record)

    assert "[INFO]" in out
    assert "pluck.sample:my_func:42" in out          # WHERE
    assert "decided: actor=apify/x" in out           # WHAT


def test_configure_logging_attaches_single_stdout_handler():
    """A tagged stdout handler is attached, with our format, and never duplicated."""
    configure_logging()
    configure_logging()  # idempotent — must not stack handlers

    root = logging.getLogger()
    pluck_handlers = [h for h in root.handlers if getattr(h, "_pluck", False)]
    assert len(pluck_handlers) == 1
    assert pluck_handlers[0].formatter._fmt == LOG_FORMAT


def test_configure_logging_respects_log_level(monkeypatch):
    """LOG_LEVEL drives the root level; default is INFO."""
    root = logging.getLogger()
    original = root.level
    try:
        monkeypatch.setenv("LOG_LEVEL", "WARNING")
        configure_logging()
        assert root.level == logging.WARNING
    finally:
        # Restore the default INFO config so other tests' caplog is unaffected.
        monkeypatch.delenv("LOG_LEVEL", raising=False)
        configure_logging()
        root.setLevel(original)


def test_info_logs_propagate_to_caplog(caplog):
    """Our INFO logs are capturable via caplog (propagation intact)."""
    logger = logging.getLogger("pluck.caplog_check")
    with caplog.at_level(logging.INFO, logger="pluck.caplog_check"):
        logger.info("hello %s", "world")
    assert "hello world" in caplog.text
