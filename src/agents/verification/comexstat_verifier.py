"""
COMEXSTAT Data Verification Module

Ensures data integrity and accuracy throughout the Bronze -> Silver -> Gold pipeline:
- Validates raw data against source checksums
- Verifies transformations preserve totals
- Checks for data completeness
- Identifies anomalies and outliers
- Reconciles database totals with API responses

Designed for the RLC Agent data quality framework.
"""

import logging
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any, Tuple, Union
from enum import Enum

logger = logging.getLogger(__name__)

try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False


class VerificationStatus(Enum):
    """Status of a verification check"""
    PASSED = "PASSED"
    FAILED = "FAILED"
    WARNING = "WARNING"
    SKIPPED = "SKIPPED"


class DataLayer(Enum):
    """Database layers in medallion architecture"""
    BRONZE = "bronze"
    SILVER = "silver"
    GOLD = "gold"


@dataclass
class VerificationCheck:
    """Result of a single verification check"""
    check_name: str
    status: VerificationStatus
    layer: DataLayer
    description: str
    expected_value: Optional[Any] = None
    actual_value: Optional[Any] = None
    difference: Optional[float] = None
    difference_pct: Optional[float] = None
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class VerificationReport:
    """Complete verification report"""
    run_id: str
    run_timestamp: datetime
    data_source: str = "COMEXSTAT"
    checks: List[VerificationCheck] = field(default_factory=list)
    summary: Dict[str, int] = field(default_factory=dict)
    overall_status: VerificationStatus = VerificationStatus.PASSED
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_check(self, check: VerificationCheck):
        """Add a check to the report and update summary"""
        self.checks.append(check)
        status_name = check.status.value
        self.summary[status_name] = self.summary.get(status_name, 0) + 1

        # Update overall status
        if check.status == VerificationStatus.FAILED:
            self.overall_status = VerificationStatus.FAILED
        elif check.status == VerificationStatus.WARNING and self.overall_status != VerificationStatus.FAILED:
            self.overall_status = VerificationStatus.WARNING

    def to_dict(self) -> Dict:
        """Convert report to dictionary"""
        return {
            'run_id': self.run_id,
            'run_timestamp': self.run_timestamp.isoformat(),
            'data_source': self.data_source,
            'overall_status': self.overall_status.value,
            'summary': self.summary,
            'checks': [
                {
                    'check_name': c.check_name,
                    'status': c.status.value,
                    'layer': c.layer.value,
                    'description': c.description,
                    'expected_value': c.expected_value,
                    'actual_value': c.actual_value,
                    'difference': c.difference,
                    'difference_pct': c.difference_pct,
                    'details': c.details
                }
                for c in self.checks
            ],
            'metadata': self.metadata
        }


