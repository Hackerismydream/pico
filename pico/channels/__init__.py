"""Chat channels module.

Public contract surface — import channel types from here, not from internal
modules, so the file layout can change without breaking callers.
"""

from pico.channels.base import ChannelBase
from pico.channels.contract import (
    Capabilities,
    Channel,
    ChannelSpec,
    SupportsLogin,
    SupportsStreaming,
)
from pico.channels.manager import ChannelManager

# Public surface = the contract types adapters implement. Validation helpers
# (capability_violations) live in channels.contract.
__all__ = [
    "Capabilities",
    "Channel",
    "ChannelBase",
    "ChannelManager",
    "ChannelSpec",
    "SupportsLogin",
    "SupportsStreaming",
]
