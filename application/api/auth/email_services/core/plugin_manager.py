from importlib.metadata import entry_points

for ep in entry_points(group="email_service.plugins"):
    try:
        plugin = ep.load()()
        print(f"Loaded: {plugin}")
    except Exception as e:
        print(f"Failed to load plugin {ep.name}: {e}")
