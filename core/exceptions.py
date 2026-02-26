"""Custom exceptions for the Market Analysis Agent."""


class MarketAnalysisError(Exception):
    """Base exception for the system."""

    pass


class DataFetchError(MarketAnalysisError):
    """Raised when market data fetch fails."""

    pass


class RateLimitError(MarketAnalysisError):
    """Raised when API rate limit is hit."""

    pass


class SignalFilterError(MarketAnalysisError):
    """Raised when signal fails quality filter."""

    pass


class WebSocketError(MarketAnalysisError):
    """Raised when WebSocket connection fails."""

    pass
