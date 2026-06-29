from .base import Connector, ClaimDict
from .gleif import GLEIFConnector
from .vies import VIESConnector
from .companies_house import CompaniesHouseConnector
from .wikidata import WikidataConnector
from .impressum import ImpressumConnector
from .sec_edgar import SECEdgarConnector
from .sam_gov import SAMGovConnector
from .patentsview import PatentsViewConnector
from .fcc_id import FCCIDConnector

# EU/DACH-Primärquellen (Discovery + Verifikation)
EU_CONNECTORS = [GLEIFConnector, CompaniesHouseConnector, WikidataConnector, ImpressumConnector]
# US-Primärquellen
US_CONNECTORS = [GLEIFConnector, SECEdgarConnector, SAMGovConnector, PatentsViewConnector, FCCIDConnector]
# Validatoren (kein Discovery)
VALIDATORS = [VIESConnector]

REGISTRY = {c.name: c for c in EU_CONNECTORS + US_CONNECTORS + VALIDATORS}
