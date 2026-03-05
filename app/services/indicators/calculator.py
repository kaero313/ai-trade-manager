from typing import Any

import numpy as np
import pandas as pd
import pandas_ta_classic as ta


class IndicatorCalculator:
    REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")
    SMA_PERIODS = (5, 20, 60)
    EMA_PERIODS = (50, 200)
    BBANDS_LENGTH = 20
    BBANDS_STD = 2
    RSI_LENGTH = 14

    def __init__(self) -> None:
        self._ta = ta

    def to_dataframe(self, candles: list[dict[str, Any]]) -> pd.DataFrame:
        if not candles:
            return pd.DataFrame(columns=["timestamp", *self.REQUIRED_COLUMNS])

        df = pd.DataFrame(candles).copy()
        for column in self.REQUIRED_COLUMNS:
            if column not in df.columns:
                df[column] = pd.NA

        for column in self.REQUIRED_COLUMNS:
            df[column] = pd.to_numeric(df[column], errors="coerce")

        ordered_columns = [col for col in ["timestamp", *self.REQUIRED_COLUMNS] if col in df.columns]
        return df[ordered_columns]

    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        calculated = df.copy()
        if calculated.empty:
            for period in self.SMA_PERIODS:
                calculated[f"sma_{period}"] = pd.Series(dtype="float64")
            for period in self.EMA_PERIODS:
                calculated[f"ema_{period}"] = pd.Series(dtype="float64")
            calculated[f"bb_upper_{self.BBANDS_LENGTH}_{self.BBANDS_STD}"] = pd.Series(dtype="float64")
            calculated[f"bb_middle_{self.BBANDS_LENGTH}_{self.BBANDS_STD}"] = pd.Series(dtype="float64")
            calculated[f"bb_lower_{self.BBANDS_LENGTH}_{self.BBANDS_STD}"] = pd.Series(dtype="float64")
            calculated[f"rsi_{self.RSI_LENGTH}"] = pd.Series(dtype="float64")
            return calculated

        close_series = pd.to_numeric(calculated["close"], errors="coerce")

        for period in self.SMA_PERIODS:
            calculated[f"sma_{period}"] = self._ta.sma(close=close_series, length=period)
        for period in self.EMA_PERIODS:
            calculated[f"ema_{period}"] = self._ta.ema(close=close_series, length=period)

        bbands = self._ta.bbands(close=close_series, length=self.BBANDS_LENGTH, std=self.BBANDS_STD)
        if isinstance(bbands, pd.DataFrame) and not bbands.empty:
            calculated[f"bb_lower_{self.BBANDS_LENGTH}_{self.BBANDS_STD}"] = bbands.iloc[:, 0]
            calculated[f"bb_middle_{self.BBANDS_LENGTH}_{self.BBANDS_STD}"] = bbands.iloc[:, 1]
            calculated[f"bb_upper_{self.BBANDS_LENGTH}_{self.BBANDS_STD}"] = bbands.iloc[:, 2]
        else:
            calculated[f"bb_lower_{self.BBANDS_LENGTH}_{self.BBANDS_STD}"] = pd.Series(dtype="float64")
            calculated[f"bb_middle_{self.BBANDS_LENGTH}_{self.BBANDS_STD}"] = pd.Series(dtype="float64")
            calculated[f"bb_upper_{self.BBANDS_LENGTH}_{self.BBANDS_STD}"] = pd.Series(dtype="float64")

        calculated[f"rsi_{self.RSI_LENGTH}"] = self._ta.rsi(close=close_series, length=self.RSI_LENGTH)
        calculated = calculated.replace({np.nan: None})
        return calculated

    def calculate_from_candles(self, candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not candles:
            return []

        base_df = self.to_dataframe(candles)
        calculated_df = self.calculate(base_df)
        return self._merge_with_original_candles(candles, calculated_df)

    def _merge_with_original_candles(
        self,
        candles: list[dict[str, Any]],
        calculated_df: pd.DataFrame,
    ) -> list[dict[str, Any]]:
        merged_rows: list[dict[str, Any]] = []
        indicator_columns = [
            *[f"sma_{period}" for period in self.SMA_PERIODS],
            *[f"ema_{period}" for period in self.EMA_PERIODS],
            f"bb_upper_{self.BBANDS_LENGTH}_{self.BBANDS_STD}",
            f"bb_middle_{self.BBANDS_LENGTH}_{self.BBANDS_STD}",
            f"bb_lower_{self.BBANDS_LENGTH}_{self.BBANDS_STD}",
            f"rsi_{self.RSI_LENGTH}",
        ]

        for index, candle in enumerate(candles):
            row = dict(candle)
            for column in indicator_columns:
                value = calculated_df.at[index, column] if column in calculated_df.columns else None
                row[column] = self._normalize_value(value)
            merged_rows.append(row)

        return merged_rows

    @staticmethod
    def _normalize_value(value: Any) -> float | None:
        if pd.isna(value):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
