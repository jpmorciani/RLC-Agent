"""
South America Data Collectors

Collectors for agricultural data from South American sources:
- Brazil: CONAB, Comex Stat, IBGE, ABIOVE, IMEA, COMEXSTAT
- Argentina: MAGYP, Buenos Aires Grain Exchange
- Paraguay, Uruguay, Colombia: Trade data
"""

from .brazil_agent import BrazilComexStatAgent
from .conab_collector import CONABCollector, CONABConfig
from .conab_soybean_agent import (
    CONABSoybeanAgent,
    CONABSoybeanConfig,
    CollectionResult
)
from .comexstat_collector import (
    COMEXSTATCollector,
    COMEXSTATConfig,
    COMEXSTAT_AGRICULTURAL_PRODUCTS
)

__all__ = [
    # Brazil - COMEXSTAT (Trade Statistics)
    'COMEXSTATCollector',
    'COMEXSTATConfig',
    'COMEXSTAT_AGRICULTURAL_PRODUCTS',
    # Brazil - Other
    'BrazilComexStatAgent',
    'CONABCollector',
    'CONABConfig',
    'CONABSoybeanAgent',
    'CONABSoybeanConfig',
    'CollectionResult',
]
