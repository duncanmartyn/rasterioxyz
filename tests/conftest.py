from pathlib import Path

import numpy
import pytest
from rasterio import MemoryFile, transform

TEST_OUTPUT_DIR = Path(__file__).parent.joinpath("output")
if not TEST_OUTPUT_DIR.exists():
    Path.mkdir(TEST_OUTPUT_DIR)

SUPPORTED_TEST_CRS = [3857, 4326, 27700, None]
SUPPORTED_TEST_DTYPE = [
    "uint8",
    "uint16"
    "uint32",
    "uint64",
    "int8",
    "int16",
    "int32",
    "int64",
    "float16",
    "float32",
    "float64",
]
TEST_BOUNDS = {
    3857: (-244781, 6545838, -191809, 6599779),
    4326: (-2.199, 50.572, -1.723, 50.878),
    27700: (386010, 74656, 419708, 108784),
}


@pytest.fixture(scope="session")
def test_data(request: pytest.FixtureRequest) -> MemoryFile:
    height = width = 256
    count = 3

    crs, dtype = request.param.values()
    if crs is None and dtype is None:
        yield None
    if crs not in SUPPORTED_TEST_CRS:
        pytest.skip(f"Unsupported CRS {crs}, use one of {SUPPORTED_TEST_CRS}")
    if dtype not in SUPPORTED_TEST_DTYPE:
        pytest.skip(f"Unsupported dtype {dtype}, use one of {SUPPORTED_TEST_DTYPE}")

    trans = transform.from_bounds(*TEST_BOUNDS[crs], width, height) if crs else None
    array = generate_test_array(dtype, count, width, height)

    with MemoryFile() as memfile:
        with memfile.open(
            driver="GTiff",
            height=height,
            width=width,
            count=count,
            crs=crs,
            transform=trans,
            dtype=dtype,
        ) as dst:
            dst.write(array)

        yield memfile.open()


def generate_test_array(
        dtype: str,
        count: int,
        width: int,
        height: int
) -> numpy.ndarray:
    info: numpy.iinfo | numpy.finfo
    if numpy.issubdtype(dtype, numpy.integer):
        info = numpy.iinfo(dtype)
    elif numpy.issubdtype(dtype, numpy.floating):
        info = numpy.finfo(dtype)
    array = numpy.random.uniform(
        info.min, info.max, (count, height, width)
    ).astype(dtype)
    return array
