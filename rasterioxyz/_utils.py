from dataclasses import astuple, dataclass
from itertools import product
from typing import Iterator

from numpy import ndarray
from rasterio import Affine, windows


@dataclass(frozen=True, slots=True)
class _Bounds:
    """Dataclass for standardised, iterable bounding coordinates."""
    minx: float
    miny: float
    maxx: float
    maxy: float

    def __iter__(self) -> Iterator[tuple[float, float, float, float]]:
        iterator: Iterator[tuple[float, float, float, float]] = iter(astuple(self))
        return iterator


@dataclass(frozen=True, slots=True)
class _ImageProperties:
    """Dataclass for key Pseudo-Mercator (EPSG:3857) properties of the source image"""
    transform: Affine
    bounds: _Bounds


@dataclass(kw_only=True, slots=True)
class _Tile:
    """Dataclass for key tile properties."""
    zoom: int
    column: int
    row: int
    bounds: _Bounds
    transform: Affine
    window: windows.Window
    data: ndarray


@dataclass(frozen=True, slots=True)
class _Zoom:
    """Dataclass for key zoom level properties."""
    zoom: int
    tile_dims: int | float
    tile_indices: product
