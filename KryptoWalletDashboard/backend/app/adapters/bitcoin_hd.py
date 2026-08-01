from bitcoinlib.keys import HDKey


def derive_address(extended_key: str, chain: int, index: int) -> str:
    """Derive the Bitcoin address at path `{chain}/{index}` relative to the
    given extended public key (xpub/ypub/zpub), in the address format
    implied by that key's own prefix (legacy/P2SH-segwit/native-segwit
    respectively). `chain` is 0 for the receive chain, 1 for change."""
    # Note: bitcoinlib does not validate the base58check checksum on import --
    # a corrupted or typo'd extended key silently parses and derives a
    # plausible-but-wrong address rather than raising. No defense added here
    # (matches this codebase's style of trusting config input); documented
    # for the user in the BITCOIN_XPUBS setup instructions instead.
    key = HDKey(import_key=extended_key)
    child = key.key_for_path(f"{chain}/{index}")
    return child.address()
