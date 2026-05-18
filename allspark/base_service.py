from allspark.database import Database


class BaseService:
    SERVICE_NAME: str = ""

    def __init__(self, db: Database, **kwargs):
        self.db = db

    def is_available(self) -> bool:
        return True

    def get_status(self) -> dict:
        return {"name": self.SERVICE_NAME, "available": self.is_available()}

    def startup(self) -> None:
        pass

    def shutdown(self) -> None:
        pass
