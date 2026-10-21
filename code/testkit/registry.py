"""Where test modules register themselves. The core never imports a module
by name; it asks the registry."""
import importlib
import inspect
import pkgutil

from testkit.base import TestModule

_MODULES = {}
_COSTS = ("fast", "slow")


class RegistrationError(ValueError):
    pass


def _validate(cls):
    if not (isinstance(cls, type) and issubclass(cls, TestModule)):
        raise RegistrationError(f"{cls!r} is not a TestModule subclass")
    if inspect.isabstract(cls):
        raise RegistrationError(f"{cls.__name__} does not implement run()")
    for name in ("id", "title"):
        value = getattr(cls, name, None)
        if not isinstance(value, str) or not value.strip():
            raise RegistrationError(f"{cls.__name__}.{name} must be a non-empty string")
    crit = getattr(cls, "criteria", None)
    if not crit or not all(isinstance(c, str) and c for c in crit):
        raise RegistrationError(f"{cls.__name__}.criteria must be a non-empty set of strings")
    if cls.cost not in _COSTS:
        raise RegistrationError(f"{cls.__name__}.cost must be one of {_COSTS}")


def register(cls):
    """Class decorator: @register on a TestModule subclass."""
    _validate(cls)
    if cls.id in _MODULES and _MODULES[cls.id] is not cls:
        raise RegistrationError(f"duplicate module id: {cls.id}")
    _MODULES[cls.id] = cls
    return cls


def get_module(module_id):
    return _MODULES[module_id]


def all_modules():
    """Registered module classes, sorted by id."""
    return [_MODULES[k] for k in sorted(_MODULES)]


def unregister(module_id):
    """Used by tests to clean up."""
    _MODULES.pop(module_id, None)


def discover():
    """Imports every package under testkit.modules so each can register
    itself. Adding a module therefore means adding a folder."""
    import testkit.modules as pkg
    for info in pkgutil.iter_modules(pkg.__path__):
        importlib.import_module(f"{pkg.__name__}.{info.name}")
    return all_modules()