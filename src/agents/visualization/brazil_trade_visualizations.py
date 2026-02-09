"""
Brazil Trade Data Visualizations - Gold Tier

Creates compelling visualizations for Brazilian agricultural trade data:
- Export trends over time (line charts)
- Trade flow maps (destination analysis)
- Seasonality patterns (heatmaps)
- Market share analysis (pie/bar charts)
- Price trends and comparisons
- State-level production maps

Designed to integrate with the RLC Desktop LLM for analysis and reporting.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple, Union
from io import BytesIO
import json

logger = logging.getLogger(__name__)

# Try to import visualization libraries
try:
    import matplotlib
    matplotlib.use('Agg')  # Non-interactive backend
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.patches import Patch
    from matplotlib.colors import LinearSegmentedColormap
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    logger.warning("matplotlib not available - visualizations will be limited")

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

# Color palettes for visualizations
BRAZIL_COLORS = {
    'green': '#009C3B',       # Brazilian flag green
    'yellow': '#FFDF00',      # Brazilian flag yellow
    'blue': '#002776',        # Brazilian flag blue
    'white': '#FFFFFF',
}

COMMODITY_COLORS = {
    'soybeans': '#4CAF50',    # Green
    'soybean_meal': '#8BC34A',
    'soybean_oil': '#CDDC39',
    'corn': '#FFC107',        # Yellow/gold
    'wheat': '#FF9800',       # Orange
    'cotton': '#E0E0E0',      # Light gray
    'sugar_raw': '#795548',   # Brown
    'sugar_refined': '#FFFFFF',
    'coffee': '#3E2723',      # Dark brown
    'beef_fresh': '#D32F2F',  # Red
    'beef_frozen': '#C62828',
    'chicken': '#FF5722',     # Orange-red
    'pork': '#FF8A80',        # Light red
    'orange_juice': '#FF9800',
    'ethanol': '#00BCD4',     # Cyan
    'cellulose': '#607D8B',   # Blue-gray
}

# Brazilian states abbreviations to full names
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
class VisualizationConfig:
    """Configuration for visualizations"""
    output_dir: Path = field(default_factory=lambda: Path("./reports/visualizations"))
    figure_dpi: int = 150
    figure_size: Tuple[int, int] = (12, 8)
    style: str = "seaborn-v0_8-whitegrid"
    save_format: str = "png"
    title_fontsize: int = 14
    label_fontsize: int = 11
    tick_fontsize: int = 10
    include_watermark: bool = True
    watermark_text: str = "RLC Agent - COMEXSTAT Data"


@dataclass
class VisualizationResult:
    """Result of visualization generation"""
    success: bool
    chart_type: str
    file_path: Optional[Path] = None
    image_bytes: Optional[bytes] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    error_message: Optional[str] = None


class BrazilTradeVisualizer:
    """
    Creates visualizations for Brazilian agricultural trade data.

    Designed for the Gold tier of the medallion architecture, creating
    business-ready charts for reports and LLM analysis.
    """

    def __init__(self, config: VisualizationConfig = None):
        self.config = config or VisualizationConfig()
        self.logger = logging.getLogger(f"{self.__class__.__name__}")

        # Create output directory
        self.config.output_dir.mkdir(parents=True, exist_ok=True)

        # Set matplotlib style
        if MATPLOTLIB_AVAILABLE:
            try:
                plt.style.use(self.config.style)
            except Exception:
                plt.style.use('default')

        self.logger.info("Initialized BrazilTradeVisualizer")

    def _setup_figure(
        self,
        title: str,
        figsize: Tuple[int, int] = None
    ) -> Tuple[plt.Figure, plt.Axes]:
        """Set up a new figure with standard formatting"""
        figsize = figsize or self.config.figure_size
        fig, ax = plt.subplots(figsize=figsize, dpi=self.config.figure_dpi)

        ax.set_title(title, fontsize=self.config.title_fontsize, fontweight='bold')

        return fig, ax

    def _add_watermark(self, fig: plt.Figure):
        """Add watermark to figure"""
        if self.config.include_watermark:
            fig.text(
                0.99, 0.01, self.config.watermark_text,
                ha='right', va='bottom',
                fontsize=8, color='gray', alpha=0.5
            )

    def _save_figure(
        self,
        fig: plt.Figure,
        filename: str,
        chart_type: str
    ) -> VisualizationResult:
        """Save figure and return result"""
        try:
            # Add watermark
            self._add_watermark(fig)

            # Tight layout
            fig.tight_layout()

            # Save to file
            file_path = self.config.output_dir / f"{filename}.{self.config.save_format}"
            fig.savefig(
                file_path,
                dpi=self.config.figure_dpi,
                bbox_inches='tight',
                facecolor='white',
                edgecolor='none'
            )

            # Also save to bytes
            buf = BytesIO()
            fig.savefig(buf, format=self.config.save_format, bbox_inches='tight')
            buf.seek(0)
            image_bytes = buf.read()

            plt.close(fig)

            return VisualizationResult(
                success=True,
                chart_type=chart_type,
                file_path=file_path,
                image_bytes=image_bytes,
                metadata={'filename': filename, 'format': self.config.save_format}
            )

        except Exception as e:
            self.logger.error(f"Error saving figure: {e}")
            plt.close(fig)
            return VisualizationResult(
                success=False,
                chart_type=chart_type,
                error_message=str(e)
            )

    # =========================================================================
    # TIME SERIES CHARTS
    # =========================================================================

    def plot_export_trends(
        self,
        data: Union[pd.DataFrame, List[Dict]],
        commodity: str,
        title: str = None,
        filename: str = None
    ) -> VisualizationResult:
        """
        Create line chart showing export trends over time.

        Args:
            data: DataFrame or list with columns: period, quantity_mt, value_usd
            commodity: Commodity name for coloring
            title: Chart title (auto-generated if None)
            filename: Output filename (auto-generated if None)

        Returns:
            VisualizationResult with chart
        """
        if not MATPLOTLIB_AVAILABLE or not PANDAS_AVAILABLE:
            return VisualizationResult(
                success=False,
                chart_type='export_trends',
                error_message="matplotlib or pandas not available"
            )

        # Convert to DataFrame if needed
        if isinstance(data, list):
            df = pd.DataFrame(data)
        else:
            df = data.copy()

        # Ensure period is datetime
        if 'period' in df.columns:
            df['period'] = pd.to_datetime(df['period'])
            df = df.sort_values('period')

        title = title or f"Brazil {commodity.replace('_', ' ').title()} Exports"
        filename = filename or f"brazil_{commodity}_export_trends"

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 10), dpi=self.config.figure_dpi)

        color = COMMODITY_COLORS.get(commodity, '#1976D2')

        # Volume chart
        ax1.fill_between(
            df['period'],
            df['quantity_mt'] / 1000,  # Convert to TMT
            alpha=0.3,
            color=color
        )
        ax1.plot(
            df['period'],
            df['quantity_mt'] / 1000,
            color=color,
            linewidth=2,
            marker='o',
            markersize=4
        )
        ax1.set_ylabel('Volume (Thousand MT)', fontsize=self.config.label_fontsize)
        ax1.set_title(f'{title} - Volume', fontsize=self.config.title_fontsize, fontweight='bold')
        ax1.xaxis.set_major_locator(mdates.YearLocator())
        ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
        ax1.grid(True, alpha=0.3)

        # Value chart
        if 'value_fob_usd' in df.columns:
            value_col = 'value_fob_usd'
        else:
            value_col = 'value_usd'

        ax2.fill_between(
            df['period'],
            df[value_col] / 1_000_000,  # Convert to millions
            alpha=0.3,
            color=color
        )
        ax2.plot(
            df['period'],
            df[value_col] / 1_000_000,
            color=color,
            linewidth=2,
            marker='o',
            markersize=4
        )
        ax2.set_ylabel('Value (Million USD)', fontsize=self.config.label_fontsize)
        ax2.set_xlabel('Period', fontsize=self.config.label_fontsize)
        ax2.set_title(f'{title} - Value', fontsize=self.config.title_fontsize, fontweight='bold')
        ax2.xaxis.set_major_locator(mdates.YearLocator())
        ax2.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
        ax2.grid(True, alpha=0.3)

        return self._save_figure(fig, filename, 'export_trends')

    def plot_multi_commodity_comparison(
        self,
        data: Union[pd.DataFrame, List[Dict]],
        commodities: List[str],
        title: str = None,
        filename: str = None
    ) -> VisualizationResult:
        """
        Create comparison chart for multiple commodities.

        Args:
            data: DataFrame with columns: period, commodity, quantity_mt
            commodities: List of commodities to compare
            title: Chart title
            filename: Output filename

        Returns:
            VisualizationResult with chart
        """
        if not MATPLOTLIB_AVAILABLE or not PANDAS_AVAILABLE:
            return VisualizationResult(
                success=False,
                chart_type='multi_commodity',
                error_message="matplotlib or pandas not available"
            )

        df = pd.DataFrame(data) if isinstance(data, list) else data.copy()
        df['period'] = pd.to_datetime(df['period'])

        title = title or "Brazil Agricultural Exports Comparison"
        filename = filename or "brazil_commodity_comparison"

        fig, ax = self._setup_figure(title, (14, 8))

        for commodity in commodities:
            commodity_data = df[df['commodity'] == commodity].sort_values('period')
            if len(commodity_data) > 0:
                color = COMMODITY_COLORS.get(commodity, '#888888')
                ax.plot(
                    commodity_data['period'],
                    commodity_data['quantity_mt'] / 1000,
                    label=commodity.replace('_', ' ').title(),
                    color=color,
                    linewidth=2,
                    marker='o',
                    markersize=3
                )

        ax.set_ylabel('Volume (Thousand MT)', fontsize=self.config.label_fontsize)
        ax.set_xlabel('Period', fontsize=self.config.label_fontsize)
        ax.legend(loc='upper left', bbox_to_anchor=(1, 1))
        ax.xaxis.set_major_locator(mdates.YearLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
        ax.grid(True, alpha=0.3)

        return self._save_figure(fig, filename, 'multi_commodity')

    # =========================================================================
    # DESTINATION/MARKET ANALYSIS CHARTS
    # =========================================================================

    def plot_top_destinations(
        self,
        data: Union[pd.DataFrame, List[Dict]],
        commodity: str,
        year: int,
        top_n: int = 10,
        title: str = None,
        filename: str = None
    ) -> VisualizationResult:
        """
        Create horizontal bar chart of top export destinations.

        Args:
            data: DataFrame with columns: country_name, quantity_mt, value_usd
            commodity: Commodity name
            year: Year for data
            top_n: Number of top destinations to show
            title: Chart title
            filename: Output filename

        Returns:
            VisualizationResult with chart
        """
        if not MATPLOTLIB_AVAILABLE or not PANDAS_AVAILABLE:
            return VisualizationResult(
                success=False,
                chart_type='top_destinations',
                error_message="matplotlib or pandas not available"
            )

        df = pd.DataFrame(data) if isinstance(data, list) else data.copy()

        # Aggregate by country
        country_totals = df.groupby('country_name').agg({
            'quantity_mt': 'sum',
            'value_fob_usd': 'sum'
        }).reset_index()

        # Sort and take top N
        country_totals = country_totals.nlargest(top_n, 'quantity_mt')
        country_totals = country_totals.sort_values('quantity_mt', ascending=True)

        title = title or f"Top {top_n} Destinations for Brazil {commodity.replace('_', ' ').title()} Exports ({year})"
        filename = filename or f"brazil_{commodity}_top_destinations_{year}"

        fig, ax = self._setup_figure(title, (12, 8))

        color = COMMODITY_COLORS.get(commodity, '#1976D2')

        bars = ax.barh(
            country_totals['country_name'],
            country_totals['quantity_mt'] / 1_000_000,  # Convert to MMT
            color=color,
            alpha=0.8
        )

        # Add value labels
        for bar, value in zip(bars, country_totals['quantity_mt']):
            ax.text(
                bar.get_width() + 0.05,
                bar.get_y() + bar.get_height() / 2,
                f'{value / 1_000_000:.2f} MMT',
                va='center',
                fontsize=9
            )

        ax.set_xlabel('Volume (Million MT)', fontsize=self.config.label_fontsize)
        ax.set_ylabel('Destination Country', fontsize=self.config.label_fontsize)
        ax.grid(True, alpha=0.3, axis='x')

        return self._save_figure(fig, filename, 'top_destinations')

    def plot_market_share_pie(
        self,
        data: Union[pd.DataFrame, List[Dict]],
        commodity: str,
        year: int,
        top_n: int = 8,
        title: str = None,
        filename: str = None
    ) -> VisualizationResult:
        """
        Create pie chart showing market share by destination.

        Args:
            data: DataFrame with columns: country_name, quantity_mt
            commodity: Commodity name
            year: Year for data
            top_n: Number of countries to show (rest grouped as "Others")
            title: Chart title
            filename: Output filename

        Returns:
            VisualizationResult with chart
        """
        if not MATPLOTLIB_AVAILABLE or not PANDAS_AVAILABLE:
            return VisualizationResult(
                success=False,
                chart_type='market_share',
                error_message="matplotlib or pandas not available"
            )

        df = pd.DataFrame(data) if isinstance(data, list) else data.copy()

        # Aggregate by country
        country_totals = df.groupby('country_name')['quantity_mt'].sum().reset_index()
        country_totals = country_totals.sort_values('quantity_mt', ascending=False)

        # Get top N and group others
        top_countries = country_totals.head(top_n)
        others_total = country_totals.iloc[top_n:]['quantity_mt'].sum()

        if others_total > 0:
            others_row = pd.DataFrame([{'country_name': 'Others', 'quantity_mt': others_total}])
            top_countries = pd.concat([top_countries, others_row], ignore_index=True)

        title = title or f"Brazil {commodity.replace('_', ' ').title()} Export Market Share ({year})"
        filename = filename or f"brazil_{commodity}_market_share_{year}"

        fig, ax = self._setup_figure(title, (10, 10))

        # Create color palette
        colors = plt.cm.Set3(range(len(top_countries)))

        wedges, texts, autotexts = ax.pie(
            top_countries['quantity_mt'],
            labels=top_countries['country_name'],
            autopct=lambda pct: f'{pct:.1f}%' if pct > 3 else '',
            colors=colors,
            startangle=90,
            explode=[0.02] * len(top_countries)
        )

        # Style text
        for autotext in autotexts:
            autotext.set_fontsize(9)
            autotext.set_fontweight('bold')

        ax.axis('equal')

        return self._save_figure(fig, filename, 'market_share')

    # =========================================================================
    # SEASONALITY CHARTS
    # =========================================================================

    def plot_seasonality_heatmap(
        self,
        data: Union[pd.DataFrame, List[Dict]],
        commodity: str,
        title: str = None,
        filename: str = None
    ) -> VisualizationResult:
        """
        Create heatmap showing monthly export patterns across years.

        Args:
            data: DataFrame with columns: year, month, quantity_mt
            commodity: Commodity name
            title: Chart title
            filename: Output filename

        Returns:
            VisualizationResult with chart
        """
        if not MATPLOTLIB_AVAILABLE or not PANDAS_AVAILABLE or not NUMPY_AVAILABLE:
            return VisualizationResult(
                success=False,
                chart_type='seasonality_heatmap',
                error_message="matplotlib, pandas, or numpy not available"
            )

        df = pd.DataFrame(data) if isinstance(data, list) else data.copy()

        # Aggregate by year and month
        monthly = df.groupby(['year', 'month'])['quantity_mt'].sum().reset_index()

        # Pivot for heatmap
        pivot = monthly.pivot(index='month', columns='year', values='quantity_mt')
        pivot = pivot / 1000  # Convert to TMT

        title = title or f"Brazil {commodity.replace('_', ' ').title()} Export Seasonality"
        filename = filename or f"brazil_{commodity}_seasonality"

        fig, ax = plt.subplots(figsize=(14, 8), dpi=self.config.figure_dpi)

        # Create custom colormap (green-based for Brazil theme)
        colors = ['#E8F5E9', '#C8E6C9', '#A5D6A7', '#81C784', '#66BB6A', '#4CAF50', '#43A047', '#388E3C', '#2E7D32']
        cmap = LinearSegmentedColormap.from_list('brazil_green', colors)

        im = ax.imshow(pivot.values, cmap=cmap, aspect='auto')

        # Labels
        month_labels = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                       'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        ax.set_yticks(range(len(pivot.index)))
        ax.set_yticklabels([month_labels[m-1] for m in pivot.index])
        ax.set_xticks(range(len(pivot.columns)))
        ax.set_xticklabels(pivot.columns)

        # Add value annotations
        for i in range(len(pivot.index)):
            for j in range(len(pivot.columns)):
                value = pivot.iloc[i, j]
                if not np.isnan(value):
                    text_color = 'white' if value > pivot.values.max() * 0.6 else 'black'
                    ax.text(j, i, f'{value:.0f}',
                           ha='center', va='center',
                           fontsize=8, color=text_color)

        # Colorbar
        cbar = plt.colorbar(im, ax=ax, label='Volume (Thousand MT)')

        ax.set_title(title, fontsize=self.config.title_fontsize, fontweight='bold')
        ax.set_xlabel('Year', fontsize=self.config.label_fontsize)
        ax.set_ylabel('Month', fontsize=self.config.label_fontsize)

        return self._save_figure(fig, filename, 'seasonality_heatmap')

    def plot_monthly_seasonal_pattern(
        self,
        data: Union[pd.DataFrame, List[Dict]],
        commodity: str,
        title: str = None,
        filename: str = None
    ) -> VisualizationResult:
        """
        Create chart showing average monthly pattern (seasonal index).

        Args:
            data: DataFrame with columns: month, avg_mt or quantity_mt
            commodity: Commodity name
            title: Chart title
            filename: Output filename

        Returns:
            VisualizationResult with chart
        """
        if not MATPLOTLIB_AVAILABLE or not PANDAS_AVAILABLE:
            return VisualizationResult(
                success=False,
                chart_type='seasonal_pattern',
                error_message="matplotlib or pandas not available"
            )

        df = pd.DataFrame(data) if isinstance(data, list) else data.copy()

        # Calculate monthly averages if needed
        if 'avg_mt' not in df.columns:
            monthly_avg = df.groupby('month')['quantity_mt'].mean().reset_index()
            monthly_avg.columns = ['month', 'avg_mt']
        else:
            monthly_avg = df[['month', 'avg_mt']].drop_duplicates()

        # Calculate seasonal index (relative to annual average)
        annual_avg = monthly_avg['avg_mt'].mean()
        monthly_avg['seasonal_index'] = monthly_avg['avg_mt'] / annual_avg * 100

        title = title or f"Brazil {commodity.replace('_', ' ').title()} Export Seasonal Pattern"
        filename = filename or f"brazil_{commodity}_seasonal_pattern"

        fig, ax = self._setup_figure(title, (12, 6))

        months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

        color = COMMODITY_COLORS.get(commodity, '#4CAF50')

        # Bar chart
        bars = ax.bar(
            range(1, 13),
            monthly_avg['seasonal_index'],
            color=color,
            alpha=0.7,
            edgecolor=color
        )

        # Add average line
        ax.axhline(y=100, color='red', linestyle='--', linewidth=2, label='Annual Average')

        # Labels
        ax.set_xticks(range(1, 13))
        ax.set_xticklabels(months)
        ax.set_ylabel('Seasonal Index (Average = 100)', fontsize=self.config.label_fontsize)
        ax.set_xlabel('Month', fontsize=self.config.label_fontsize)
        ax.legend()
        ax.grid(True, alpha=0.3, axis='y')

        # Add value labels on bars
        for bar in bars:
            height = bar.get_height()
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                height + 2,
                f'{height:.0f}',
                ha='center',
                va='bottom',
                fontsize=9
            )

        return self._save_figure(fig, filename, 'seasonal_pattern')

    # =========================================================================
    # STATE-LEVEL ANALYSIS
    # =========================================================================

    def plot_state_contributions(
        self,
        data: Union[pd.DataFrame, List[Dict]],
        commodity: str,
        year: int,
        top_n: int = 10,
        title: str = None,
        filename: str = None
    ) -> VisualizationResult:
        """
        Create chart showing state-level export contributions.

        Args:
            data: DataFrame with columns: state_name, quantity_mt
            commodity: Commodity name
            year: Year for data
            top_n: Number of states to show
            title: Chart title
            filename: Output filename

        Returns:
            VisualizationResult with chart
        """
        if not MATPLOTLIB_AVAILABLE or not PANDAS_AVAILABLE:
            return VisualizationResult(
                success=False,
                chart_type='state_contributions',
                error_message="matplotlib or pandas not available"
            )

        df = pd.DataFrame(data) if isinstance(data, list) else data.copy()

        # Aggregate by state
        state_totals = df.groupby('state_name')['quantity_mt'].sum().reset_index()
        state_totals = state_totals.nlargest(top_n, 'quantity_mt')
        state_totals = state_totals.sort_values('quantity_mt', ascending=True)

        # Calculate percentages
        total = state_totals['quantity_mt'].sum()
        state_totals['pct'] = state_totals['quantity_mt'] / total * 100

        title = title or f"Top {top_n} Brazilian States - {commodity.replace('_', ' ').title()} Exports ({year})"
        filename = filename or f"brazil_{commodity}_states_{year}"

        fig, ax = self._setup_figure(title, (12, 8))

        # Create gradient colors
        colors = plt.cm.Greens(np.linspace(0.3, 0.9, len(state_totals)))

        bars = ax.barh(
            state_totals['state_name'],
            state_totals['quantity_mt'] / 1_000_000,  # Convert to MMT
            color=colors,
            edgecolor='darkgreen',
            linewidth=0.5
        )

        # Add value labels
        for bar, pct in zip(bars, state_totals['pct']):
            ax.text(
                bar.get_width() + 0.05,
                bar.get_y() + bar.get_height() / 2,
                f'{bar.get_width():.2f} MMT ({pct:.1f}%)',
                va='center',
                fontsize=9
            )

        ax.set_xlabel('Volume (Million MT)', fontsize=self.config.label_fontsize)
        ax.set_ylabel('State', fontsize=self.config.label_fontsize)
        ax.grid(True, alpha=0.3, axis='x')

        return self._save_figure(fig, filename, 'state_contributions')

    # =========================================================================
    # PRICE ANALYSIS
    # =========================================================================

    def plot_price_trends(
        self,
        data: Union[pd.DataFrame, List[Dict]],
        commodity: str,
        title: str = None,
        filename: str = None
    ) -> VisualizationResult:
        """
        Create chart showing export price trends (USD/MT).

        Args:
            data: DataFrame with columns: period, avg_price_usd_mt or calculated from value/quantity
            commodity: Commodity name
            title: Chart title
            filename: Output filename

        Returns:
            VisualizationResult with chart
        """
        if not MATPLOTLIB_AVAILABLE or not PANDAS_AVAILABLE:
            return VisualizationResult(
                success=False,
                chart_type='price_trends',
                error_message="matplotlib or pandas not available"
            )

        df = pd.DataFrame(data) if isinstance(data, list) else data.copy()
        df['period'] = pd.to_datetime(df['period'])
        df = df.sort_values('period')

        # Calculate price if not present
        if 'avg_price_usd_mt' not in df.columns:
            if 'value_fob_usd' in df.columns and 'quantity_mt' in df.columns:
                df['avg_price_usd_mt'] = df['value_fob_usd'] / df['quantity_mt']
            else:
                return VisualizationResult(
                    success=False,
                    chart_type='price_trends',
                    error_message="Cannot calculate price - missing columns"
                )

        title = title or f"Brazil {commodity.replace('_', ' ').title()} Export Prices"
        filename = filename or f"brazil_{commodity}_prices"

        fig, ax = self._setup_figure(title, (12, 6))

        color = COMMODITY_COLORS.get(commodity, '#1976D2')

        ax.plot(
            df['period'],
            df['avg_price_usd_mt'],
            color=color,
            linewidth=2,
            marker='o',
            markersize=4
        )

        # Add trend line
        if NUMPY_AVAILABLE and len(df) > 2:
            z = np.polyfit(range(len(df)), df['avg_price_usd_mt'].fillna(0), 1)
            p = np.poly1d(z)
            ax.plot(df['period'], p(range(len(df))),
                   color='red', linestyle='--', alpha=0.5, label='Trend')
            ax.legend()

        ax.set_ylabel('Average Price (USD/MT)', fontsize=self.config.label_fontsize)
        ax.set_xlabel('Period', fontsize=self.config.label_fontsize)
        ax.xaxis.set_major_locator(mdates.YearLocator())
        ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
        ax.grid(True, alpha=0.3)

        return self._save_figure(fig, filename, 'price_trends')

    # =========================================================================
    # DASHBOARD / SUMMARY CHARTS
    # =========================================================================

    def create_commodity_dashboard(
        self,
        data: Union[pd.DataFrame, List[Dict]],
        commodity: str,
        year: int = None,
        filename: str = None
    ) -> VisualizationResult:
        """
        Create a comprehensive dashboard with multiple charts for a commodity.

        Args:
            data: Complete trade data for the commodity
            commodity: Commodity name
            year: Year for point-in-time analysis (default: most recent)
            filename: Output filename

        Returns:
            VisualizationResult with dashboard image
        """
        if not MATPLOTLIB_AVAILABLE or not PANDAS_AVAILABLE:
            return VisualizationResult(
                success=False,
                chart_type='dashboard',
                error_message="matplotlib or pandas not available"
            )

        df = pd.DataFrame(data) if isinstance(data, list) else data.copy()

        year = year or df['year'].max()
        filename = filename or f"brazil_{commodity}_dashboard_{year}"

        # Create figure with subplots
        fig = plt.figure(figsize=(16, 12), dpi=self.config.figure_dpi)

        # Title
        fig.suptitle(
            f"Brazil {commodity.replace('_', ' ').title()} Export Dashboard ({year})",
            fontsize=16,
            fontweight='bold',
            y=0.98
        )

        # Create grid spec
        gs = fig.add_gridspec(2, 2, hspace=0.3, wspace=0.3)

        color = COMMODITY_COLORS.get(commodity, '#4CAF50')

        # 1. Monthly volume trend (top left)
        ax1 = fig.add_subplot(gs[0, 0])
        monthly = df.groupby('period')['quantity_mt'].sum().reset_index()
        monthly['period'] = pd.to_datetime(monthly['period'])
        monthly = monthly.sort_values('period')
        ax1.fill_between(monthly['period'], monthly['quantity_mt'] / 1000, alpha=0.3, color=color)
        ax1.plot(monthly['period'], monthly['quantity_mt'] / 1000, color=color, linewidth=2)
        ax1.set_title('Monthly Export Volume', fontweight='bold')
        ax1.set_ylabel('Volume (TMT)')
        ax1.grid(True, alpha=0.3)

        # 2. Top destinations (top right)
        ax2 = fig.add_subplot(gs[0, 1])
        year_data = df[df['year'] == year]
        if len(year_data) > 0:
            country_totals = year_data.groupby('country_name')['quantity_mt'].sum().nlargest(5)
            ax2.barh(country_totals.index, country_totals.values / 1_000_000, color=color, alpha=0.7)
            ax2.set_title(f'Top 5 Destinations ({year})', fontweight='bold')
            ax2.set_xlabel('Volume (MMT)')
        ax2.grid(True, alpha=0.3, axis='x')

        # 3. State contributions (bottom left)
        ax3 = fig.add_subplot(gs[1, 0])
        if len(year_data) > 0 and 'state_name' in year_data.columns:
            state_totals = year_data.groupby('state_name')['quantity_mt'].sum().nlargest(5)
            ax3.pie(
                state_totals.values,
                labels=state_totals.index,
                autopct='%1.1f%%',
                colors=plt.cm.Greens(np.linspace(0.3, 0.9, len(state_totals)))
            )
            ax3.set_title(f'Top 5 States ({year})', fontweight='bold')

        # 4. Price trend (bottom right)
        ax4 = fig.add_subplot(gs[1, 1])
        if 'value_fob_usd' in monthly.columns:
            monthly_price = df.groupby('period').agg({
                'value_fob_usd': 'sum',
                'quantity_mt': 'sum'
            }).reset_index()
            monthly_price['avg_price'] = monthly_price['value_fob_usd'] / monthly_price['quantity_mt']
            monthly_price['period'] = pd.to_datetime(monthly_price['period'])
            monthly_price = monthly_price.sort_values('period')
            ax4.plot(monthly_price['period'], monthly_price['avg_price'], color=color, linewidth=2)
            ax4.set_title('Average Export Price', fontweight='bold')
            ax4.set_ylabel('USD/MT')
            ax4.grid(True, alpha=0.3)

        return self._save_figure(fig, filename, 'dashboard')

    # =========================================================================
    # REPORT GENERATION
    # =========================================================================

    def generate_all_visualizations(
        self,
        data: Union[pd.DataFrame, List[Dict]],
        commodities: List[str] = None,
        year: int = None
    ) -> Dict[str, VisualizationResult]:
        """
        Generate a complete set of visualizations for multiple commodities.

        Args:
            data: Complete trade data
            commodities: List of commodities to visualize
            year: Year for analysis

        Returns:
            Dict mapping chart name to VisualizationResult
        """
        results = {}
        df = pd.DataFrame(data) if isinstance(data, list) else data.copy()

        year = year or df['year'].max()
        commodities = commodities or df['commodity'].unique().tolist()

        self.logger.info(f"Generating visualizations for {len(commodities)} commodities, year {year}")

        for commodity in commodities:
            commodity_data = df[df['commodity'] == commodity]

            if len(commodity_data) == 0:
                self.logger.warning(f"No data for {commodity}")
                continue

            # Generate each chart type
            try:
                # Dashboard
                key = f"{commodity}_dashboard"
                results[key] = self.create_commodity_dashboard(commodity_data, commodity, year)
                self.logger.info(f"Generated {key}: {'success' if results[key].success else 'failed'}")

                # Export trends
                key = f"{commodity}_trends"
                monthly = commodity_data.groupby('period').agg({
                    'quantity_mt': 'sum',
                    'value_fob_usd': 'sum'
                }).reset_index()
                results[key] = self.plot_export_trends(monthly, commodity)

                # Top destinations
                key = f"{commodity}_destinations"
                year_data = commodity_data[commodity_data['year'] == year]
                if len(year_data) > 0:
                    results[key] = self.plot_top_destinations(year_data, commodity, year)

                # Seasonality
                key = f"{commodity}_seasonality"
                results[key] = self.plot_seasonality_heatmap(commodity_data, commodity)

            except Exception as e:
                self.logger.error(f"Error generating visualizations for {commodity}: {e}")

        return results


# =============================================================================
# CLI INTERFACE
# =============================================================================

def main():
    """Command-line interface for Brazil trade visualizations"""
    import argparse

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    parser = argparse.ArgumentParser(description='Brazil Trade Data Visualizations')

    parser.add_argument(
        '--input', '-i',
        required=True,
        help='Input data file (CSV or JSON)'
    )

    parser.add_argument(
        '--commodity',
        default='soybeans',
        help='Commodity to visualize'
    )

    parser.add_argument(
        '--year',
        type=int,
        default=None,
        help='Year for analysis'
    )

    parser.add_argument(
        '--output-dir', '-o',
        default='./reports/visualizations',
        help='Output directory for charts'
    )

    parser.add_argument(
        '--chart-type',
        choices=['dashboard', 'trends', 'destinations', 'seasonality', 'all'],
        default='dashboard',
        help='Type of chart to generate'
    )

    args = parser.parse_args()

    # Load data
    input_path = Path(args.input)
    if input_path.suffix == '.csv':
        data = pd.read_csv(input_path)
    else:
        data = pd.read_json(input_path)

    # Configure visualizer
    config = VisualizationConfig(output_dir=Path(args.output_dir))
    visualizer = BrazilTradeVisualizer(config)

    # Generate visualizations
    if args.chart_type == 'all':
        results = visualizer.generate_all_visualizations(
            data,
            commodities=[args.commodity],
            year=args.year
        )
        for name, result in results.items():
            status = 'SUCCESS' if result.success else 'FAILED'
            print(f"{name}: {status}")
            if result.file_path:
                print(f"  -> {result.file_path}")

    elif args.chart_type == 'dashboard':
        result = visualizer.create_commodity_dashboard(data, args.commodity, args.year)
        print(f"Dashboard: {'SUCCESS' if result.success else 'FAILED'}")
        if result.file_path:
            print(f"Saved to: {result.file_path}")

    elif args.chart_type == 'trends':
        monthly = data.groupby('period').agg({
            'quantity_mt': 'sum',
            'value_fob_usd': 'sum'
        }).reset_index()
        result = visualizer.plot_export_trends(monthly, args.commodity)
        print(f"Trends: {'SUCCESS' if result.success else 'FAILED'}")
        if result.file_path:
            print(f"Saved to: {result.file_path}")


if __name__ == '__main__':
    main()
