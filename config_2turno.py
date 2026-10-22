from enum import Enum
from dataclasses import dataclass
from typing import Dict, List

"""
CONFIGURAÇÕES OFICIAIS DO TSE - 2º TURNO ELEIÇÕES GERAIS 2026
------------------------------------------------------------
Este arquivo adapta toda a malha de conexão para o 2º Turno:
- Turno fixado em 2.
- Cargos reduzidos exclusivamente a Presidente (c0001) e Governador (c0003).
- Governadores restritos aos 6 estados com 2º turno ativo: AC, AM, DF, ES, RN, TO.
"""

class Environment(Enum):
    SIMULATED = "simulado2026"
    OFFICIAL = "oficial"

@dataclass
class TSEConfig2T:
    env: Environment
    env_path: str
    base_url: str
    cycle: str
    turno: int
    pleito: str
    eleicao_federal: str
    eleicao_estadual: str

# Configurações do Ambiente Simulado (Testes / Homologação 2º Turno)
SIMULADO_2TURNO_CONFIG = TSEConfig2T(
    env=Environment.SIMULATED,
    env_path="simulado/simulado2026",
    base_url="https://resultados-sim.tse.jus.br",
    cycle="ele2026",
    turno=2,
    pleito="17801",
    eleicao_federal="21271",   # Código de 2º turno no simulado TSE
    eleicao_estadual="21273"    # Código de 2º turno no simulado TSE
)

# Configurações do Ambiente Oficial (Produção - Domingo de 2º Turno)
# Nota: No TSE, as eleições de 2º turno usam o identificador sequencial da eleição federal/estadual
OFICIAL_2TURNO_CONFIG = TSEConfig2T(
    env=Environment.OFFICIAL,
    env_path="oficial",
    base_url="https://resultados.tse.jus.br",
    cycle="ele2026",
    turno=2,
    pleito="3220",
    eleicao_federal="6258",    # Código do 2º turno Presidente no TSE
    eleicao_estadual="6260"     # Código do 2º turno Governador no TSE
)

# Cargos Ativos no 2º Turno (Eliminados Senador e Deputados)
CARGOS_2TURNO: Dict[str, str] = {
    "c0001": "Presidente",
    "c0003": "Governador"
}

# Unidades Federativas com 2º Turno para GOVERNADOR
UFS_GOVERNADOR_2TURNO: List[str] = [
    "AC", "AM", "DF", "ES", "RN", "TO"
]

# Unidades Federativas para PRESIDENTE (Brasil inteiro + Exterior)
UFS_PRESIDENTE_2TURNO: List[str] = [
    "AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA",
    "MG", "MS", "MT", "PA", "PB", "PE", "PI", "PR", "RJ", "RN",
    "RO", "RR", "RS", "SC", "SE", "SP", "TO", "BR"
]

# Teto de requisições por segundo
MAX_REQ_PER_SEC = 60
