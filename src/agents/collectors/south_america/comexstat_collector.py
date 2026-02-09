"""
COMEXSTAT Collector (Brazilian Foreign Trade Statistics)

Collects Brazilian export and import data from COMEXSTAT (MDIC):
- Agricultural commodities trade flows (soybeans, corn, wheat, cotton, sugar, coffee)
- Monthly export/import data by country and product
- NCM (Mercosur Common Nomenclature) code-level detail
- Historical data from 1997 to present

Data source:
- Portal: https://comexstat.mdic.gov.br
- API: https://api-comexstat.mdic.gov.br

No API key required - public data via REST API.
Monthly data releases with ~30 day lag.
"""

import logging
import json
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any, Union
from io import StringIO

from ...base import (
    BaseCollector,
    CollectorConfig,
    CollectorResult,
    DataFrequency,
    AuthType
)

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

logger = logging.getLogger(__name__)


# =============================================================================
# COMEXSTAT CONFIGURATION
# =============================================================================

# Agricultural commodity NCM codes (8-digit Brazilian Mercosur classification)
# These map to HS codes used internationally
COMEXSTAT_AGRICULTURAL_PRODUCTS = {
    # SOYBEANS
    'soybeans': {
        'ncm_codes': ['12019000', '12011000', '12010010', '12010090'],
        'sh6_codes': ['120190', '120110'],
        'sh4_codes': ['1201'],
        'chapter': '12',
        'description': 'Soybeans, whether or not broken',
        'unit': 'KG'
    },
    'soybean_meal': {
        'ncm_codes': ['23040010', '23040090'],
        'sh6_codes': ['230400'],
        'sh4_codes': ['2304'],
        'chapter': '23',
        'description': 'Soybean oil-cake and meal',
        'unit': 'KG'
    },
    'soybean_oil': {
        'ncm_codes': ['15071000', '15079000', '15079011', '15079019', '15079090'],
        'sh6_codes': ['150710', '150790'],
        'sh4_codes': ['1507'],
        'chapter': '15',
        'description': 'Soybean oil and fractions',
        'unit': 'KG'
    },

    # CORN
    'corn': {
        'ncm_codes': ['10059010', '10059090', '10051000'],
        'sh6_codes': ['100590', '100510'],
        'sh4_codes': ['1005'],
        'chapter': '10',
        'description': 'Maize (corn)',
        'unit': 'KG'
    },

    # WHEAT
    'wheat': {
        'ncm_codes': ['10019100', '10019900', '10011100', '10011900'],
        'sh6_codes': ['100191', '100199', '100111', '100119'],
        'sh4_codes': ['1001'],
        'chapter': '10',
        'description': 'Wheat and meslin',
        'unit': 'KG'
    },

    # COTTON
    'cotton': {
        'ncm_codes': ['52010000', '52010010', '52010020', '52010090'],
        'sh6_codes': ['520100'],
        'sh4_codes': ['5201'],
        'chapter': '52',
        'description': 'Cotton, not carded or combed',
        'unit': 'KG'
    },

    # SUGAR
    'sugar_raw': {
        'ncm_codes': ['17011300', '17011400'],
        'sh6_codes': ['170113', '170114'],
        'sh4_codes': ['1701'],
        'chapter': '17',
        'description': 'Raw cane sugar',
        'unit': 'KG'
    },
    'sugar_refined': {
        'ncm_codes': ['17019900', '17019100'],
        'sh6_codes': ['170199', '170191'],
        'sh4_codes': ['1701'],
        'chapter': '17',
        'description': 'Refined sugar',
        'unit': 'KG'
    },

    # COFFEE
    'coffee': {
        'ncm_codes': ['09011110', '09011190', '09011200', '09012100', '09012200'],
        'sh6_codes': ['090111', '090112', '090121', '090122'],
        'sh4_codes': ['0901'],
        'chapter': '09',
        'description': 'Coffee, roasted or not',
        'unit': 'KG'
    },

    # BEEF
    'beef_fresh': {
        'ncm_codes': ['02013000', '02023000', '02011000', '02012000'],
        'sh6_codes': ['020130', '020230', '020110', '020120'],
        'sh4_codes': ['0201', '0202'],
        'chapter': '02',
        'description': 'Fresh or chilled beef',
        'unit': 'KG'
    },
    'beef_frozen': {
        'ncm_codes': ['02022000', '02023000'],
        'sh6_codes': ['020220', '020230'],
        'sh4_codes': ['0202'],
        'chapter': '02',
        'description': 'Frozen beef',
        'unit': 'KG'
    },

    # CHICKEN
    'chicken': {
        'ncm_codes': ['02071200', '02071400', '02071100', '02071300'],
        'sh6_codes': ['020712', '020714', '020711', '020713'],
        'sh4_codes': ['0207'],
        'chapter': '02',
        'description': 'Chicken meat and edible offal',
        'unit': 'KG'
    },

    # PORK
    'pork': {
        'ncm_codes': ['02031200', '02031900', '02032200', '02032900'],
        'sh6_codes': ['020312', '020319', '020322', '020329'],
        'sh4_codes': ['0203'],
        'chapter': '02',
        'description': 'Swine meat',
        'unit': 'KG'
    },

    # ORANGE JUICE
    'orange_juice': {
        'ncm_codes': ['20091100', '20091200', '20091900'],
        'sh6_codes': ['200911', '200912', '200919'],
        'sh4_codes': ['2009'],
        'chapter': '20',
        'description': 'Orange juice',
        'unit': 'KG'
    },

    # ETHANOL
    'ethanol': {
        'ncm_codes': ['22071000', '22072010', '22072020'],
        'sh6_codes': ['220710', '220720'],
        'sh4_codes': ['2207'],
        'chapter': '22',
        'description': 'Ethyl alcohol (ethanol)',
        'unit': 'LITERS'
    },

    # CELLULOSE/PULP
    'cellulose': {
        'ncm_codes': ['47032100', '47032900', '47031100', '47031900'],
        'sh6_codes': ['470321', '470329', '470311', '470319'],
        'sh4_codes': ['4703'],
        'chapter': '47',
        'description': 'Chemical wood pulp',
        'unit': 'KG'
    },
}

