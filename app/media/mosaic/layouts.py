"""Preset mosaic layouts and tile validation."""

from __future__ import annotations

from app.core.exceptions import ValidationFailed
from app.schemas.mosaic import LayoutInfo, MosaicOutput, MosaicTile

LAYOUTS: dict[str, LayoutInfo] = {
    "single": LayoutInfo(name="single", camera_count=1, description="One camera fills the canvas."),
    "side_by_side": LayoutInfo(name="side_by_side", camera_count=2, description="Two equal columns."),
    "three_focus": LayoutInfo(
        name="three_focus",
        camera_count=3,
        description="One camera across the top and two cameras on the bottom row.",
    ),
    "grid_2x2": LayoutInfo(name="grid_2x2", camera_count=4, description="Two rows of two cameras."),
    "five_3_over_2": LayoutInfo(
        name="five_3_over_2",
        camera_count=5,
        description="Three cameras on the top row and two cameras on the bottom row.",
    ),
    "grid_3x2": LayoutInfo(name="grid_3x2", camera_count=6, description="Two rows of three cameras."),
    "custom": LayoutInfo(name="custom", camera_count=0, description="Caller supplies tile geometry."),
}


def tiles_for(layout: str, camera_ids: list[str], output: MosaicOutput) -> list[MosaicTile]:
    if layout == "custom":
        raise ValidationFailed("A custom layout requires tiles.")
    expected = LAYOUTS[layout].camera_count
    if len(camera_ids) != expected:
        raise ValidationFailed(
            f"Layout {layout} requires {expected} cameras.",
            details={"camera_count": len(camera_ids)},
        )
    width = output.width
    height = output.height
    builders = {
        "single": lambda: [_tile(camera_ids[0], 0, 0, width, height)],
        "side_by_side": lambda: _columns(camera_ids, width, height, columns=2, rows=1),
        "three_focus": lambda: [
            _tile(camera_ids[0], 0, 0, width, height // 2),
            _tile(camera_ids[1], 0, height // 2, width // 2, height // 2),
            _tile(camera_ids[2], width // 2, height // 2, width // 2, height // 2),
        ],
        "grid_2x2": lambda: _columns(camera_ids, width, height, columns=2, rows=2),
        "five_3_over_2": lambda: _top_and_bottom(camera_ids, width, height, top=3, bottom=2),
        "grid_3x2": lambda: _columns(camera_ids, width, height, columns=3, rows=2),
    }
    tiles = builders[layout]()
    validate_tiles(tiles, output)
    return tiles


def validate_tiles(tiles: list[MosaicTile], output: MosaicOutput) -> None:
    if not tiles:
        raise ValidationFailed("A mosaic needs at least one visible tile.")
    visible = [tile for tile in tiles if tile.visible]
    if not visible:
        raise ValidationFailed("At least one tile must be visible.")
    if len(visible) > 6:
        raise ValidationFailed("A mosaic can include at most six cameras.")
    seen: set[str] = set()
    for tile in visible:
        if tile.camera_id in seen:
            raise ValidationFailed(f"Camera {tile.camera_id} is used more than once.")
        seen.add(tile.camera_id)
        if tile.x + tile.width > output.width or tile.y + tile.height > output.height:
            raise ValidationFailed(
                f"Tile for {tile.camera_id} does not fit inside the mosaic canvas.",
                details={"tile": tile.model_dump(), "canvas": {"width": output.width, "height": output.height}},
            )


def _tile(camera_id: str, x: int, y: int, width: int, height: int, z: int = 0) -> MosaicTile:
    return MosaicTile(camera_id=camera_id, x=_even(x), y=_even(y), width=_even(width), height=_even(height), z=z)


def _even(value: int) -> int:
    return value if value % 2 == 0 else value - 1


def _columns(camera_ids: list[str], width: int, height: int, columns: int, rows: int) -> list[MosaicTile]:
    tile_width = _even(width // columns)
    tile_height = _even(height // rows)
    tiles: list[MosaicTile] = []
    for index, camera_id in enumerate(camera_ids):
        column = index % columns
        row = index // columns
        tiles.append(_tile(camera_id, column * tile_width, row * tile_height, tile_width, tile_height, index))
    return tiles


def _top_and_bottom(
    camera_ids: list[str],
    width: int,
    height: int,
    *,
    top: int,
    bottom: int,
) -> list[MosaicTile]:
    row_height = _even(height // 2)
    top_width = _even(width // top)
    bottom_width = _even(width // bottom)
    tiles = [
        _tile(camera_ids[index], index * top_width, 0, top_width, row_height, index) for index in range(top)
    ]
    tiles.extend(
        _tile(camera_ids[top + index], index * bottom_width, row_height, bottom_width, row_height, top + index)
        for index in range(bottom)
    )
    return tiles
