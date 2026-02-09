"""
COMEXSTAT Agent - Brazilian Trade Data Pipeline

Main agent for collecting, verifying, transforming, and visualizing
Brazilian agricultural trade data from COMEXSTAT.

This agent integrates:
- Data collection from COMEXSTAT API
- Bronze database storage (raw data)
- Silver transformation (standardized data)
- Gold visualizations (charts and reports)
- Data verification at each step

Designed for integration with the RLC Desktop LLM for trade flow analysis.
"""

import logging
import json
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
import uuid

logger = logging.getLogger(__name__)

# Import collector
from .collectors.south_america.comexstat_collector import (
    COMEXSTATCollector,
    COMEXSTATConfig,
    COMEXSTAT_AGRICULTURAL_PRODUCTS
)

# Import verifier
from .verification.comexstat_verifier import (
    COMEXSTATVerifier,
    VerificationReport,
    VerificationStatus
)

# Import visualizer
from .visualization.brazil_trade_visualizations import (
    BrazilTradeVisualizer,
    VisualizationConfig,
    VisualizationResult
)

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False


@dataclass
class AgentConfig:
    """Configuration for COMEXSTAT Agent"""
    # Data collection
    commodities: List[str] = field(default_factory=lambda: [
        'soybeans', 'soybean_meal', 'soybean_oil', 'corn', 'wheat',
        'cotton', 'sugar_raw', 'coffee', 'beef_fresh', 'chicken'
    ])
    default_years_back: int = 5

    # Database
    db_type: str = "postgresql"
    db_connection_string: Optional[str] = None

    # Output
    output_dir: Path = field(default_factory=lambda: Path("./data/comexstat"))
    reports_dir: Path = field(default_factory=lambda: Path("./reports/comexstat"))
    cache_dir: Path = field(default_factory=lambda: Path("./data/cache/comexstat"))

    # Verification
    verification_tolerance_pct: float = 0.01
    auto_verify: bool = True

    # Visualization
    generate_visualizations: bool = True
    visualization_format: str = "png"


@dataclass
class PipelineResult:
    """Result of running the full data pipeline"""
    success: bool
    run_id: str
    run_timestamp: datetime

    # Collection results
    records_collected: int = 0
    commodities_collected: List[str] = field(default_factory=list)
    period_start: Optional[date] = None
    period_end: Optional[date] = None

    # Verification results
    verification_status: Optional[str] = None
    verification_summary: Dict[str, int] = field(default_factory=dict)

    # Transformation results
    records_transformed: int = 0

    # Visualization results
    visualizations_created: int = 0
    visualization_paths: List[str] = field(default_factory=list)

    # Output files
    bronze_file: Optional[Path] = None
    silver_file: Optional[Path] = None
    report_file: Optional[Path] = None

    # Errors and warnings
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    # Timing
    duration_seconds: float = 0.0


