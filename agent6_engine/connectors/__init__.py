from .base import Connector, ClaimDict
from .gleif import GLEIFConnector
from .vies import VIESConnector
from .companies_house import CompaniesHouseConnector
from .wikidata import WikidataConnector

REGISTRY = {c.name: c for c in [GLEIFConnector, VIESConnector,
                                CompaniesHouseConnector, WikidataConnector]}
