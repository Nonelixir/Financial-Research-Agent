from finagent.schemas import UserProfile
from finagent.storage import SQLiteStore


class ProfileService:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    def get(self, profile_id: str = "default") -> UserProfile:
        return self.store.get_profile(profile_id)

    def update(self, profile: UserProfile) -> UserProfile:
        profile.preferred_tickers = list(
            dict.fromkeys(ticker.upper() for ticker in profile.preferred_tickers)
        )
        return self.store.put_profile(profile)

    def clear(self, profile_id: str = "default") -> None:
        self.store.delete_profile(profile_id)
