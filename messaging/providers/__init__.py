from ..models import Channel
from .base import MessagingProvider, ProviderError
from .gmail import GmailProvider
from .instagram import InstagramProvider

PROVIDERS: dict[str, type[MessagingProvider]] = {
    Channel.INSTAGRAM: InstagramProvider,
    Channel.EMAIL: GmailProvider,
}


def get_provider(channel) -> MessagingProvider:
    try:
        return PROVIDERS[channel]()
    except KeyError:
        raise ProviderError("지원하지 않는 채널입니다.") from None


__all__ = ["PROVIDERS", "MessagingProvider", "ProviderError", "get_provider"]