# Major trading partners for Brazil agricultural exports
BRAZIL_TRADE_PARTNERS = {
    'CN': 'China',
    'US': 'United States',
    'AR': 'Argentina',
    'NL': 'Netherlands',
    'ES': 'Spain',
    'DE': 'Germany',
    'JP': 'Japan',
    'KR': 'South Korea',
    'IT': 'Italy',
    'FR': 'France',
    'GB': 'United Kingdom',
    'BE': 'Belgium',
    'TH': 'Thailand',
    'VN': 'Vietnam',
    'EG': 'Egypt',
    'IR': 'Iran',
    'SA': 'Saudi Arabia',
    'AE': 'United Arab Emirates',
    'RU': 'Russia',
    'IN': 'India',
    'MX': 'Mexico',
    'CL': 'Chile',
    'CO': 'Colombia',
    'ID': 'Indonesia',
    'MY': 'Malaysia',
    'PH': 'Philippines',
    'HK': 'Hong Kong',
    'TW': 'Taiwan',
    'SG': 'Singapore',
}

# Brazilian states (UF codes)
BR_STATES = {
    'AC': 'Acre', 'AL': 'Alagoas', 'AP': 'Amapá', 'AM': 'Amazonas',
    'BA': 'Bahia', 'CE': 'Ceará', 'DF': 'Distrito Federal',
    'ES': 'Espírito Santo', 'GO': 'Goiás', 'MA': 'Maranhão',
    'MT': 'Mato Grosso', 'MS': 'Mato Grosso do Sul', 'MG': 'Minas Gerais',
    'PA': 'Pará', 'PB': 'Paraíba', 'PR': 'Paraná', 'PE': 'Pernambuco',
    'PI': 'Piauí', 'RJ': 'Rio de Janeiro', 'RN': 'Rio Grande do Norte',
    'RS': 'Rio Grande do Sul', 'RO': 'Rondônia', 'RR': 'Roraima',
    'SC': 'Santa Catarina', 'SP': 'São Paulo', 'SE': 'Sergipe',
    'TO': 'Tocantins'
}


