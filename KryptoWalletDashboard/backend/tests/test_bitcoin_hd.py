from app.adapters.bitcoin_hd import derive_address

# BIP32 official spec test vector 1 master public key -- well-known, public
# test data from the BIP32 specification itself, not a real wallet.
# https://github.com/bitcoin/bips/blob/master/bip-0032.mediawiki
TEST_XPUB = "xpub661MyMwAqRbcFtXgS5sYJABqqG9YLmC4Q1Rdap9gSE8NqtwybGhePY2gZ29ESFjqJoCu1Rupje8YtGqsefD265TMg7usUDFdp6W1EGMcet8"


def test_derives_a_legacy_p2pkh_address_from_an_xpub():
    address = derive_address(TEST_XPUB, chain=0, index=0)

    assert address.startswith("1")


def test_derivation_is_deterministic():
    address_a = derive_address(TEST_XPUB, chain=0, index=0)
    address_b = derive_address(TEST_XPUB, chain=0, index=0)

    assert address_a == address_b


def test_different_indexes_produce_different_addresses():
    address_0 = derive_address(TEST_XPUB, chain=0, index=0)
    address_1 = derive_address(TEST_XPUB, chain=0, index=1)

    assert address_0 != address_1


def test_receive_and_change_chains_produce_different_addresses():
    receive_address = derive_address(TEST_XPUB, chain=0, index=0)
    change_address = derive_address(TEST_XPUB, chain=1, index=0)

    assert receive_address != change_address


def test_ypub_produces_a_p2sh_segwit_address():
    # Convert the same underlying key material to a ypub (BIP49) test
    # fixture using bitcoinlib itself, rather than hand-writing/guessing a
    # ypub string.
    from bitcoinlib.keys import HDKey

    k = HDKey(import_key=TEST_XPUB)
    ypub = k.public_master(witness_type="p2sh-segwit").wif()

    address = derive_address(ypub, chain=0, index=0)

    assert address.startswith("3")


def test_zpub_produces_a_native_segwit_address():
    from bitcoinlib.keys import HDKey

    k = HDKey(import_key=TEST_XPUB)
    zpub = k.public_master(witness_type="segwit").wif()

    address = derive_address(zpub, chain=0, index=0)

    assert address.startswith("bc1")
