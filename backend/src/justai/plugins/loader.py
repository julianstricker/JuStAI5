"""Discovering plugin directories and importing in-process plugin code."""

from __future__ import annotations

import importlib
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

from justai_sdk.manifest import MANIFEST_FILENAME, PluginManifest, load_manifest
from justai_sdk.plugin import Plugin

from justai.logging import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class PluginSource:
    manifest: PluginManifest
    path: Path
    origin: str  # builtin | uploaded | generated


def discover(directory: Path, origin: str) -> list[PluginSource]:
    found: list[PluginSource] = []
    if not directory.exists():
        return found
    for manifest_path in sorted(directory.glob(f"*/{MANIFEST_FILENAME}")):
        try:
            manifest = load_manifest(manifest_path.parent)
        except Exception as exc:
            log.error("invalid plugin manifest", path=str(manifest_path), error=str(exc))
            continue
        found.append(PluginSource(manifest, manifest_path.parent, origin))
    return found


def _package_name(plugin_id: str) -> str:
    return "justai_plugins." + plugin_id.replace("-", "_")


def load_plugin_class(source: PluginSource) -> type[Plugin]:
    """Import the entrypoint under a private package name (``justai_plugins.<id>``).

    Plugin modules must use relative imports for their own modules.
    """
    module_path, class_name = source.manifest.entrypoint.split(":", 1)
    package = _package_name(source.manifest.id)
    unload_plugin_modules(source.manifest.id)
    if "justai_plugins" not in sys.modules:
        root = importlib.util.module_from_spec(
            importlib.machinery.ModuleSpec("justai_plugins", None, is_package=True)
        )
        root.__path__ = []
        sys.modules["justai_plugins"] = root
    spec = importlib.util.spec_from_file_location(
        package, source.path / "__init__.py", submodule_search_locations=[str(source.path)]
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load plugin package from {source.path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[package] = module
    if (source.path / "__init__.py").exists():
        spec.loader.exec_module(module)
    entry = importlib.import_module(f"{package}.{module_path}")
    cls = getattr(entry, class_name, None)
    if not isinstance(cls, type) or not issubclass(cls, Plugin):
        raise ImportError(f"{source.manifest.entrypoint} is not a Plugin subclass")
    return cls


def unload_plugin_modules(plugin_id: str) -> None:
    package = _package_name(plugin_id)
    for name in [m for m in sys.modules if m == package or m.startswith(package + ".")]:
        del sys.modules[name]
