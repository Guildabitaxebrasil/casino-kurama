"""
Compilação de contratos Solidity para a EVM da KuramaChain.

Usa ``py-solc-x`` para baixar/rodar o ``solc``. Compilamos sempre com
``evmVersion: london`` porque a EVM da KuramaChain roda o fork London
(último fork com Proof of Work) — evitar PUSH0/opcodes de Shangai.
"""
import functools
from typing import Dict

import solcx

SOLC_VERSION = '0.8.21'
EVM_VERSION = 'london'


@functools.lru_cache(maxsize=1)
def ensure_solc() -> str:
    """Garante que o `solc` da versão alvo esteja instalado."""
    installed = {str(v) for v in solcx.get_installed_solc_versions()}
    if SOLC_VERSION not in installed:
        solcx.install_solc(SOLC_VERSION, show_progress=False)
    solcx.set_solc_version(SOLC_VERSION)
    return SOLC_VERSION


def compile_source(source: str, contract_name: str,
                   filename: str = None) -> Dict[str, object]:
    """
    Compila um contrato Solidity e retorna abi + bytecode.

    Args:
        source: Código-fonte Solidity.
        contract_name: Nome do contrato a extrair.
        filename: Nome do arquivo virtual (default: '<contract_name>.sol').

    Returns:
        ``{'abi': [...], 'bytecode': bytes, 'deployed_bytecode': bytes}``
    """
    ensure_solc()
    filename = filename or f'{contract_name}.sol'
    compiled = solcx.compile_standard(
        {
            'language': 'Solidity',
            'sources': {filename: {'content': source}},
            'settings': {
                'evmVersion': EVM_VERSION,
                # viaIR evita "Stack too deep" em contratos maiores (ex: Router)
                'viaIR': True,
                'optimizer': {'enabled': True, 'runs': 200},
                'outputSelection': {
                    '*': {'*': ['abi', 'evm.bytecode.object',
                                'evm.deployedBytecode.object']}
                },
            },
        },
        solc_version=SOLC_VERSION,
        allow_paths='.',
    )
    contract = compiled['contracts'][filename][contract_name]
    return {
        'abi': contract['abi'],
        'bytecode': bytes.fromhex(contract['evm']['bytecode']['object']),
        'deployed_bytecode': bytes.fromhex(
            contract['evm']['deployedBytecode']['object']
        ),
    }


def compile_file(path: str, contract_name: str) -> Dict[str, object]:
    """Compila um contrato a partir de um arquivo .sol."""
    with open(path, 'r', encoding='utf-8') as fh:
        return compile_source(fh.read(), contract_name, filename=path)


def compile_all(sources: Dict[str, str]) -> Dict[str, Dict[str, Dict[str, object]]]:
    """
    Compila vários arquivos Solidity de uma só vez (resolve ``import`` entre
    eles) e devolve o bytecode de TODOS os contratos.

    Útil para testes que precisam de vários contratos: uma única chamada ao
    ``solc`` compila o conjunto inteiro.

    Args:
        sources: mapa ``{'Nome.sol': 'código'}``. O import ``./X.sol``
            dentro de ``Y.sol`` resolve para a chave ``X.sol``.

    Returns:
        ``{'Nome.sol': {'Contrato': {'abi': [...], 'bytecode': bytes,
                                     'deployed_bytecode': bytes}}}``
    """
    ensure_solc()
    compiled = solcx.compile_standard(
        {
            'language': 'Solidity',
            'sources': {name: {'content': content}
                        for name, content in sources.items()},
            'settings': {
                'evmVersion': EVM_VERSION,
                # viaIR evita "Stack too deep" em contratos maiores (ex: Router)
                'viaIR': True,
                'optimizer': {'enabled': True, 'runs': 200},
                'outputSelection': {
                    '*': {'*': ['abi', 'evm.bytecode.object',
                                'evm.deployedBytecode.object']}
                },
            },
        },
        solc_version=SOLC_VERSION,
        allow_paths='.',
    )
    return {
        filename: {
            name: {
                'abi': contract['abi'],
                'bytecode': bytes.fromhex(contract['evm']['bytecode']['object']),
                'deployed_bytecode': bytes.fromhex(
                    contract['evm']['deployedBytecode']['object']
                ),
            }
            for name, contract in contracts.items()
        }
        for filename, contracts in compiled['contracts'].items()
    }


def compile_contracts(sources: Dict[str, str], source_key: str,
                      contract_name: str) -> Dict[str, object]:
    """
    Compila vários arquivos Solidity juntos (resolve ``import`` entre eles)
    e extrai um único contrato.

    Args:
        sources: mapa ``{'Nome.sol': 'código'}``.
        source_key: chave do arquivo que contém o contrato alvo.
        contract_name: nome do contrato a extrair.

    Returns:
        ``{'abi': [...], 'bytecode': bytes, 'deployed_bytecode': bytes}``
    """
    return compile_all(sources)[source_key][contract_name]
