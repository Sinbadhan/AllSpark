from allspark.core.database import Database


class BaseService:
    SERVICE_NAME: str = ""

    def __init__(self, db: Database, **kwargs):
        self.db = db

    def is_available(self) -> bool:
        return True

    def is_configured(self) -> bool:
        """Whether the service has been set up with required parameters."""
        return self.is_available()

    def unavailability_reason(self) -> str:
        """Human-readable reason why the service is not available."""
        return ""

    def next_action(self) -> str:
        """Suggested action to make the service available."""
        return ""

    def get_status(self) -> dict:
        available = self.is_available()
        return {
            "name": self.SERVICE_NAME,
            "available": available,
            "loaded": True,
            "configured": self.is_configured() if available else False,
            "reason": self.unavailability_reason() if not available else "",
            "next_action": self.next_action() if not available else "",
        }

    def startup(self) -> None:
        pass

    def shutdown(self) -> None:
        pass
