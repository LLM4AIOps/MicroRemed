from argparse import Namespace
from typing import Optional

_config: Optional[Namespace] = None


def set_config(args: Namespace):
    global _config
    _config = args


def get_config() -> Namespace:
    if _config is None:
        raise RuntimeError("Configuration not initialized. Call set_config() first.")
    return _config