@dataclass
class COMEXSTATConfig(CollectorConfig):
    """COMEXSTAT specific configuration"""
    source_name: str = "COMEXSTAT"
    source_url: str = "https://api-comexstat.mdic.gov.br"
    auth_type: AuthType = AuthType.NONE
    frequency: DataFrequency = DataFrequency.MONTHLY

    # API endpoints
    api_base: str = "https://api-comexstat.mdic.gov.br"
    general_endpoint: str = "/general"
    cities_endpoint: str = "/cities"
    filters_endpoint: str = "/general/filters"

    # Default commodities to track
    commodities: List[str] = field(default_factory=lambda: [
        'soybeans', 'soybean_meal', 'soybean_oil', 'corn', 'wheat',
        'cotton', 'sugar_raw', 'coffee', 'beef_fresh', 'chicken'
    ])

    # Rate limiting - be respectful
    rate_limit_per_minute: int = 30
    timeout: int = 120

    # Data range defaults
    default_years_back: int = 5


class COMEXSTATCollector(BaseCollector):
    """
    Collector for Brazilian foreign trade data from COMEXSTAT.

    COMEXSTAT is Brazil's official foreign trade statistics system managed by
    the Ministry of Development, Industry, Commerce and Services (MDIC).

    Key data:
    - Monthly export/import volumes and values by NCM/HS code
    - Trade flows by destination/origin country
    - Data by Brazilian state of origin
    - Historical series from 1997 to present

    No API key required.
    """

    def __init__(self, config: COMEXSTATConfig = None):
        config = config or COMEXSTATConfig()
        super().__init__(config)
        self.config: COMEXSTATConfig = config

        # Set up headers for API requests
        self.session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        })

    def get_table_name(self) -> str:
        return "comexstat_trade_raw"

    def fetch_data(
        self,
        start_date: date = None,
        end_date: date = None,
        flow: str = "export",
        commodities: List[str] = None,
        **kwargs
    ) -> CollectorResult:
        """
        Fetch trade data from COMEXSTAT API.

        Args:
            start_date: Start date for data range
            end_date: End date for data range (default: most recent available)
            flow: 'export' or 'import'
            commodities: List of commodity keys to fetch (from COMEXSTAT_AGRICULTURAL_PRODUCTS)

        Returns:
            CollectorResult with fetched data
        """
        # Set defaults
        if end_date is None:
            # Data typically available with 1-2 month lag
            end_date = date.today().replace(day=1) - timedelta(days=1)

        if start_date is None:
            start_date = date(end_date.year - 1, 1, 1)

        commodities = commodities or self.config.commodities

        self.logger.info(
            f"Fetching {flow} data from {start_date} to {end_date} "
            f"for {len(commodities)} commodities"
        )

        all_records = []
        warnings = []
        errors = []

        # Fetch data for each commodity
        for commodity in commodities:
            if commodity not in COMEXSTAT_AGRICULTURAL_PRODUCTS:
                warnings.append(f"Unknown commodity: {commodity}")
                continue

            product_info = COMEXSTAT_AGRICULTURAL_PRODUCTS[commodity]

            try:
                result = self._fetch_commodity_data(
                    commodity=commodity,
                    product_info=product_info,
                    flow=flow,
                    start_date=start_date,
                    end_date=end_date
                )

                if result:
                    all_records.extend(result)
                    self.logger.info(f"  {commodity}: {len(result)} records")
                else:
                    warnings.append(f"{commodity}: No data returned")

            except Exception as e:
                self.logger.error(f"Error fetching {commodity}: {e}")
                errors.append(f"{commodity}: {str(e)}")

        # Convert to DataFrame if pandas available
        if PANDAS_AVAILABLE and all_records:
            result_df = pd.DataFrame(all_records)
        else:
            result_df = all_records

        return CollectorResult(
            success=len(all_records) > 0,
            source=self.config.source_name,
            records_fetched=len(all_records),
            data=result_df,
            period_start=start_date.isoformat() if start_date else None,
            period_end=end_date.isoformat() if end_date else None,
            data_as_of=datetime.now().isoformat(),
            warnings=warnings,
            error_message="; ".join(errors) if errors else None
        )

    def _fetch_commodity_data(
        self,
        commodity: str,
        product_info: Dict,
        flow: str,
        start_date: date,
        end_date: date
    ) -> List[Dict]:
        """
        Fetch data for a specific commodity from COMEXSTAT API.
        """
        records = []

        # Build API request payload
        # Format dates as YYYY-MM
        from_period = start_date.strftime("%Y-%m")
        to_period = end_date.strftime("%Y-%m")

        # Build filter for NCM codes
        ncm_codes = product_info['ncm_codes']

        # API request body
        request_body = {
            "flow": flow,
            "monthDetail": True,
            "period": {
                "from": from_period,
                "to": to_period
            },
            "filters": [
                {
                    "filter": "ncm",
                    "values": ncm_codes
                }
            ],
            "details": ["country", "state"],
            "metrics": ["metricFOB", "metricKG", "metricStatistic"]
        }

        # Make API request
        url = f"{self.config.api_base}{self.config.general_endpoint}"

        response, error = self._make_request(
            url=url,
            method="POST",
            json_data=request_body,
            timeout=self.config.timeout
        )

        if error:
            self.logger.error(f"API request failed: {error}")
            return records

        if response.status_code != 200:
            self.logger.error(f"API returned {response.status_code}: {response.text[:500]}")
            return records

        # Parse response
        try:
            data = response.json()

            if isinstance(data, dict) and 'data' in data:
                raw_records = data['data']
            elif isinstance(data, list):
                raw_records = data
            else:
                self.logger.warning(f"Unexpected response format: {type(data)}")
                return records

            # Transform records
            for raw in raw_records:
                record = self._transform_record(raw, commodity, product_info, flow)
                if record:
                    records.append(record)

        except json.JSONDecodeError as e:
            self.logger.error(f"JSON parse error: {e}")
        except Exception as e:
            self.logger.error(f"Error processing response: {e}")

        return records

    def _transform_record(
        self,
        raw: Dict,
        commodity: str,
        product_info: Dict,
        flow: str
    ) -> Optional[Dict]:
        """
        Transform raw API record to standardized format.
        """
        try:
            # Extract year and month
            year = raw.get('coAno') or raw.get('year') or raw.get('ano')
            month = raw.get('coMes') or raw.get('month') or raw.get('mes')

            # Get country info
            country_code = raw.get('coPais') or raw.get('countryCode') or raw.get('pais')
            country_name = raw.get('noPais') or raw.get('countryName') or raw.get('paisNome')

            # Get state info
            state_code = raw.get('sgUfNcm') or raw.get('state') or raw.get('uf')

            # Get NCM code
            ncm_code = raw.get('coNcm') or raw.get('ncm')

            # Get values
            value_fob = self._safe_float(
                raw.get('metricFOB') or raw.get('vlFob') or raw.get('fob') or 0
            )
            quantity_kg = self._safe_float(
                raw.get('metricKG') or raw.get('kgLiquido') or raw.get('kg') or 0
            )
            quantity_stat = self._safe_float(
                raw.get('metricStatistic') or raw.get('qtEstat') or raw.get('qtd') or 0
            )

            # Skip empty records
            if not value_fob and not quantity_kg:
                return None

            return {
                # Time dimensions
                'year': int(year) if year else None,
                'month': int(month) if month else None,
                'period': f"{year}-{str(month).zfill(2)}" if year and month else None,

                # Product dimensions
                'commodity': commodity,
                'commodity_description': product_info['description'],
                'ncm_code': str(ncm_code) if ncm_code else None,
                'sh6_code': str(ncm_code)[:6] if ncm_code and len(str(ncm_code)) >= 6 else None,
                'sh4_code': str(ncm_code)[:4] if ncm_code and len(str(ncm_code)) >= 4 else None,
                'chapter': str(ncm_code)[:2] if ncm_code else None,

                # Geography dimensions
                'flow': flow,
                'country_code': str(country_code) if country_code else None,
                'country_name': country_name,
                'state_code': state_code,
                'state_name': BR_STATES.get(state_code, state_code),

                # Values
                'value_fob_usd': value_fob,
                'quantity_kg': quantity_kg,
                'quantity_mt': quantity_kg / 1000 if quantity_kg else None,
                'quantity_stat': quantity_stat,
                'unit': product_info['unit'],

                # Derived
                'unit_value_usd_mt': (
                    (value_fob / (quantity_kg / 1000))
                    if quantity_kg and quantity_kg > 0
                    else None
                ),

                # Metadata
                'source': 'COMEXSTAT',
                'collected_at': datetime.now().isoformat()
            }

        except Exception as e:
            self.logger.warning(f"Error transforming record: {e}")
            return None

    def _safe_float(self, value: Any) -> Optional[float]:
        """Safely convert value to float"""
        if value is None or value == '' or str(value).strip() == '':
            return None
        try:
            return float(value)
        except (ValueError, TypeError):
            return None

    def parse_response(self, response_data: Any) -> Any:
        """Parse API response"""
        return response_data

    # =========================================================================
    # CONVENIENCE METHODS
    # =========================================================================

    def get_soybean_exports(
        self,
        start_date: date = None,
        end_date: date = None
    ) -> Optional[Any]:
        """
        Get Brazilian soybean exports (beans, meal, oil).

        Returns:
            DataFrame or list of records
        """
        result = self.collect(
            flow="export",
            commodities=['soybeans', 'soybean_meal', 'soybean_oil'],
            start_date=start_date,
            end_date=end_date
        )
        return result.data if result.success else None

    def get_corn_exports(
        self,
        start_date: date = None,
        end_date: date = None
    ) -> Optional[Any]:
        """Get Brazilian corn exports"""
        result = self.collect(
            flow="export",
            commodities=['corn'],
            start_date=start_date,
            end_date=end_date
        )
        return result.data if result.success else None

    def get_exports_by_country(
        self,
        commodity: str,
        year: int = None
    ) -> Dict[str, float]:
        """
        Get export totals by destination country for a commodity.

        Returns:
            Dict of country -> total MT exported
        """
        year = year or date.today().year - 1

        result = self.collect(
            flow="export",
            commodities=[commodity],
            start_date=date(year, 1, 1),
            end_date=date(year, 12, 31)
        )

        if not result.success or result.data is None:
            return {}

        if PANDAS_AVAILABLE and hasattr(result.data, 'groupby'):
            df = result.data
            by_country = df.groupby('country_name')['quantity_mt'].sum()
            return by_country.to_dict()

        # Manual aggregation for non-pandas case
        totals = {}
        for record in result.data:
            country = record.get('country_name', 'Unknown')
            mt = record.get('quantity_mt', 0) or 0
            totals[country] = totals.get(country, 0) + mt

        return dict(sorted(totals.items(), key=lambda x: x[1], reverse=True))

    def get_exports_by_state(
        self,
        commodity: str,
        year: int = None
    ) -> Dict[str, float]:
        """
        Get export totals by Brazilian state of origin.

        Returns:
            Dict of state -> total MT exported
        """
        year = year or date.today().year - 1

        result = self.collect(
            flow="export",
            commodities=[commodity],
            start_date=date(year, 1, 1),
            end_date=date(year, 12, 31)
        )

        if not result.success or result.data is None:
            return {}

        if PANDAS_AVAILABLE and hasattr(result.data, 'groupby'):
            df = result.data
            by_state = df.groupby('state_name')['quantity_mt'].sum()
            return by_state.to_dict()

        # Manual aggregation
        totals = {}
        for record in result.data:
            state = record.get('state_name', 'Unknown')
            mt = record.get('quantity_mt', 0) or 0
            totals[state] = totals.get(state, 0) + mt

        return dict(sorted(totals.items(), key=lambda x: x[1], reverse=True))

    def get_monthly_time_series(
        self,
        commodity: str,
        flow: str = "export",
        start_year: int = None,
        end_year: int = None
    ) -> List[Dict]:
        """
        Get monthly time series for a commodity.

        Returns:
            List of {period, quantity_mt, value_usd} dicts
        """
        end_year = end_year or date.today().year
        start_year = start_year or (end_year - 5)

        result = self.collect(
            flow=flow,
            commodities=[commodity],
            start_date=date(start_year, 1, 1),
            end_date=date(end_year, 12, 31)
        )

        if not result.success or result.data is None:
            return []

        if PANDAS_AVAILABLE and hasattr(result.data, 'groupby'):
            df = result.data
            monthly = df.groupby('period').agg({
                'quantity_mt': 'sum',
                'value_fob_usd': 'sum'
            }).reset_index()
            return monthly.to_dict(orient='records')

        # Manual aggregation
        monthly = {}
        for record in result.data:
            period = record.get('period', '')
            if period not in monthly:
                monthly[period] = {'period': period, 'quantity_mt': 0, 'value_fob_usd': 0}
            monthly[period]['quantity_mt'] += record.get('quantity_mt', 0) or 0
            monthly[period]['value_fob_usd'] += record.get('value_fob_usd', 0) or 0

        return sorted(monthly.values(), key=lambda x: x['period'])

    def get_china_soybean_exports(
        self,
        year: int = None
    ) -> Dict[str, Any]:
        """
        Get detailed soybean exports to China (Brazil's largest buyer).

        Returns:
            Dict with monthly data and totals
        """
        year = year or date.today().year - 1

        result = self.collect(
            flow="export",
            commodities=['soybeans'],
            start_date=date(year, 1, 1),
            end_date=date(year, 12, 31)
        )

        if not result.success or result.data is None:
            return {}

        # Filter for China (country code typically 160 or CN)
        china_records = []
        total_mt = 0
        total_usd = 0

        for record in (result.data if isinstance(result.data, list) else result.data.to_dict('records')):
            country = str(record.get('country_name', '')).lower()
            if 'china' in country or record.get('country_code') in ['160', 'CN']:
                china_records.append(record)
                total_mt += record.get('quantity_mt', 0) or 0
                total_usd += record.get('value_fob_usd', 0) or 0

        return {
            'year': year,
            'destination': 'China',
            'total_mt': total_mt,
            'total_mmt': total_mt / 1_000_000,
            'total_usd': total_usd,
            'total_billion_usd': total_usd / 1_000_000_000,
            'avg_price_usd_mt': total_usd / total_mt if total_mt > 0 else 0,
            'monthly_data': china_records
        }