class COMEXSTATVerifier:
    """
    Verifies COMEXSTAT data integrity throughout the data pipeline.

    Checks performed:
    1. BRONZE: Raw data integrity
       - Record counts match API response
       - No duplicate records
       - Required fields populated
       - Value ranges reasonable

    2. SILVER: Transformation accuracy
       - Aggregation totals match bronze
       - No data loss in transformation
       - Derived fields calculated correctly

    3. GOLD: Business logic validation
       - View totals match silver
       - Percentages sum to 100%
       - Rankings are consistent
    """

    def __init__(self, db_connection=None, tolerance_pct: float = 0.01):
        """
        Initialize verifier.

        Args:
            db_connection: Database connection or connection factory
            tolerance_pct: Acceptable difference for numeric comparisons (default 0.01 = 1%)
        """
        self.db_connection = db_connection
        self.tolerance_pct = tolerance_pct
        self.logger = logging.getLogger(f"{self.__class__.__name__}")

    def run_id(self) -> str:
        """Generate unique run ID"""
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    # =========================================================================
    # BRONZE LAYER VERIFICATION
    # =========================================================================

    def verify_bronze_data(
        self,
        bronze_data: Union[pd.DataFrame, List[Dict]],
        api_response_metadata: Dict = None
    ) -> VerificationReport:
        """
        Verify bronze (raw) data integrity.

        Args:
            bronze_data: Raw data from collection
            api_response_metadata: Metadata from API response for comparison

        Returns:
            VerificationReport with all check results
        """
        report = VerificationReport(
            run_id=self.run_id(),
            run_timestamp=datetime.now(),
            metadata={'layer': 'bronze', 'api_metadata': api_response_metadata}
        )

        if isinstance(bronze_data, list):
            df = pd.DataFrame(bronze_data) if PANDAS_AVAILABLE else None
            data = bronze_data
        else:
            df = bronze_data
            data = bronze_data.to_dict('records') if PANDAS_AVAILABLE else bronze_data

        # Check 1: Record count
        report.add_check(self._check_record_count(
            data,
            api_response_metadata.get('expected_count') if api_response_metadata else None
        ))

        # Check 2: No duplicates
        report.add_check(self._check_duplicates(data, df))

        # Check 3: Required fields
        report.add_check(self._check_required_fields(data))

        # Check 4: Value ranges
        report.add_check(self._check_value_ranges(data, df))

        # Check 5: Data completeness
        report.add_check(self._check_data_completeness(data, df))

        # Check 6: Null values
        report.add_check(self._check_null_values(data, df))

        self.logger.info(
            f"Bronze verification complete: {report.summary}"
        )

        return report

    def _check_record_count(
        self,
        data: List[Dict],
        expected_count: int = None
    ) -> VerificationCheck:
        """Check that record count matches expected"""
        actual_count = len(data)

        if expected_count is None:
            return VerificationCheck(
                check_name="record_count",
                status=VerificationStatus.SKIPPED,
                layer=DataLayer.BRONZE,
                description="Record count check skipped - no expected value provided",
                actual_value=actual_count
            )

        if actual_count == expected_count:
            return VerificationCheck(
                check_name="record_count",
                status=VerificationStatus.PASSED,
                layer=DataLayer.BRONZE,
                description="Record count matches expected",
                expected_value=expected_count,
                actual_value=actual_count
            )
        else:
            diff = actual_count - expected_count
            diff_pct = abs(diff) / expected_count * 100 if expected_count > 0 else 0

            status = VerificationStatus.WARNING if diff_pct < 5 else VerificationStatus.FAILED

            return VerificationCheck(
                check_name="record_count",
                status=status,
                layer=DataLayer.BRONZE,
                description=f"Record count mismatch: expected {expected_count}, got {actual_count}",
                expected_value=expected_count,
                actual_value=actual_count,
                difference=diff,
                difference_pct=diff_pct
            )

    def _check_duplicates(
        self,
        data: List[Dict],
        df: pd.DataFrame = None
    ) -> VerificationCheck:
        """Check for duplicate records"""
        # Natural key fields for COMEXSTAT
        key_fields = ['year', 'month', 'flow', 'ncm_code', 'country_code', 'state_code']

        if df is not None and PANDAS_AVAILABLE:
            available_keys = [k for k in key_fields if k in df.columns]
            if available_keys:
                duplicates = df.duplicated(subset=available_keys, keep=False)
                dup_count = duplicates.sum()
            else:
                dup_count = 0
        else:
            # Manual check
            seen = set()
            dup_count = 0
            for record in data:
                key = tuple(str(record.get(k, '')) for k in key_fields)
                if key in seen:
                    dup_count += 1
                seen.add(key)

        if dup_count == 0:
            return VerificationCheck(
                check_name="no_duplicates",
                status=VerificationStatus.PASSED,
                layer=DataLayer.BRONZE,
                description="No duplicate records found",
                actual_value=0
            )
        else:
            return VerificationCheck(
                check_name="no_duplicates",
                status=VerificationStatus.WARNING,
                layer=DataLayer.BRONZE,
                description=f"Found {dup_count} potential duplicate records",
                actual_value=dup_count,
                details={'key_fields': key_fields}
            )

    def _check_required_fields(self, data: List[Dict]) -> VerificationCheck:
        """Check that required fields are populated"""
        required_fields = [
            'year', 'month', 'flow', 'commodity',
            'quantity_mt', 'value_fob_usd'
        ]

        missing_counts = {}
        for field in required_fields:
            missing = sum(1 for r in data if not r.get(field))
            if missing > 0:
                missing_counts[field] = missing

        if not missing_counts:
            return VerificationCheck(
                check_name="required_fields",
                status=VerificationStatus.PASSED,
                layer=DataLayer.BRONZE,
                description="All required fields populated",
                details={'required_fields': required_fields}
            )
        else:
            total_missing = sum(missing_counts.values())
            return VerificationCheck(
                check_name="required_fields",
                status=VerificationStatus.WARNING,
                layer=DataLayer.BRONZE,
                description=f"Missing required fields in {total_missing} instances",
                actual_value=total_missing,
                details={'missing_by_field': missing_counts}
            )

    def _check_value_ranges(
        self,
        data: List[Dict],
        df: pd.DataFrame = None
    ) -> VerificationCheck:
        """Check that numeric values are within reasonable ranges"""
        issues = []

        # Define reasonable ranges
        ranges = {
            'value_fob_usd': (0, 50_000_000_000),  # Max $50B per record
            'quantity_mt': (0, 100_000_000),       # Max 100 MMT per record
            'quantity_kg': (0, 100_000_000_000),   # Max 100B kg per record
            'year': (1997, date.today().year + 1),
            'month': (1, 12)
        }

        for field, (min_val, max_val) in ranges.items():
            for record in data:
                value = record.get(field)
                if value is not None:
                    try:
                        num_val = float(value)
                        if num_val < min_val or num_val > max_val:
                            issues.append({
                                'field': field,
                                'value': num_val,
                                'range': (min_val, max_val)
                            })
                    except (ValueError, TypeError):
                        pass

        if not issues:
            return VerificationCheck(
                check_name="value_ranges",
                status=VerificationStatus.PASSED,
                layer=DataLayer.BRONZE,
                description="All values within expected ranges"
            )
        else:
            return VerificationCheck(
                check_name="value_ranges",
                status=VerificationStatus.WARNING,
                layer=DataLayer.BRONZE,
                description=f"Found {len(issues)} values outside expected ranges",
                actual_value=len(issues),
                details={'issues': issues[:10]}  # First 10 issues
            )

    def _check_data_completeness(
        self,
        data: List[Dict],
        df: pd.DataFrame = None
    ) -> VerificationCheck:
        """Check for data completeness (expected months present)"""
        if not data:
            return VerificationCheck(
                check_name="data_completeness",
                status=VerificationStatus.FAILED,
                layer=DataLayer.BRONZE,
                description="No data to check"
            )

        # Get year/month combinations
        periods = set()
        for record in data:
            year = record.get('year')
            month = record.get('month')
            if year and month:
                periods.add((int(year), int(month)))

        if not periods:
            return VerificationCheck(
                check_name="data_completeness",
                status=VerificationStatus.WARNING,
                layer=DataLayer.BRONZE,
                description="Could not determine time periods in data"
            )

        # Check for gaps in the time series
        min_period = min(periods)
        max_period = max(periods)

        expected_periods = set()
        year, month = min_period
        while (year, month) <= max_period:
            expected_periods.add((year, month))
            month += 1
            if month > 12:
                month = 1
                year += 1

        missing_periods = expected_periods - periods

        if not missing_periods:
            return VerificationCheck(
                check_name="data_completeness",
                status=VerificationStatus.PASSED,
                layer=DataLayer.BRONZE,
                description=f"All {len(expected_periods)} expected periods present",
                details={'period_range': f"{min_period} to {max_period}"}
            )
        else:
            return VerificationCheck(
                check_name="data_completeness",
                status=VerificationStatus.WARNING,
                layer=DataLayer.BRONZE,
                description=f"Missing {len(missing_periods)} periods",
                expected_value=len(expected_periods),
                actual_value=len(periods),
                details={'missing_periods': sorted(list(missing_periods))[:12]}
            )

    def _check_null_values(
        self,
        data: List[Dict],
        df: pd.DataFrame = None
    ) -> VerificationCheck:
        """Check null value rates"""
        if df is not None and PANDAS_AVAILABLE:
            null_rates = df.isnull().sum() / len(df) * 100
            high_null_fields = null_rates[null_rates > 10].to_dict()
        else:
            null_rates = {}
            for record in data:
                for key, value in record.items():
                    if key not in null_rates:
                        null_rates[key] = {'null': 0, 'total': 0}
                    null_rates[key]['total'] += 1
                    if value is None or value == '':
                        null_rates[key]['null'] += 1

            high_null_fields = {
                k: v['null'] / v['total'] * 100
                for k, v in null_rates.items()
                if v['total'] > 0 and v['null'] / v['total'] > 0.1
            }

        if not high_null_fields:
            return VerificationCheck(
                check_name="null_values",
                status=VerificationStatus.PASSED,
                layer=DataLayer.BRONZE,
                description="No fields with >10% null values"
            )
        else:
            return VerificationCheck(
                check_name="null_values",
                status=VerificationStatus.WARNING,
                layer=DataLayer.BRONZE,
                description=f"Found {len(high_null_fields)} fields with >10% null values",
                details={'high_null_fields': high_null_fields}
            )

    # =========================================================================
    # SILVER LAYER VERIFICATION
    # =========================================================================

    def verify_silver_transformation(
        self,
        bronze_data: Union[pd.DataFrame, List[Dict]],
        silver_data: Union[pd.DataFrame, List[Dict]]
    ) -> VerificationReport:
        """
        Verify silver layer transformation accuracy.

        Args:
            bronze_data: Source bronze data
            silver_data: Transformed silver data

        Returns:
            VerificationReport with all check results
        """
        report = VerificationReport(
            run_id=self.run_id(),
            run_timestamp=datetime.now(),
            metadata={'layer': 'silver'}
        )

        # Convert to DataFrames
        if not PANDAS_AVAILABLE:
            report.add_check(VerificationCheck(
                check_name="silver_verification",
                status=VerificationStatus.SKIPPED,
                layer=DataLayer.SILVER,
                description="Pandas required for silver verification"
            ))
            return report

        bronze_df = pd.DataFrame(bronze_data) if isinstance(bronze_data, list) else bronze_data
        silver_df = pd.DataFrame(silver_data) if isinstance(silver_data, list) else silver_data

        # Check 1: Total volume preservation
        report.add_check(self._check_volume_preservation(bronze_df, silver_df))

        # Check 2: Total value preservation
        report.add_check(self._check_value_preservation(bronze_df, silver_df))

        # Check 3: Record aggregation
        report.add_check(self._check_aggregation_logic(bronze_df, silver_df))

        # Check 4: Derived field calculations
        report.add_check(self._check_derived_fields(silver_df))

        self.logger.info(
            f"Silver verification complete: {report.summary}"
        )

        return report

    def _check_volume_preservation(
        self,
        bronze_df: pd.DataFrame,
        silver_df: pd.DataFrame
    ) -> VerificationCheck:
        """Verify total volume is preserved through transformation"""
        # Find volume column in bronze
        bronze_vol_col = None
        for col in ['quantity_mt', 'quantity_kg', 'metricKG']:
            if col in bronze_df.columns:
                bronze_vol_col = col
                break

        if bronze_vol_col is None:
            return VerificationCheck(
                check_name="volume_preservation",
                status=VerificationStatus.SKIPPED,
                layer=DataLayer.SILVER,
                description="Could not find volume column in bronze data"
            )

        # Find volume column in silver
        silver_vol_col = None
        for col in ['quantity_mt', 'total_mt', 'volume_mt']:
            if col in silver_df.columns:
                silver_vol_col = col
                break

        if silver_vol_col is None:
            return VerificationCheck(
                check_name="volume_preservation",
                status=VerificationStatus.SKIPPED,
                layer=DataLayer.SILVER,
                description="Could not find volume column in silver data"
            )

        # Calculate totals
        bronze_total = bronze_df[bronze_vol_col].sum()
        silver_total = silver_df[silver_vol_col].sum()

        # Convert if needed (kg to mt)
        if 'kg' in bronze_vol_col.lower():
            bronze_total = bronze_total / 1000

        diff = abs(bronze_total - silver_total)
        diff_pct = diff / bronze_total * 100 if bronze_total > 0 else 0

        if diff_pct <= self.tolerance_pct:
            return VerificationCheck(
                check_name="volume_preservation",
                status=VerificationStatus.PASSED,
                layer=DataLayer.SILVER,
                description="Total volume preserved within tolerance",
                expected_value=bronze_total,
                actual_value=silver_total,
                difference=diff,
                difference_pct=diff_pct
            )
        else:
            return VerificationCheck(
                check_name="volume_preservation",
                status=VerificationStatus.FAILED,
                layer=DataLayer.SILVER,
                description=f"Volume mismatch: {diff_pct:.2f}% difference",
                expected_value=bronze_total,
                actual_value=silver_total,
                difference=diff,
                difference_pct=diff_pct
            )

    def _check_value_preservation(
        self,
        bronze_df: pd.DataFrame,
        silver_df: pd.DataFrame
    ) -> VerificationCheck:
        """Verify total value is preserved through transformation"""
        # Find value column in bronze
        bronze_val_col = None
        for col in ['value_fob_usd', 'value_usd', 'metricFOB']:
            if col in bronze_df.columns:
                bronze_val_col = col
                break

        # Find value column in silver
        silver_val_col = None
        for col in ['value_usd', 'total_usd', 'value_fob_usd']:
            if col in silver_df.columns:
                silver_val_col = col
                break

        if bronze_val_col is None or silver_val_col is None:
            return VerificationCheck(
                check_name="value_preservation",
                status=VerificationStatus.SKIPPED,
                layer=DataLayer.SILVER,
                description="Could not find value columns"
            )

        bronze_total = bronze_df[bronze_val_col].sum()
        silver_total = silver_df[silver_val_col].sum()

        diff = abs(bronze_total - silver_total)
        diff_pct = diff / bronze_total * 100 if bronze_total > 0 else 0

        if diff_pct <= self.tolerance_pct:
            return VerificationCheck(
                check_name="value_preservation",
                status=VerificationStatus.PASSED,
                layer=DataLayer.SILVER,
                description="Total value preserved within tolerance",
                expected_value=bronze_total,
                actual_value=silver_total,
                difference=diff,
                difference_pct=diff_pct
            )
        else:
            return VerificationCheck(
                check_name="value_preservation",
                status=VerificationStatus.FAILED,
                layer=DataLayer.SILVER,
                description=f"Value mismatch: {diff_pct:.2f}% difference",
                expected_value=bronze_total,
                actual_value=silver_total,
                difference=diff,
                difference_pct=diff_pct
            )

    def _check_aggregation_logic(
        self,
        bronze_df: pd.DataFrame,
        silver_df: pd.DataFrame
    ) -> VerificationCheck:
        """Verify aggregation logic is correct"""
        # Check that silver has fewer or equal records (aggregation reduces rows)
        bronze_count = len(bronze_df)
        silver_count = len(silver_df)

        if silver_count <= bronze_count:
            return VerificationCheck(
                check_name="aggregation_logic",
                status=VerificationStatus.PASSED,
                layer=DataLayer.SILVER,
                description=f"Aggregation reduced {bronze_count} to {silver_count} records",
                expected_value=bronze_count,
                actual_value=silver_count,
                details={'reduction_ratio': bronze_count / silver_count if silver_count > 0 else 0}
            )
        else:
            return VerificationCheck(
                check_name="aggregation_logic",
                status=VerificationStatus.WARNING,
                layer=DataLayer.SILVER,
                description=f"Silver has more records than bronze ({silver_count} > {bronze_count})",
                expected_value=bronze_count,
                actual_value=silver_count
            )

    def _check_derived_fields(self, silver_df: pd.DataFrame) -> VerificationCheck:
        """Verify derived field calculations"""
        issues = []

        # Check unit price calculation if present
        if all(col in silver_df.columns for col in ['avg_price_usd_mt', 'value_usd', 'quantity_mt']):
            for idx, row in silver_df.iterrows():
                if row['quantity_mt'] and row['quantity_mt'] > 0:
                    expected_price = row['value_usd'] / row['quantity_mt']
                    actual_price = row.get('avg_price_usd_mt', 0) or 0
                    if abs(expected_price - actual_price) > 0.01:
                        issues.append({
                            'idx': idx,
                            'expected': expected_price,
                            'actual': actual_price
                        })

        if not issues:
            return VerificationCheck(
                check_name="derived_fields",
                status=VerificationStatus.PASSED,
                layer=DataLayer.SILVER,
                description="Derived fields calculated correctly"
            )
        else:
            return VerificationCheck(
                check_name="derived_fields",
                status=VerificationStatus.WARNING,
                layer=DataLayer.SILVER,
                description=f"Found {len(issues)} derived field calculation issues",
                details={'issues': issues[:5]}
            )

    # =========================================================================
    # GOLD LAYER VERIFICATION
    # =========================================================================

    def verify_gold_views(
        self,
        silver_data: Union[pd.DataFrame, List[Dict]],
        gold_data: Union[pd.DataFrame, List[Dict]],
        view_name: str = None
    ) -> VerificationReport:
        """
        Verify gold layer views match silver source.

        Args:
            silver_data: Source silver data
            gold_data: Gold view data
            view_name: Name of the gold view being verified

        Returns:
            VerificationReport with all check results
        """
        report = VerificationReport(
            run_id=self.run_id(),
            run_timestamp=datetime.now(),
            metadata={'layer': 'gold', 'view_name': view_name}
        )

        if not PANDAS_AVAILABLE:
            report.add_check(VerificationCheck(
                check_name="gold_verification",
                status=VerificationStatus.SKIPPED,
                layer=DataLayer.GOLD,
                description="Pandas required for gold verification"
            ))
            return report

        silver_df = pd.DataFrame(silver_data) if isinstance(silver_data, list) else silver_data
        gold_df = pd.DataFrame(gold_data) if isinstance(gold_data, list) else gold_data

        # Check 1: Total consistency
        report.add_check(self._check_gold_totals(silver_df, gold_df))

        # Check 2: Percentage sums
        report.add_check(self._check_percentage_sums(gold_df))

        # Check 3: Ranking consistency
        report.add_check(self._check_ranking_consistency(gold_df))

        self.logger.info(
            f"Gold verification complete: {report.summary}"
        )

        return report

    def _check_gold_totals(
        self,
        silver_df: pd.DataFrame,
        gold_df: pd.DataFrame
    ) -> VerificationCheck:
        """Check that gold totals match silver"""
        # Find common numeric columns
        silver_nums = silver_df.select_dtypes(include=[np.number]).columns.tolist() if NUMPY_AVAILABLE else []
        gold_nums = gold_df.select_dtypes(include=[np.number]).columns.tolist() if NUMPY_AVAILABLE else []

        common_cols = set(silver_nums) & set(gold_nums)

        if not common_cols:
            return VerificationCheck(
                check_name="gold_totals",
                status=VerificationStatus.SKIPPED,
                layer=DataLayer.GOLD,
                description="No common numeric columns to compare"
            )

        issues = []
        for col in common_cols:
            silver_total = silver_df[col].sum()
            gold_total = gold_df[col].sum()
            diff_pct = abs(silver_total - gold_total) / silver_total * 100 if silver_total != 0 else 0

            if diff_pct > self.tolerance_pct:
                issues.append({
                    'column': col,
                    'silver_total': silver_total,
                    'gold_total': gold_total,
                    'diff_pct': diff_pct
                })

        if not issues:
            return VerificationCheck(
                check_name="gold_totals",
                status=VerificationStatus.PASSED,
                layer=DataLayer.GOLD,
                description="Gold totals match silver within tolerance"
            )
        else:
            return VerificationCheck(
                check_name="gold_totals",
                status=VerificationStatus.WARNING,
                layer=DataLayer.GOLD,
                description=f"Found {len(issues)} columns with total mismatches",
                details={'issues': issues}
            )

    def _check_percentage_sums(self, gold_df: pd.DataFrame) -> VerificationCheck:
        """Check that percentage columns sum to approximately 100%"""
        pct_cols = [col for col in gold_df.columns if 'pct' in col.lower() or 'share' in col.lower()]

        if not pct_cols:
            return VerificationCheck(
                check_name="percentage_sums",
                status=VerificationStatus.SKIPPED,
                layer=DataLayer.GOLD,
                description="No percentage columns to check"
            )

        issues = []
        for col in pct_cols:
            total = gold_df[col].sum()
            if abs(total - 100) > 1:  # Allow 1% tolerance
                issues.append({
                    'column': col,
                    'sum': total,
                    'expected': 100
                })

        if not issues:
            return VerificationCheck(
                check_name="percentage_sums",
                status=VerificationStatus.PASSED,
                layer=DataLayer.GOLD,
                description="Percentage columns sum to ~100%"
            )
        else:
            return VerificationCheck(
                check_name="percentage_sums",
                status=VerificationStatus.WARNING,
                layer=DataLayer.GOLD,
                description=f"Found {len(issues)} percentage columns that don't sum to 100%",
                details={'issues': issues}
            )

    def _check_ranking_consistency(self, gold_df: pd.DataFrame) -> VerificationCheck:
        """Check that rankings are consistent with values"""
        rank_cols = [col for col in gold_df.columns if 'rank' in col.lower()]

        if not rank_cols:
            return VerificationCheck(
                check_name="ranking_consistency",
                status=VerificationStatus.SKIPPED,
                layer=DataLayer.GOLD,
                description="No ranking columns to check"
            )

        issues = []
        for rank_col in rank_cols:
            # Check for duplicate ranks
            if gold_df[rank_col].duplicated().any():
                issues.append({
                    'column': rank_col,
                    'issue': 'duplicate_ranks'
                })

            # Check for gaps in ranks
            ranks = sorted(gold_df[rank_col].dropna().unique())
            expected = list(range(int(min(ranks)), int(max(ranks)) + 1))
            if ranks != expected:
                issues.append({
                    'column': rank_col,
                    'issue': 'non_sequential_ranks'
                })

        if not issues:
            return VerificationCheck(
                check_name="ranking_consistency",
                status=VerificationStatus.PASSED,
                layer=DataLayer.GOLD,
                description="Rankings are consistent"
            )
        else:
            return VerificationCheck(
                check_name="ranking_consistency",
                status=VerificationStatus.WARNING,
                layer=DataLayer.GOLD,
                description=f"Found {len(issues)} ranking issues",
                details={'issues': issues}
            )

    # =========================================================================
    # FULL PIPELINE VERIFICATION
    # =========================================================================

    def verify_full_pipeline(
        self,
        bronze_data: Union[pd.DataFrame, List[Dict]],
        silver_data: Union[pd.DataFrame, List[Dict]] = None,
        gold_data: Union[pd.DataFrame, List[Dict]] = None,
        api_metadata: Dict = None
    ) -> VerificationReport:
        """
        Run full pipeline verification across all layers.

        Args:
            bronze_data: Raw bronze data
            silver_data: Optional silver data to verify
            gold_data: Optional gold data to verify
            api_metadata: Optional API response metadata

        Returns:
            Combined VerificationReport
        """
        full_report = VerificationReport(
            run_id=self.run_id(),
            run_timestamp=datetime.now(),
            metadata={'full_pipeline': True}
        )

        # Bronze verification
        bronze_report = self.verify_bronze_data(bronze_data, api_metadata)
        for check in bronze_report.checks:
            full_report.add_check(check)

        # Silver verification
        if silver_data is not None:
            silver_report = self.verify_silver_transformation(bronze_data, silver_data)
            for check in silver_report.checks:
                full_report.add_check(check)

        # Gold verification
        if silver_data is not None and gold_data is not None:
            gold_report = self.verify_gold_views(silver_data, gold_data)
            for check in gold_report.checks:
                full_report.add_check(check)

        self.logger.info(
            f"Full pipeline verification complete: {full_report.overall_status.value} "
            f"({full_report.summary})"
        )

        return full_report


