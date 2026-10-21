"""Utilities for Streamlit-compatible DataFrames."""

import json
import pandas as pd


def normalize_dataframe(data):
    """Normalize mixed Python types for PyArrow."""

    df = (
        data.copy()
        if isinstance(data, pd.DataFrame)
        else pd.DataFrame(data)
    )

    if df.empty:
        return df

    for column in df.columns:

        if column == "status":
            df[column] = pd.to_numeric(
                df[column],
                errors="coerce"
            ).astype("Int64")
            continue

        if df[column].dtype == "object":

            def normalize(value):

                if isinstance(value, (list, dict, tuple)):
                    return json.dumps(
                        value,
                        ensure_ascii=False,
                        default=str
                    )

                if value is None:
                    return ""

                return str(value)

            df[column] = df[column].map(
                normalize
            ).astype("string")

    return df
