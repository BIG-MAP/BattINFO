from importlib.resources import files


def data_path() -> str:
    """Return the root path to packaged data files."""
    return str(files("battinfo.data"))