class COMEXSTATAgent:
    """
    Main agent for Brazilian trade data pipeline.

    Provides a complete workflow for:
    1. Collecting data from COMEXSTAT API
    2. Storing raw data (Bronze layer)
    3. Verifying data integrity
    4. Transforming to standardized format (Silver layer)
    5. Creating visualizations (Gold layer)
    6. Integrating with Desktop LLM for analysis

    Usage:
        agent = COMEXSTATAgent()

        # Run full pipeline
        result = agent.run_monthly_collection()

        # Or run individual steps
        bronze_data = agent.collect_data(flow='export', commodities=['soybeans'])
        verification = agent.verify_data(bronze_data)
        silver_data = agent.transform_data(bronze_data)
        charts = agent.create_visualizations(silver_data)
    """

    def __init__(self, config: AgentConfig = None):
        """
        Initialize COMEXSTAT Agent.

        Args:
            config: Agent configuration (uses defaults if None)
        """
        self.config = config or AgentConfig()
        self.logger = logging.getLogger(f"{self.__class__.__name__}")

        # Create output directories
        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        self.config.reports_dir.mkdir(parents=True, exist_ok=True)
        self.config.cache_dir.mkdir(parents=True, exist_ok=True)

        # Initialize sub-components
        self.collector = COMEXSTATCollector(
            COMEXSTATConfig(commodities=self.config.commodities)
        )

        self.verifier = COMEXSTATVerifier(
            tolerance_pct=self.config.verification_tolerance_pct
        )

        self.visualizer = BrazilTradeVisualizer(
            VisualizationConfig(
                output_dir=self.config.reports_dir / "visualizations",
                save_format=self.config.visualization_format
            )
        )

        self.logger.info("Initialized COMEXSTAT Agent")

    def generate_run_id(self) -> str:
        """Generate unique run ID"""
        return datetime.now().strftime("%Y%m%d_%H%M%S_") + str(uuid.uuid4())[:8]

    # =========================================================================
    # MAIN PIPELINE
    # =========================================================================

    def run_monthly_collection(
        self,
        year: int = None,
        month: int = None,
        commodities: List[str] = None,
        flows: List[str] = None
    ) -> PipelineResult:
        """
        Run complete monthly data collection pipeline.

        This is the primary method for scheduled monthly data updates.

        Args:
            year: Year to collect (default: previous month)
            month: Month to collect (default: previous month)
            commodities: Commodities to collect (default: all configured)
            flows: Trade flows to collect (default: ['export', 'import'])

        Returns:
            PipelineResult with complete pipeline status
        """
        run_id = self.generate_run_id()
        start_time = datetime.now()

        result = PipelineResult(
            success=False,
            run_id=run_id,
            run_timestamp=start_time
        )

        # Determine period
        if year is None or month is None:
            # Default to previous month
            today = date.today()
            if today.month == 1:
                year = today.year - 1
                month = 12
            else:
                year = today.year
                month = today.month - 1

        period_start = date(year, month, 1)
        if month == 12:
            period_end = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            period_end = date(year, month + 1, 1) - timedelta(days=1)

        result.period_start = period_start
        result.period_end = period_end

        commodities = commodities or self.config.commodities
        flows = flows or ['export', 'import']

        self.logger.info(
            f"Starting monthly collection: {year}-{month:02d} "
            f"for {len(commodities)} commodities"
        )

        all_bronze_data = []

        try:
            # Step 1: Collect data
            for flow in flows:
                self.logger.info(f"Collecting {flow} data...")

                collector_result = self.collector.collect(
                    flow=flow,
                    commodities=commodities,
                    start_date=period_start,
                    end_date=period_end
                )

                if collector_result.success and collector_result.data is not None:
                    if PANDAS_AVAILABLE and hasattr(collector_result.data, 'to_dict'):
                        records = collector_result.data.to_dict('records')
                    else:
                        records = collector_result.data

                    all_bronze_data.extend(records)
                    result.records_collected += collector_result.records_fetched
                    self.logger.info(f"  Collected {collector_result.records_fetched} {flow} records")
                else:
                    result.warnings.append(f"Failed to collect {flow} data: {collector_result.error_message}")

            if not all_bronze_data:
                result.errors.append("No data collected")
                return result

            result.commodities_collected = list(set(
                r.get('commodity') for r in all_bronze_data if r.get('commodity')
            ))

            # Step 2: Save bronze data
            bronze_file = self._save_bronze_data(all_bronze_data, run_id)
            result.bronze_file = bronze_file

            # Step 3: Verify bronze data
            if self.config.auto_verify:
                self.logger.info("Verifying bronze data...")
                verification = self.verifier.verify_bronze_data(
                    all_bronze_data,
                    {'expected_count': len(all_bronze_data)}
                )
                result.verification_status = verification.overall_status.value
                result.verification_summary = verification.summary

                if verification.overall_status == VerificationStatus.FAILED:
                    result.warnings.append("Data verification failed - check verification report")

            # Step 4: Transform to silver
            self.logger.info("Transforming to silver layer...")
            silver_data = self._transform_to_silver(all_bronze_data)
            result.records_transformed = len(silver_data)

            silver_file = self._save_silver_data(silver_data, run_id)
            result.silver_file = silver_file

            # Step 5: Create visualizations
            if self.config.generate_visualizations and PANDAS_AVAILABLE:
                self.logger.info("Creating visualizations...")
                viz_results = self._create_visualizations(all_bronze_data, year)
                result.visualizations_created = len([v for v in viz_results.values() if v.success])
                result.visualization_paths = [
                    str(v.file_path) for v in viz_results.values()
                    if v.success and v.file_path
                ]

            # Step 6: Generate summary report
            report_file = self._generate_report(result, all_bronze_data)
            result.report_file = report_file

            result.success = True

        except Exception as e:
            self.logger.error(f"Pipeline error: {e}", exc_info=True)
            result.errors.append(str(e))

        result.duration_seconds = (datetime.now() - start_time).total_seconds()

        self.logger.info(
            f"Pipeline complete: {result.success} "
            f"({result.records_collected} records, {result.duration_seconds:.1f}s)"
        )

        return result

    def run_historical_collection(
        self,
        start_year: int,
        end_year: int = None,
        commodities: List[str] = None
    ) -> PipelineResult:
        """
        Run historical data collection for multiple years.

        Args:
            start_year: First year to collect
            end_year: Last year to collect (default: current year)
            commodities: Commodities to collect

        Returns:
            PipelineResult with complete pipeline status
        """
        end_year = end_year or date.today().year
        commodities = commodities or self.config.commodities

        run_id = self.generate_run_id()
        start_time = datetime.now()

        result = PipelineResult(
            success=False,
            run_id=run_id,
            run_timestamp=start_time,
            period_start=date(start_year, 1, 1),
            period_end=date(end_year, 12, 31)
        )

        self.logger.info(
            f"Starting historical collection: {start_year}-{end_year} "
            f"for {len(commodities)} commodities"
        )

        all_bronze_data = []

        try:
            for flow in ['export', 'import']:
                collector_result = self.collector.collect(
                    flow=flow,
                    commodities=commodities,
                    start_date=date(start_year, 1, 1),
                    end_date=date(end_year, 12, 31)
                )

                if collector_result.success and collector_result.data is not None:
                    if PANDAS_AVAILABLE and hasattr(collector_result.data, 'to_dict'):
                        records = collector_result.data.to_dict('records')
                    else:
                        records = collector_result.data

                    all_bronze_data.extend(records)
                    result.records_collected += collector_result.records_fetched

            if all_bronze_data:
                # Save and process
                result.bronze_file = self._save_bronze_data(all_bronze_data, run_id)

                silver_data = self._transform_to_silver(all_bronze_data)
                result.records_transformed = len(silver_data)
                result.silver_file = self._save_silver_data(silver_data, run_id)

                if self.config.generate_visualizations and PANDAS_AVAILABLE:
                    viz_results = self._create_visualizations(all_bronze_data, end_year)
                    result.visualizations_created = len([v for v in viz_results.values() if v.success])

                result.success = True

        except Exception as e:
            self.logger.error(f"Historical collection error: {e}", exc_info=True)
            result.errors.append(str(e))

        result.duration_seconds = (datetime.now() - start_time).total_seconds()
        return result

    # =========================================================================
    # INDIVIDUAL PIPELINE STEPS
    # =========================================================================

    def collect_data(
        self,
        flow: str = "export",
        commodities: List[str] = None,
        start_date: date = None,
        end_date: date = None
    ) -> Optional[Union[pd.DataFrame, List[Dict]]]:
        """
        Collect data from COMEXSTAT API.

        Args:
            flow: 'export' or 'import'
            commodities: List of commodities to collect
            start_date: Start of period
            end_date: End of period

        Returns:
            Collected data as DataFrame or list
        """
        commodities = commodities or self.config.commodities

        result = self.collector.collect(
            flow=flow,
            commodities=commodities,
            start_date=start_date,
            end_date=end_date
        )

        if result.success:
            return result.data
        else:
            self.logger.error(f"Collection failed: {result.error_message}")
            return None

    def verify_data(
        self,
        data: Union[pd.DataFrame, List[Dict]],
        api_metadata: Dict = None
    ) -> VerificationReport:
        """
        Verify collected data.

        Args:
            data: Data to verify
            api_metadata: Optional API response metadata

        Returns:
            VerificationReport with check results
        """
        return self.verifier.verify_bronze_data(data, api_metadata)

    def transform_data(
        self,
        bronze_data: Union[pd.DataFrame, List[Dict]]
    ) -> List[Dict]:
        """
        Transform bronze data to silver format.

        Args:
            bronze_data: Raw collected data

        Returns:
            Transformed silver data
        """
        return self._transform_to_silver(bronze_data)

    def create_visualizations(
        self,
        data: Union[pd.DataFrame, List[Dict]],
        year: int = None
    ) -> Dict[str, VisualizationResult]:
        """
        Create visualizations for the data.

        Args:
            data: Data to visualize
            year: Year for point-in-time charts

        Returns:
            Dict mapping chart name to result
        """
        return self._create_visualizations(data, year)

    # =========================================================================
    # LLM INTEGRATION METHODS
    # =========================================================================

    def get_summary_for_llm(
        self,
        commodity: str,
        year: int = None
    ) -> Dict[str, Any]:
        """
        Get a summary suitable for LLM analysis.

        Args:
            commodity: Commodity to summarize
            year: Year for analysis

        Returns:
            Dict with summary data for LLM context
        """
        year = year or date.today().year - 1

        # Collect recent data
        data = self.collect_data(
            flow='export',
            commodities=[commodity],
            start_date=date(year, 1, 1),
            end_date=date(year, 12, 31)
        )

        if data is None:
            return {'error': 'Failed to collect data'}

        if PANDAS_AVAILABLE and hasattr(data, 'groupby'):
            df = data

            summary = {
                'commodity': commodity,
                'year': year,
                'source': 'COMEXSTAT',

                'total_exports_mt': float(df['quantity_mt'].sum()),
                'total_exports_mmt': float(df['quantity_mt'].sum() / 1_000_000),
                'total_value_usd': float(df['value_fob_usd'].sum()),
                'total_value_billion_usd': float(df['value_fob_usd'].sum() / 1_000_000_000),

                'avg_price_usd_mt': float(
                    df['value_fob_usd'].sum() / df['quantity_mt'].sum()
                ) if df['quantity_mt'].sum() > 0 else 0,

                'top_destinations': df.groupby('country_name')['quantity_mt'].sum().nlargest(5).to_dict(),

                'monthly_volumes': df.groupby('month')['quantity_mt'].sum().to_dict(),

                'top_states': df.groupby('state_name')['quantity_mt'].sum().nlargest(5).to_dict()
                    if 'state_name' in df.columns else {}
            }
        else:
            # Basic summary without pandas
            total_mt = sum(r.get('quantity_mt', 0) or 0 for r in data)
            total_usd = sum(r.get('value_fob_usd', 0) or 0 for r in data)

            summary = {
                'commodity': commodity,
                'year': year,
                'source': 'COMEXSTAT',
                'total_exports_mt': total_mt,
                'total_exports_mmt': total_mt / 1_000_000,
                'total_value_usd': total_usd,
                'total_value_billion_usd': total_usd / 1_000_000_000,
                'avg_price_usd_mt': total_usd / total_mt if total_mt > 0 else 0
            }

        return summary

    def answer_query(self, query: str) -> str:
        """
        Process a natural language query about Brazilian trade.

        Args:
            query: Natural language question

        Returns:
            Text response with data
        """
        query_lower = query.lower()

        # Determine what's being asked
        commodity = None
        for c in self.config.commodities:
            if c.replace('_', ' ') in query_lower or c in query_lower:
                commodity = c
                break

        if not commodity:
            commodity = 'soybeans'  # Default

        # Determine year
        year = None
        for y in range(2024, 2018, -1):
            if str(y) in query:
                year = y
                break

        if year is None:
            year = date.today().year - 1

        # Get summary
        summary = self.get_summary_for_llm(commodity, year)

        if 'error' in summary:
            return f"Unable to retrieve data: {summary['error']}"

        # Format response
        response = f"""
## Brazil {commodity.replace('_', ' ').title()} Export Summary ({year})

**Total Volume:** {summary['total_exports_mmt']:.2f} million metric tons
**Total Value:** ${summary['total_value_billion_usd']:.2f} billion USD
**Average Price:** ${summary['avg_price_usd_mt']:.2f} per metric ton

**Top Destinations:**
"""
        for country, mt in summary.get('top_destinations', {}).items():
            response += f"- {country}: {mt/1_000_000:.2f} MMT\n"

        if summary.get('top_states'):
            response += "\n**Top Brazilian States:**\n"
            for state, mt in summary.get('top_states', {}).items():
                response += f"- {state}: {mt/1_000_000:.2f} MMT\n"

        return response

    # =========================================================================
    # PRIVATE HELPER METHODS
    # =========================================================================

    def _save_bronze_data(
        self,
        data: List[Dict],
        run_id: str
    ) -> Path:
        """Save bronze data to file"""
        filename = f"bronze_{run_id}.json"
        file_path = self.config.output_dir / "bronze" / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)

        with open(file_path, 'w') as f:
            json.dump(data, f, default=str, indent=2)

        self.logger.info(f"Saved bronze data to {file_path}")
        return file_path

    def _save_silver_data(
        self,
        data: List[Dict],
        run_id: str
    ) -> Path:
        """Save silver data to file"""
        filename = f"silver_{run_id}.json"
        file_path = self.config.output_dir / "silver" / filename
        file_path.parent.mkdir(parents=True, exist_ok=True)

        with open(file_path, 'w') as f:
            json.dump(data, f, default=str, indent=2)

        self.logger.info(f"Saved silver data to {file_path}")
        return file_path

    def _transform_to_silver(
        self,
        bronze_data: Union[pd.DataFrame, List[Dict]]
    ) -> List[Dict]:
        """Transform bronze to silver format"""
        if PANDAS_AVAILABLE:
            if isinstance(bronze_data, list):
                df = pd.DataFrame(bronze_data)
            else:
                df = bronze_data

            # Aggregate by period and commodity
            silver = df.groupby([
                'year', 'month', 'period', 'flow', 'commodity'
            ]).agg({
                'quantity_mt': 'sum',
                'value_fob_usd': 'sum'
            }).reset_index()

            silver['avg_price_usd_mt'] = silver['value_fob_usd'] / silver['quantity_mt']

            return silver.to_dict('records')
        else:
            # Manual aggregation
            aggregated = {}
            for record in bronze_data:
                key = (
                    record.get('year'),
                    record.get('month'),
                    record.get('period'),
                    record.get('flow'),
                    record.get('commodity')
                )

                if key not in aggregated:
                    aggregated[key] = {
                        'year': record.get('year'),
                        'month': record.get('month'),
                        'period': record.get('period'),
                        'flow': record.get('flow'),
                        'commodity': record.get('commodity'),
                        'quantity_mt': 0,
                        'value_fob_usd': 0
                    }

                aggregated[key]['quantity_mt'] += record.get('quantity_mt', 0) or 0
                aggregated[key]['value_fob_usd'] += record.get('value_fob_usd', 0) or 0

            # Calculate derived fields
            result = []
            for record in aggregated.values():
                if record['quantity_mt'] > 0:
                    record['avg_price_usd_mt'] = record['value_fob_usd'] / record['quantity_mt']
                else:
                    record['avg_price_usd_mt'] = 0
                result.append(record)

            return result

    def _create_visualizations(
        self,
        data: Union[pd.DataFrame, List[Dict]],
        year: int = None
    ) -> Dict[str, VisualizationResult]:
        """Create visualizations for the data"""
        if isinstance(data, list):
            df = pd.DataFrame(data) if PANDAS_AVAILABLE else None
        else:
            df = data

        if df is None:
            return {}

        commodities = df['commodity'].unique().tolist() if 'commodity' in df.columns else []
        year = year or df['year'].max() if 'year' in df.columns else date.today().year

        return self.visualizer.generate_all_visualizations(df, commodities, year)

    def _generate_report(
        self,
        result: PipelineResult,
        data: List[Dict]
    ) -> Path:
        """Generate summary report"""
        report = {
            'run_id': result.run_id,
            'timestamp': result.run_timestamp.isoformat(),
            'success': result.success,
            'period': {
                'start': result.period_start.isoformat() if result.period_start else None,
                'end': result.period_end.isoformat() if result.period_end else None
            },
            'statistics': {
                'records_collected': result.records_collected,
                'records_transformed': result.records_transformed,
                'commodities': result.commodities_collected,
                'visualizations_created': result.visualizations_created
            },
            'verification': {
                'status': result.verification_status,
                'summary': result.verification_summary
            },
            'files': {
                'bronze': str(result.bronze_file) if result.bronze_file else None,
                'silver': str(result.silver_file) if result.silver_file else None,
                'visualizations': result.visualization_paths
            },
            'errors': result.errors,
            'warnings': result.warnings,
            'duration_seconds': result.duration_seconds
        }

        filename = f"report_{result.run_id}.json"
        file_path = self.config.reports_dir / filename

        with open(file_path, 'w') as f:
            json.dump(report, f, indent=2)

        self.logger.info(f"Generated report: {file_path}")
        return file_path


