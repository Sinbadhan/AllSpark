from typing import Any, Callable, Optional


class ServiceNotFoundError(Exception):
    def __init__(self, name: str):
        self.name = name
        super().__init__(f"Service not found: {name}")


class ServiceContainer:
    def __init__(self, db=None, flags=None):
        self._services: dict[str, Any] = {}
        self._factories: dict[str, tuple[Callable, list[str]]] = {}
        self._initializing: set[str] = set()
        self.db = db
        self.flags = flags

    def register(self, name: str, instance: Any) -> 'ServiceContainer':
        self._services[name] = instance
        return self

    def register_factory(self, name: str, factory: Callable, *, requires: list[str] = None) -> 'ServiceContainer':
        self._factories[name] = (factory, requires or [])
        return self

    def get(self, name: str) -> Optional[Any]:
        if name in self._services:
            return self._services[name]
        if name in self._factories:
            if name in self._initializing:
                raise RuntimeError(f"Circular dependency detected: {name}")
            self._initializing.add(name)
            try:
                factory, requires = self._factories[name]
                deps = {r: self.get(r) for r in requires}
                instance = factory(**deps)
                self._services[name] = instance
                del self._factories[name]
                return instance
            finally:
                self._initializing.discard(name)
        return None

    def has(self, name: str) -> bool:
        return name in self._services or name in self._factories

    def require(self, name: str) -> Any:
        svc = self.get(name)
        if svc is None:
            raise ServiceNotFoundError(name)
        return svc

    def all_services(self) -> dict[str, Any]:
        return dict(self._services)

    def service_names(self) -> list[str]:
        names = set(self._services.keys()) | set(self._factories.keys())
        return sorted(names)
