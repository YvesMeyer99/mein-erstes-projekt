import requests

from app.adapters.bitcoin import API_BASE
from app.adapters.bitcoin_hd import derive_address

GAP_LIMIT = 20


def _address_is_used(address: str) -> bool:
    response = requests.get(f"{API_BASE}/address/{address}", timeout=10)
    response.raise_for_status()
    data = response.json()
    chain_count = data.get("chain_stats", {}).get("tx_count", 0)
    mempool_count = data.get("mempool_stats", {}).get("tx_count", 0)
    return (chain_count + mempool_count) > 0


def _scan_chain(extended_key: str, chain: int) -> set[str]:
    used: set[str] = set()
    unused_streak = 0
    index = 0
    while unused_streak < GAP_LIMIT:
        address = derive_address(extended_key, chain, index)
        if _address_is_used(address):
            used.add(address)
            unused_streak = 0
        else:
            unused_streak += 1
        index += 1
    return used


def discover_used_addresses(extended_key: str) -> set[str]:
    """Scan both the receive (chain 0) and change (chain 1) derivation
    chains of an HD wallet's extended public key for used addresses,
    stopping each chain after GAP_LIMIT consecutive unused addresses --
    the same gap-limit convention essentially every wallet uses."""
    return _scan_chain(extended_key, 0) | _scan_chain(extended_key, 1)
