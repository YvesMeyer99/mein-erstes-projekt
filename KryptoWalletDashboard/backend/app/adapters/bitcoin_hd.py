from bitcoinlib.keys import HDKey


def derive_address(extended_key: str, chain: int, index: int) -> str:
    """Derive the Bitcoin address at path `{chain}/{index}` relative to the
    given extended public key (xpub/ypub/zpub), in the address format
    implied by that key's own prefix (legacy/P2SH-segwit/native-segwit
    respectively). `chain` is 0 for the receive chain, 1 for change."""
    key = HDKey(import_key=extended_key)
    child = key.key_for_path(f"{chain}/{index}")
    return child.address()
