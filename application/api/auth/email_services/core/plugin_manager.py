# email_services/core/plugin_manager.py
import importlib
import yaml
from pathlib import Path
from typing import Dict, Any, List

from .exceptions import EmailServiceError


class PluginManager:
    """
    Dynamically loads email service plugins from a YAML config.
    Supports multiple instances per plugin and ignores extra keys like `enabled` and `order`.
    Collects all load errors without stopping other plugins.
    """

    def __init__(self, config_path: str):
        self.config_path = Path(config_path)
        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")

        self.plugins: Dict[str, List[Any]] = {}
        self.load_errors: Dict[str, str] = {}
        self._load_plugins()

    def _load_plugins(self):
        """Load all enabled plugins and their instances from the YAML config."""
        with open(self.config_path) as f:
            cfg = yaml.safe_load(f)

        plugins_cfg = cfg.get("email_service", {}).get("plugins", {})

        for plugin_name, plugin_info in plugins_cfg.items():
            if not plugin_info.get("enabled", True):
                continue

            entry_point = plugin_info.get("entry_point")
            try:
                plugin_cls = self._import_plugin(entry_point)
            except Exception as exc:
                self.load_errors[plugin_name] = f"Import error: {exc}"
                continue

            instances_cfg = plugin_info.get("instances")
            loaded_instances = []

            if instances_cfg:
                # Multi-instance plugins
                for instance_name, instance_cfg in instances_cfg.items():
                    if not instance_cfg.get("enabled", True):
                        continue
                    try:
                        instance = self._create_instance(plugin_cls, instance_cfg.get("settings", {}))
                        loaded_instances.append(instance)
                    except Exception as exc:
                        self.load_errors[f"{plugin_name}:{instance_name}"] = str(exc)
            else:
                # Single-instance plugin
                try:
                    instance = self._create_instance(plugin_cls, plugin_info.get("settings", {}))
                    loaded_instances.append(instance)
                except Exception as exc:
                    self.load_errors[plugin_name] = str(exc)

            if loaded_instances:
                self.plugins[plugin_name] = loaded_instances


    def _import_plugin(self, entry_point: str):
        """Import plugin class from entry point string 'module:ClassName'"""
        if not entry_point or ":" not in entry_point:
            raise ValueError(f"Invalid entry_point format: {entry_point}")
        
        module_name, class_name = entry_point.split(":")
        try:
            print(f"Trying to import module: {module_name}, class: {class_name}")  # Add debugging here
            module = importlib.import_module(f"email_services.plugins.{module_name}")
            plugin_cls = getattr(module, class_name)
            return plugin_cls
        except Exception as exc:
            print(f"Error importing plugin '{entry_point}': {exc}")  # Debugging output
            raise ImportError(f"Cannot import plugin '{entry_point}'") from exc
       

    def _create_instance(self, plugin_cls, settings: dict):
        """
        Create plugin instance.
        Removes unsupported keys automatically.
        """
        # Remove non-init keys
        safe_settings = {k: v for k, v in settings.items() if k not in ["enabled", "order"]}

        config_cls = getattr(plugin_cls, "ConfigClass", None)
        if config_cls:
            config_obj = config_cls(**safe_settings)
            return plugin_cls(config_obj)
        else:
            return plugin_cls(**safe_settings)

    def get_plugin(self, plugin_name: str, instance_index: int = 0):
        """Retrieve a loaded plugin instance by name and optional index."""
        instances = self.plugins.get(plugin_name)
        if not instances:
            raise ValueError(f"Plugin '{plugin_name}' not loaded or disabled")
        if instance_index >= len(instances):
            raise IndexError(f"Plugin '{plugin_name}' has only {len(instances)} instances")
        return instances[instance_index]

    def all_plugins(self) -> Dict[str, List[Any]]:
        """Return all successfully loaded plugins."""
        return self.plugins

    def report_errors(self) -> Dict[str, str]:
        """Return all plugin load errors."""
        return self.load_errors


# Run the plugin manager if executed directly
if __name__ == "__main__":
    plugin_manager = PluginManager(
        config_path="/home/karthikeya/Development/Opensource/DocsGPT/application/config/email_services.yaml"
    )
    print("Loaded plugins:", plugin_manager.plugins)
    if plugin_manager.load_errors:
        print("Plugin load errors:")
        for k, v in plugin_manager.load_errors.items():
            print(f"  {k}: {v}")