# =============================================================================
# CLI INTERFACE
# =============================================================================

def main():
    """Command-line interface for COMEXSTAT Agent"""
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    parser = argparse.ArgumentParser(description='COMEXSTAT Brazilian Trade Data Agent')

    subparsers = parser.add_subparsers(dest='command', help='Commands')

    # Monthly collection
    monthly_parser = subparsers.add_parser('monthly', help='Run monthly collection')
    monthly_parser.add_argument('--year', type=int, help='Year to collect')
    monthly_parser.add_argument('--month', type=int, help='Month to collect')
    monthly_parser.add_argument('--commodities', nargs='+', help='Commodities to collect')

    # Historical collection
    hist_parser = subparsers.add_parser('historical', help='Run historical collection')
    hist_parser.add_argument('--start-year', type=int, required=True, help='Start year')
    hist_parser.add_argument('--end-year', type=int, help='End year')
    hist_parser.add_argument('--commodities', nargs='+', help='Commodities to collect')

    # Query
    query_parser = subparsers.add_parser('query', help='Query trade data')
    query_parser.add_argument('question', help='Natural language question')

    # Summary
    summary_parser = subparsers.add_parser('summary', help='Get commodity summary')
    summary_parser.add_argument('--commodity', default='soybeans', help='Commodity')
    summary_parser.add_argument('--year', type=int, help='Year')

    args = parser.parse_args()

    agent = COMEXSTATAgent()

    if args.command == 'monthly':
        result = agent.run_monthly_collection(
            year=args.year,
            month=args.month,
            commodities=args.commodities
        )
        print(f"\nPipeline Result: {'SUCCESS' if result.success else 'FAILED'}")
        print(f"Records Collected: {result.records_collected}")
        print(f"Records Transformed: {result.records_transformed}")
        print(f"Visualizations: {result.visualizations_created}")
        print(f"Duration: {result.duration_seconds:.1f}s")

        if result.errors:
            print(f"\nErrors: {result.errors}")
        if result.warnings:
            print(f"\nWarnings: {result.warnings}")

    elif args.command == 'historical':
        result = agent.run_historical_collection(
            start_year=args.start_year,
            end_year=args.end_year,
            commodities=args.commodities
        )
        print(f"\nPipeline Result: {'SUCCESS' if result.success else 'FAILED'}")
        print(f"Records Collected: {result.records_collected}")

    elif args.command == 'query':
        response = agent.answer_query(args.question)
        print(response)

    elif args.command == 'summary':
        summary = agent.get_summary_for_llm(args.commodity, args.year)
        print(json.dumps(summary, indent=2, default=str))

    else:
        parser.print_help()


if __name__ == '__main__':
    main()