# =============================================================================
# CLI INTERFACE
# =============================================================================

def main():
    """Command-line interface for COMEXSTAT verification"""
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    parser = argparse.ArgumentParser(description='COMEXSTAT Data Verification')

    parser.add_argument(
        '--bronze-file',
        required=True,
        help='Path to bronze data file (CSV or JSON)'
    )

    parser.add_argument(
        '--silver-file',
        help='Path to silver data file (optional)'
    )

    parser.add_argument(
        '--gold-file',
        help='Path to gold data file (optional)'
    )

    parser.add_argument(
        '--output', '-o',
        help='Output file for verification report (JSON)'
    )

    parser.add_argument(
        '--tolerance',
        type=float,
        default=0.01,
        help='Tolerance percentage for numeric comparisons (default: 0.01 = 1%)'
    )

    args = parser.parse_args()

    # Load data
    from pathlib import Path

    def load_data(file_path):
        path = Path(file_path)
        if path.suffix == '.csv':
            return pd.read_csv(path)
        else:
            return pd.read_json(path)

    bronze_data = load_data(args.bronze_file)
    silver_data = load_data(args.silver_file) if args.silver_file else None
    gold_data = load_data(args.gold_file) if args.gold_file else None

    # Run verification
    verifier = COMEXSTATVerifier(tolerance_pct=args.tolerance)
    report = verifier.verify_full_pipeline(bronze_data, silver_data, gold_data)

    # Print summary
    print(f"\n{'='*60}")
    print(f"COMEXSTAT Data Verification Report")
    print(f"{'='*60}")
    print(f"Run ID: {report.run_id}")
    print(f"Overall Status: {report.overall_status.value}")
    print(f"\nSummary:")
    for status, count in report.summary.items():
        print(f"  {status}: {count}")

    print(f"\nDetails:")
    for check in report.checks:
        status_icon = {
            'PASSED': '✓',
            'FAILED': '✗',
            'WARNING': '⚠',
            'SKIPPED': '○'
        }.get(check.status.value, '?')

        print(f"  {status_icon} [{check.layer.value}] {check.check_name}: {check.description}")

    # Save report
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(report.to_dict(), f, indent=2)
        print(f"\nReport saved to: {args.output}")


if __name__ == '__main__':
    main()
