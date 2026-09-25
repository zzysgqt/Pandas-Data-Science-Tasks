"""Reproducible extension of Keith Galli's Pandas sales analysis project.

The script keeps the upstream tutorial intact and writes all derived artifacts to
``extended_analysis/outputs`` and ``extended_analysis/figures``.  Figures use a
non-interactive backend, so running the script never opens GUI windows.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
ANALYSIS_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT / "SalesAnalysis" / "Sales_Data"
OUTPUT_DIR = ANALYSIS_DIR / "outputs"
FIGURE_DIR = ANALYSIS_DIR / "figures"

DUPLICATE_KEYS = [
    "Order ID",
    "Product",
    "Quantity Ordered",
    "Price Each",
    "Order Date",
    "Purchase Address",
]


def load_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Load all monthly files and return valid source rows and strict 2019 rows."""
    files = sorted(DATA_DIR.glob("Sales_*.csv"))
    if len(files) != 12:
        raise FileNotFoundError(
            f"Expected 12 monthly CSV files in {DATA_DIR}, found {len(files)}."
        )

    source = pd.concat(
        [pd.read_csv(path) for path in files],
        ignore_index=True,
    )
    source = source.dropna(how="all")
    source = source[source["Order Date"].ne("Order Date")].copy()

    source["Order ID"] = source["Order ID"].astype(str).str.strip()
    source["Quantity Ordered"] = pd.to_numeric(source["Quantity Ordered"])
    source["Price Each"] = pd.to_numeric(source["Price Each"])
    source["Order Date"] = pd.to_datetime(
        source["Order Date"],
        format="%m/%d/%y %H:%M",
    )
    source["Sales"] = source["Quantity Ordered"] * source["Price Each"]

    df_2019 = source[source["Order Date"].dt.year.eq(2019)].copy()
    df_2019["Month"] = df_2019["Order Date"].dt.month
    df_2019["Hour"] = df_2019["Order Date"].dt.hour

    address_parts = df_2019["Purchase Address"].str.split(",")
    df_2019["City"] = address_parts.str[1].str.strip()
    df_2019["State"] = (
        address_parts.str[2].str.strip().str.split().str[0]
    )
    df_2019["City Label"] = (
        df_2019["City"] + " (" + df_2019["State"] + ")"
    )
    return source, df_2019


def audit_duplicates(
    source: pd.DataFrame,
    df_2019: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, int | float]]:
    """Audit exact source-row duplicates and return a deduplicated 2019 table."""
    all_duplicate_rows = df_2019.duplicated(
        subset=DUPLICATE_KEYS,
        keep=False,
    )
    extra_duplicate_rows = df_2019.duplicated(
        subset=DUPLICATE_KEYS,
        keep="first",
    )
    removed = df_2019.loc[extra_duplicate_rows]
    clean = df_2019.loc[~extra_duplicate_rows].copy()

    metrics: dict[str, int | float] = {
        "valid_source_rows": int(len(source)),
        "strict_2019_rows": int(len(df_2019)),
        "duplicate_participating_rows": int(all_duplicate_rows.sum()),
        "extra_duplicate_rows": int(extra_duplicate_rows.sum()),
        "affected_order_ids": int(
            df_2019.loc[all_duplicate_rows, "Order ID"].nunique()
        ),
        "duplicated_units": int(removed["Quantity Ordered"].sum()),
        "duplicated_sales": round(float(removed["Sales"].sum()), 2),
        "duplicated_sales_rate_percent": round(
            float(removed["Sales"].sum() / df_2019["Sales"].sum() * 100),
            4,
        ),
        "clean_2019_rows": int(len(clean)),
        "unique_orders_before": int(df_2019["Order ID"].nunique()),
        "unique_orders_after": int(clean["Order ID"].nunique()),
        "sales_before": round(float(df_2019["Sales"].sum()), 2),
        "sales_after": round(float(clean["Sales"].sum()), 2),
    }
    return clean, metrics


