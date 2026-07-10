"""Tests for ServiceContainer and ApplicationBootstrap."""
import pytest

from allspark.container import ServiceContainer, ServiceNotFoundError


class TestServiceContainer:
    def test_register_and_get(self):
        container = ServiceContainer()
        container.register("test", "hello")
        assert container.get("test") == "hello"

    def test_get_nonexistent_returns_none(self):
        container = ServiceContainer()
        assert container.get("missing") is None

    def test_require_nonexistent_raises(self):
        container = ServiceContainer()
        with pytest.raises(ServiceNotFoundError):
            container.require("missing")

    def test_has_registered(self):
        container = ServiceContainer()
        container.register("svc", 42)
        assert container.has("svc") is True
        assert container.has("nope") is False

    def test_register_factory_lazy(self):
        called = []
        def factory():
            called.append(1)
            return "lazy"
        container = ServiceContainer()
        container.register_factory("lazy_svc", factory)
        assert len(called) == 0  # not called yet
        assert container.get("lazy_svc") == "lazy"
        assert len(called) == 1

    def test_register_factory_with_requires(self):
        container = ServiceContainer()
        container.register("db", "fake_db")
        container.register_factory("svc", lambda db: f"svc-{db}", requires=["db"])
        assert container.get("svc") == "svc-fake_db"

    def test_register_factory_circular_dependency(self):
        container = ServiceContainer()
        container.register_factory("a", lambda b: "a", requires=["b"])
        container.register_factory("b", lambda a: "b", requires=["a"])
        with pytest.raises(RuntimeError, match="Circular dependency"):
            container.get("a")

    def test_require_returns_service(self):
        container = ServiceContainer()
        container.register("x", 99)
        assert container.require("x") == 99

    def test_all_services(self):
        container = ServiceContainer()
        container.register("a", 1)
        container.register("b", 2)
        assert container.all_services() == {"a": 1, "b": 2}

    def test_service_names(self):
        container = ServiceContainer()
        container.register("z", 1)
        container.register("a", 2)
        assert container.service_names() == ["a", "z"]

    def test_register_returns_container(self):
        container = ServiceContainer()
        result = container.register("x", 1)
        assert result is container

    def test_register_factory_returns_container(self):
        container = ServiceContainer()
        result = container.register_factory("x", lambda: 1)
        assert result is container

    def test_factory_only_called_once(self):
        calls = []
        def factory():
            calls.append(1)
            return "val"
        container = ServiceContainer()
        container.register_factory("svc", factory)
        container.get("svc")
        container.get("svc")
        assert len(calls) == 1

    def test_db_and_flags_attrs(self):
        container = ServiceContainer(db="mydb", flags="myflags")
        assert container.db == "mydb"
        assert container.flags == "myflags"
