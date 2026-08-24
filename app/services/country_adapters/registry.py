from .base import CountryAdapter
from .india import IndiaAdapter
from .kenya import KenyaAdapter
from .uganda import UgandaAdapter
from .tanzania import TanzaniaAdapter
from .ethiopia import EthiopiaAdapter
from .south_africa import SouthAfricaAdapter

_REGISTRY: dict[str, CountryAdapter] = {
    "IND": IndiaAdapter(),
    "KEN": KenyaAdapter(),
    "UGA": UgandaAdapter(),
    "TZA": TanzaniaAdapter(),
    "ETH": EthiopiaAdapter(),
    "ZAF": SouthAfricaAdapter(),
}


def get_adapter(country_id: str) -> CountryAdapter:
    if country_id not in _REGISTRY:
        raise ValueError(f"No CountryAdapter registered for {country_id}")
    return _REGISTRY[country_id]


def all_country_ids() -> list[str]:
    return list(_REGISTRY.keys())
