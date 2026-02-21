import logging

from app.services.brokers.base import BaseBrokerClient
from app.services.brokers.korea_investment import KoreaInvestmentBroker
from app.services.brokers.upbit import upbit_broker


class BrokerFactory:
    _logger = logging.getLogger(__name__)
    _korea_investment_broker = KoreaInvestmentBroker()

    _upbit_aliases = {"upbit", "krw-crypto", "crypto"}
    _korea_investment_aliases = {
        "korea_investment",
        "koreainvestment",
        "ki",
        "stock",
        "kr-stock",
    }

    @classmethod
    def get_broker(cls, broker_id: str) -> BaseBrokerClient:
        normalized = (broker_id or "").strip().lower()
        if normalized in cls._upbit_aliases:
            return upbit_broker

        if normalized in cls._korea_investment_aliases:
            return cls._korea_investment_broker

        cls._logger.warning(
            "Unknown broker_id '%s'. Falling back to UPBIT.",
            broker_id,
        )
        return upbit_broker