def build_product_tables(
    df_2019: pd.DataFrame,
    clean: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Build duplicate impact, product performance, role and type tables."""
    sales_before = (
        df_2019.groupby("Product")["Sales"].sum().rename("SalesBefore")
    )
    sales_after = clean.groupby("Product")["Sales"].sum().rename("SalesAfter")
    product_impact = pd.concat([sales_before, sales_after], axis=1)
    product_impact["OverstatedSales"] = (
        product_impact["SalesBefore"] - product_impact["SalesAfter"]
    )
    product_impact["OverstatedRate (%)"] = (
        product_impact["OverstatedSales"]
        / product_impact["SalesBefore"]
        * 100
    )
    product_impact = product_impact.sort_values(
        "OverstatedSales",
        ascending=False,
    )

    product_performance = clean.groupby("Product").agg(
        Orders=("Order ID", "nunique"),
        Units=("Quantity Ordered", "sum"),
        Sales=("Sales", "sum"),
    )
    product_performance["AvgPrice"] = (
        product_performance["Sales"] / product_performance["Units"]
    )
    product_performance["SalesShare (%)"] = (
        product_performance["Sales"] / product_performance["Sales"].sum() * 100
    )
    product_performance = product_performance.sort_values(
        "Sales",
        ascending=False,
    )
    product_performance["CumulativeSalesShare (%)"] = (
        product_performance["SalesShare (%)"].cumsum()
    )

    product_roles = product_performance[["Orders", "Units", "Sales", "AvgPrice"]].copy()
    product_roles["SalesRank"] = (
        product_roles["Sales"].rank(method="min", ascending=False).astype(int)
    )
    product_roles["UnitsRank"] = (
        product_roles["Units"].rank(method="min", ascending=False).astype(int)
    )
    product_roles["RankGap"] = (
        product_roles["UnitsRank"] - product_roles["SalesRank"]
    )

    median_price = product_roles["AvgPrice"].median()
    median_units = product_roles["Units"].median()

    def classify_product(row: pd.Series) -> str:
        high_price = row["AvgPrice"] >= median_price
        high_units = row["Units"] >= median_units
        if high_price and high_units:
            return "高价高销量"
        if high_price:
            return "高价低销量"
        if high_units:
            return "低价高销量"
        return "低价低销量"

    product_roles["ProductType"] = product_roles.apply(classify_product, axis=1)

    type_summary = product_roles.groupby("ProductType").agg(
        ProductCount=("Sales", "size"),
        Units=("Units", "sum"),
        Sales=("Sales", "sum"),
    )
    type_summary["UnitShare (%)"] = (
        type_summary["Units"] / type_summary["Units"].sum() * 100
    )
    type_summary["SalesShare (%)"] = (
        type_summary["Sales"] / type_summary["Sales"].sum() * 100
    )
    type_summary["SalesPerUnit"] = type_summary["Sales"] / type_summary["Units"]
    type_summary["SalesPerProduct"] = (
        type_summary["Sales"] / type_summary["ProductCount"]
    )
    type_summary["UnitsPerProduct"] = (
        type_summary["Units"] / type_summary["ProductCount"]
    )
    type_summary = type_summary.sort_values("Sales", ascending=False)

    return product_impact, product_performance, product_roles, type_summary


def build_inventory_tables(
    clean: pd.DataFrame,
    product_roles: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, list[str]]:
    """Compare three illustrative two-week reorder-point approaches."""
    focus_products = product_roles.index[
        product_roles["ProductType"].eq("高价高销量")
    ].tolist()

    focus_weekly = (
        clean[clean["Product"].isin(focus_products)]
        .sort_values("Order Date")
        .set_index("Order Date")
        .groupby("Product")["Quantity Ordered"]
        .resample("W")
        .sum()
        .rename("Units")
        .reset_index()
    )
    inventory_profile = focus_weekly.groupby("Product")["Units"].agg(
        WeeksObserved="count",
        WeeklyMean="mean",
        WeeklyStd="std",
        WeeklyMin="min",
        WeeklyMax="max",
    )
    inventory_profile["WeeklyCV (%)"] = (
        inventory_profile["WeeklyStd"] / inventory_profile["WeeklyMean"] * 100
    )
    inventory_profile["PeakToMean"] = (
        inventory_profile["WeeklyMax"] / inventory_profile["WeeklyMean"]
    )
    inventory_profile["WeeklyRange"] = (
        inventory_profile["WeeklyMax"] - inventory_profile["WeeklyMin"]
    )

    weekly_pivot = focus_weekly.pivot(
        index="Order Date",
        columns="Product",
        values="Units",
    ).fillna(0)
    two_week_demand = weekly_pivot.rolling(window=2).sum().dropna()

    lead_time_weeks = 2
    service_level_z = 1.645
    original_rop = (
        inventory_profile["WeeklyMean"] * lead_time_weeks
        + service_level_z
        * inventory_profile["WeeklyStd"]
        * np.sqrt(lead_time_weeks)
    )
    adjusted_rop = two_week_demand.mean() + service_level_z * two_week_demand.std()
    empirical_p95 = two_week_demand.quantile(0.95)

    def coverage(thresholds: pd.Series) -> pd.Series:
        return pd.Series(
            {
                product: float(
                    (two_week_demand[product] <= thresholds[product]).mean() * 100
                )
                for product in focus_products
            }
        )

    method_comparison = pd.DataFrame(
        {
            "OriginalFormulaROP": original_rop,
            "CorrelationAdjustedROP": adjusted_rop,
            "EmpiricalP95ROP": empirical_p95,
            "OriginalCoverage (%)": coverage(original_rop),
            "AdjustedCoverage (%)": coverage(adjusted_rop),
            "EmpiricalCoverage (%)": coverage(empirical_p95),
        }
    )

    diagnostics = pd.DataFrame(
        {
            "WeeklySkewness": weekly_pivot.skew(),
            "Lag1Autocorrelation": weekly_pivot.apply(
                lambda series: series.autocorr(lag=1)
            ),
            "IndependentTwoWeekStd": inventory_profile["WeeklyStd"] * np.sqrt(2),
            "ActualTwoWeekStd": two_week_demand.std(),
        }
    )
    diagnostics["StdDifference"] = (
        diagnostics["ActualTwoWeekStd"] - diagnostics["IndependentTwoWeekStd"]
    )
    diagnostics["StdRatio"] = (
        diagnostics["ActualTwoWeekStd"] / diagnostics["IndependentTwoWeekStd"]
    )

    return (
        focus_weekly,
        inventory_profile,
        method_comparison,
        diagnostics,
        focus_products,
    )


def build_city_tables(
    clean: pd.DataFrame,
    focus_products: list[str],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Decompose top-city sales into order count and units per order."""
    focus_city = (
        clean[clean["Product"].isin(focus_products)]
        .groupby(["Product", "City Label"])
        .agg(
            Orders=("Order ID", "nunique"),
            Units=("Quantity Ordered", "sum"),
            Sales=("Sales", "sum"),
        )
    )
    focus_city["SalesPerOrder"] = focus_city["Sales"] / focus_city["Orders"]
    focus_city["SalesShareWithinProduct (%)"] = (
        focus_city.groupby(level=0)["Sales"].transform(
            lambda values: values / values.sum() * 100
        )
    )
    focus_city["CityRank"] = (
        focus_city.groupby(level=0)["Sales"]
        .rank(method="min", ascending=False)
        .astype(int)
    )
    focus_city["UnitsPerOrder"] = focus_city["Units"] / focus_city["Orders"]
    focus_city["OrderShareWithinProduct (%)"] = (
        focus_city.groupby(level=0)["Orders"].transform(
            lambda values: values / values.sum() * 100
        )
    )
    product_avg_units_per_order = (
        focus_city.groupby(level=0)["Units"].sum()
        / focus_city.groupby(level=0)["Orders"].sum()
    )
    focus_city["ProductAvgUnitsPerOrder"] = (
        focus_city.index.get_level_values("Product").map(product_avg_units_per_order)
    )
    focus_city["UnitsPerOrderIndex"] = (
        focus_city["UnitsPerOrder"]
        / focus_city["ProductAvgUnitsPerOrder"]
        * 100
    )
    top_three = focus_city[focus_city["CityRank"].le(3)].sort_values(
        ["Product", "CityRank"]
    )
    top_drivers = focus_city[focus_city["CityRank"].eq(1)].copy()
    return top_three, top_drivers


def save_figures(
    product_performance: pd.DataFrame,
    method_comparison: pd.DataFrame,
) -> None:
    """Save two portfolio figures without opening interactive windows."""
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)

    fig, axis = plt.subplots(figsize=(12, 6))
    positions = np.arange(len(product_performance))
    axis.bar(
        positions,
        product_performance["SalesShare (%)"],
        color="#3b82f6",
        label="Sales share",
    )
    axis.set_ylabel("Sales share (%)")
    axis.set_xticks(positions)
    axis.set_xticklabels(product_performance.index, rotation=70, ha="right")
    second_axis = axis.twinx()
    second_axis.plot(
        positions,
        product_performance["CumulativeSalesShare (%)"],
        color="#ef4444",
        marker="o",
        label="Cumulative share",
    )
    second_axis.axhline(80, color="#111827", linestyle="--", linewidth=1)
    second_axis.set_ylabel("Cumulative sales share (%)")
    axis.set_title("2019 product sales concentration after exact-row deduplication")
    fig.tight_layout()
    fig.savefig(FIGURE_DIR / "product_sales_concentration.png", dpi=160)
    plt.close(fig)

    comparison_columns = [
        "OriginalFormulaROP",
        "CorrelationAdjustedROP",
        "EmpiricalP95ROP",
    ]
    axis = method_comparison[comparison_columns].plot(
        kind="bar",
        figsize=(9, 5),
        color=["#94a3b8", "#3b82f6", "#f97316"],
    )
    axis.set_ylabel("Units")
    axis.set_xlabel("")
    axis.set_title("Illustrative two-week reorder-point estimates")
    axis.legend(["Independent normal", "Observed 2-week std", "Empirical P95"])
    axis.tick_params(axis="x", rotation=0)
    axis.figure.tight_layout()
    axis.figure.savefig(FIGURE_DIR / "inventory_reorder_point_comparison.png", dpi=160)
    plt.close(axis.figure)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    source, df_2019 = load_data()
    clean, metrics = audit_duplicates(source, df_2019)
    (
        product_impact,
        product_performance,
        product_roles,
        type_summary,
    ) = build_product_tables(df_2019, clean)
    (
        focus_weekly,
        inventory_profile,
        method_comparison,
        diagnostics,
        focus_products,
    ) = build_inventory_tables(clean, product_roles)
    top_three_cities, top_city_drivers = build_city_tables(clean, focus_products)

    products_to_80 = int(
        (product_performance["CumulativeSalesShare (%)"] < 80).sum() + 1
    )
    metrics.update(
        {
            "top_sales_product": str(product_performance.index[0]),
            "top_product_sales_share_percent": round(
                float(product_performance.iloc[0]["SalesShare (%)"]), 2
            ),
            "top_five_sales_share_percent": round(
                float(product_performance.iloc[:5]["SalesShare (%)"].sum()), 2
            ),
            "products_needed_for_80_percent_sales": products_to_80,
            "focus_products": focus_products,
        }
    )

    with (OUTPUT_DIR / "summary_metrics.json").open("w", encoding="utf-8") as handle:
        json.dump(metrics, handle, ensure_ascii=False, indent=2)

    tables = {
        "product_duplicate_impact.csv": product_impact,
        "product_performance.csv": product_performance,
        "product_roles.csv": product_roles,
        "product_type_summary.csv": type_summary,
        "focus_weekly_demand.csv": focus_weekly,
        "inventory_profile.csv": inventory_profile,
        "inventory_method_comparison.csv": method_comparison,
        "inventory_diagnostics.csv": diagnostics,
        "focus_top_three_cities.csv": top_three_cities,
        "focus_top_city_drivers.csv": top_city_drivers,
    }
    for filename, table in tables.items():
        table.to_csv(OUTPUT_DIR / filename, encoding="utf-8-sig")

    save_figures(product_performance, method_comparison)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
