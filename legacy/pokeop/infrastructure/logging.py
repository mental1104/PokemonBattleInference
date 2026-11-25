import logging


def configure_logging(log_level: str | int = "INFO") -> None:
    """
    Configure application-wide logging.

    Parameters
    ----------
    log_level:
        Either a valid logging level string or logging level integer.
    """
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    resolved_level: int
    if isinstance(log_level, str):
        resolved_level = getattr(logging, log_level.upper(), logging.INFO)
    else:
        resolved_level = log_level

    logging.basicConfig(
        level=resolved_level,
        format="[SERVER]%(asctime)s %(filename)s [line:%(lineno)d] "
        "%(levelname)s %(message)s",
    )
