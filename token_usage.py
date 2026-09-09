def log_token_usage(fn):
    """Compatibility decorator for environments that do not define the original token logger."""

    def wrapper(*args, **kwargs):
        return fn(*args, **kwargs)

    wrapper.__name__ = getattr(fn, "__name__", "wrapped")
    return wrapper
