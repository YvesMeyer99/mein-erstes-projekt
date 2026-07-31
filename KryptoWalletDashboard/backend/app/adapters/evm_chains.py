from dataclasses import dataclass


@dataclass(frozen=True)
class EvmChainConfig:
    chain_id: int
    chain_name: str
    native_asset: str


EVM_CHAINS: list[EvmChainConfig] = [
    EvmChainConfig(chain_id=1, chain_name="ethereum", native_asset="ETH"),
    EvmChainConfig(chain_id=10, chain_name="optimism", native_asset="ETH"),
    EvmChainConfig(chain_id=56, chain_name="bsc", native_asset="BNB"),
    EvmChainConfig(chain_id=137, chain_name="polygon", native_asset="MATIC"),
    EvmChainConfig(chain_id=8453, chain_name="base", native_asset="ETH"),
    EvmChainConfig(chain_id=42161, chain_name="arbitrum", native_asset="ETH"),
]
