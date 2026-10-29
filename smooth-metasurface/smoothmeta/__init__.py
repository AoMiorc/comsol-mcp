"""Geometry preparation is independent of COMSOL and does not start a JVM."""
from .geometry import prepare_geometry, export_geometry, load_spec

__all__ = ["prepare_geometry", "export_geometry", "load_spec"]
