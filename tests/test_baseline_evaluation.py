"""Unit tests for baseline evaluation metrics and result equivalence."""

import pandas as pd
from decimal import Decimal
from scripts.evaluate_baseline_a import are_results_equivalent


def test_equivalence_scalar_ints():
    df1 = pd.DataFrame([{"total": 100}])
    df2 = pd.DataFrame([{"count": 100}])
    assert are_results_equivalent(df1, df2) is True


def test_equivalence_scalar_floats_and_decimals():
    df1 = pd.DataFrame([{"avg_score": Decimal("4.11")}])
    df2 = pd.DataFrame([{"score": 4.11}])
    assert are_results_equivalent(df1, df2) is True


def test_equivalence_empty_dataframes():
    df1 = pd.DataFrame()
    df2 = pd.DataFrame()
    assert are_results_equivalent(df1, df2) is True


def test_equivalence_multi_row():
    df1 = pd.DataFrame([
        {"status": "delivered", "count": 85},
        {"status": "shipped", "count": 8}
    ])
    df2 = pd.DataFrame([
        {"order_status": "shipped", "n": 8},
        {"order_status": "delivered", "n": 85}
    ])
    assert are_results_equivalent(df1, df2) is True


def test_equivalence_mismatch():
    df1 = pd.DataFrame([{"val": 10}])
    df2 = pd.DataFrame([{"val": 20}])
    assert are_results_equivalent(df1, df2) is False
