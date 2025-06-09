import logging
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler
from typing import TYPE_CHECKING, Any

from numpy import ndarray

if TYPE_CHECKING:
    from rasterioxyz.tile import Tiles


class _TileRequestHandler(BaseHTTPRequestHandler):
    """Class for handling XYZ tile image requests.

    Parameters
    ----------
    *args : tuple[typing.Any, ...]
        Positional arguments passed by `http.server.HTTPServer` and used by
        `http.server.BaseHTTPRequestHandler`.
    data : rasterioxyz.tile.Tiles
        Object to use in constructing requested tiles.
    driver : str
        Format in which to serve tile images.
    cache_age : int
        Time in seconds to cache served tile images after request creation.
    start : datetime.datetime
        Datetime at which the server started.
    **kwargs : dict[str, typing.Any]
        Keyword arguments passed by `http.server.HTTPServer` and used by
        `http.server.BaseHTTPRequestHandler`.

    """

    def __init__(
        self,
        *args: tuple[Any, ...],
        data: "Tiles",
        driver: str,
        cache_age: int,
        start: datetime,
        **kwargs: dict[str, Any],
    ) -> None:
        self.data = data
        self.driver = driver.lower()
        self.cache_age = cache_age
        self.log = logging.getLogger("rasterioxyz")
        self.start = start
        super().__init__(*args, **kwargs)  # type: ignore[arg-type]

    def do_GET(self) -> None:  # noqa: N802
        """Respond to a GET request.

        Raises
        ------
        ValueError
            If the tile request URL is malformed.

        """
        if self._request_is_unmodified():
            self.send_response(304)
            self.end_headers()
            return
        if self.path == "/favicon.ico" or self.path.endswith("styles.css.map"):
            self._not_tile_response()
            return

        try:
            z, x, y = [
                int(val)
                for val in self.path.replace(f".{self.driver}", "").split("/")[
                    1:
                ]
            ]
        except ValueError:
            self._malformed_url_response()
            return

        if z > max(self.data.zooms) or z < min(self.data.zooms):
            self._zoom_limit_response()
            return

        tile = self.data._build_tile(z, x, y)  # noqa: SLF001
        if tile["is_empty"]:
            self._empty_tile_response(z, x, y)
        else:
            self._tile_response(tile)

    def log_message(self, fmt: str, *args: tuple[Any, ...]) -> None:
        """Override `http.server.BaseHTTPRequestHandler.log_message()`.

        Parameters
        ----------
        fmt : str
            Template string dictating message format.
        *args : tuple[typing.Any, ...]
            Arguments to use in formatting the message template.

        """
        info_codes = ["200", "204", "304"]
        log_lvl = self.log.info if args[1] in info_codes else self.log.error
        log_lvl(fmt % args)

    def _request_is_unmodified(self) -> bool:
        """Check if a request has been modified."""
        if last_req := self.headers.get("If-Modified-Since"):
            last_utc = datetime.strptime(
                last_req,
                "%a, %d %b %Y %H:%M:%S GMT",
            ).replace(tzinfo=UTC)
            if self.start < last_utc:
                return True
        return False

    def _not_tile_response(self) -> None:
        """Send a 204 (No Content) status code."""
        self.send_response(204)
        self.end_headers()

    def _malformed_url_response(self) -> None:
        """Send a 400 (Bad Request) status code."""
        self.send_error(400, f"Incorrectly formatted XYZ URL: {self.path}")
        self.end_headers()

    def _zoom_limit_response(self) -> None:
        """Send a 404 (Not Found) status code."""
        self.send_error(
            404,
            "Tile outside of set minimum or maximum zoom levels.",
        )
        self.end_headers()

    def _empty_tile_response(self, z: int, x: int, y: int) -> None:
        """Send a 404 (Not Found) status code."""
        self.send_error(
            404,
            f"Tile empty or out of image bounds: zoom={z}, col={x}, row={y}",
        )
        self.send_header("Cache-Control", f"max-age={self.cache_age}")
        self.end_headers()

    def _tile_response(self, tile: dict[str, int | ndarray | bool]) -> None:
        """Send a 200 (OK) status code and tiled data."""
        stream = self.data._get_tile_bytes(tile, self.driver)  # noqa: SLF001
        self.send_response(200)
        self.send_header(
            "Last-Modified",
            datetime.now(UTC).strftime("%a, %d %b %Y %H:%M:%S GMT"),
        )
        self.send_header("Cache-Control", f"max-age={self.cache_age}")
        self.send_header("Content-Type", f"image/{self.driver}")
        self.end_headers()
        self.wfile.write(stream)
