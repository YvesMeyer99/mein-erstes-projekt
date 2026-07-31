from app.adapters.evm_chains import EVM_CHAINS


def test_evm_chains_covers_all_six_supported_chains():
    names = {chain.chain_name for chain in EVM_CHAINS}
    assert names == {"ethereum", "optimism", "bsc", "polygon", "base", "arbitrum"}


def test_evm_chains_have_unique_chain_ids():
    chain_ids = [chain.chain_id for chain in EVM_CHAINS]
    assert len(chain_ids) == len(set(chain_ids))


def test_ethereum_chain_config_matches_etherscan_v2_chain_id():
    ethereum = next(c for c in EVM_CHAINS if c.chain_name == "ethereum")
    assert ethereum.chain_id == 1
    assert ethereum.native_asset == "ETH"
