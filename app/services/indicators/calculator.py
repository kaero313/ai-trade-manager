from typing import Any

import pandas as pd
import pandas_ta_classic as ta


class IndicatorCalculator:
    REQUIRED_COLUMNS = ("open", "high", "low", "close", "volume")

    def __init__(self) -> None:
        self._ta = ta

    def to_dataframe(self, candles: list[dict[str, Any]]) -> pd.DataFrame:
        if not candles:
            return pd.DataFrame(columns=["timestamp", *self.REQUIRED_COLUMNS])

        df = pd.DataFrame(candles).copy()
        for column in self.REQUIRED_COLUMNS:
            if column not in df.columns:
                df[column] = pd.NA

        ordered_columns = [col for col in ["timestamp", *self.REQUIRED_COLUMNS] if col in df.columns]
        return df[ordered_columns]

    def calculate(self, df: pd.DataFrame) -> pd.DataFrame:
        # TODO: 실제 보조지표 공식(EMA/RSI/MACD 등)은 후속 단계에서 추가
        _ = self._ta
        return df.copy()

    def calculate_from_candles(self, candles: list[dict[str, Any]]) -> pd.DataFrame:
        base_df = self.to_dataframe(candles)
        return self.calculate(base_df)