# =============================================================================
# CLI INTERFACE
# =============================================================================

def main():
    """Command-line interface for COMEXSTAT collector"""
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    parser = argparse.ArgumentParser(description='COMEXSTAT Brazilian Trade Data Collector')

    parser.add_argument(
        'command',
        choices=['collect', 'soybeans', 'corn', 'by_country', 'by_state', 'test'],
        help='Command to execute'
    )

    parser.add_argument(
        '--flow',
        choices=['export', 'import'],
        default='export',
        help='Trade flow direction'
    )

    parser.add_argument(
        '--commodities',
        nargs='+',
        default=['soybeans', 'corn'],
        help='Commodities to fetch'
    )

    parser.add_argument(
        '--year',
        type=int,
        default=None,
        help='Year for data (default: last year)'
    )

    parser.add_argument(
        '--output', '-o',
        help='Output file (JSON or CSV)'
    )

    args = parser.parse_args()

    config = COMEXSTATConfig(commodities=args.commodities)
    collector = COMEXSTATCollector(config)

    if args.command == 'test':
        success, message = collector.test_connection()
        print(f"Connection test: {'PASS' if success else 'FAIL'} - {message}")
        return

    year = args.year or (date.today().year - 1)

    if args.command == 'collect':
        result = collector.collect(
            flow=args.flow,
            commodities=args.commodities,
            start_date=date(year, 1, 1),
            end_date=date(year, 12, 31)
        )

        print(f"Success: {result.success}")
        print(f"Records: {result.records_fetched}")

        if result.warnings:
            print(f"Warnings: {result.warnings}")

        if result.error_message:
            print(f"Error: {result.error_message}")

    elif args.command == 'soybeans':
        data = collector.get_soybean_exports(
            start_date=date(year, 1, 1),
            end_date=date(year, 12, 31)
        )
        print(f"Soybean export data: {len(data) if data is not None else 0} records")

    elif args.command == 'corn':
        data = collector.get_corn_exports(
            start_date=date(year, 1, 1),
            end_date=date(year, 12, 31)
        )
        print(f"Corn export data: {len(data) if data is not None else 0} records")

    elif args.command == 'by_country':
        for commodity in args.commodities:
            print(f"\n{commodity.upper()} exports by country ({year}):")
            totals = collector.get_exports_by_country(commodity, year)
            for country, mt in list(totals.items())[:10]:
                print(f"  {country}: {mt/1000:.1f} TMT")

    elif args.command == 'by_state':
        for commodity in args.commodities:
            print(f"\n{commodity.upper()} exports by Brazilian state ({year}):")
            totals = collector.get_exports_by_state(commodity, year)
            for state, mt in list(totals.items())[:10]:
                print(f"  {state}: {mt/1000:.1f} TMT")

    if args.output and 'result' in dir() and result.data is not None:
        if args.output.endswith('.csv') and PANDAS_AVAILABLE:
            result.data.to_csv(args.output, index=False)
        else:
            if PANDAS_AVAILABLE and hasattr(result.data, 'to_json'):
                result.data.to_json(args.output, orient='records', date_format='iso')
            else:
                with open(args.output, 'w') as f:
                    json.dump(result.data, f, default=str, indent=2)
        print(f"Saved to: {args.output}")


if __name__ == '__main__':
    main()
