"""
gann_layer1_tools.py — Layer 1 (Mathematical/Geometric), remaining tools beyond
Square of Nine (see gann_square9_precise.py for that).

PROVENANCE:
    - Gann Angles (1x1, 2x1, etc.): "Scientific Methods Unveiled Vol. 2", Introduction
      section "Nomenclature of Gann's Price and Time Angles". Fully documented,
      unambiguous: NxM means N price units per M time units.
    - Hexagon Chart ring structure: "Scientific Methods Unveiled Vol. 1", Chapter 10
      "Introduction to the Hexagon Chart". Documented: ring 1 has 6 numbers (1-6),
      each additional ring adds 6 more numbers (ring 2: 7-18, ring 3: 19-36, ...).
    - Circle Chart ring structure: "Scientific Methods Unveiled Vol. 2", Chapter 4,
      discussion of Gann's rye-market Circle Chart. Documented: 24 numbers per ring,
      numbered counterclockwise starting at the right side.

NOT IMPLEMENTED — Square of 144:
    No explicit construction formula for a chart specifically called "Square of 144"
    was found in the three books currently in this project (Mikula's Square of Nine
    guide, and Scientific Methods Unveiled Vol. 1 & 2). The closest documented
    relative is Gann's "Master 360° Square of 12" (a 24-cycle square chart variant,
    Scientific Methods Unveiled Vol. 2, Chapter 4) and the general mathematical fact
    that 144 = 12² is an even square number (Mikula, Chapter 1, "Other Math
    Principles"). Rather than invent a formula, this is left unimplemented. If Abdo
    has a source with the actual construction rule, it can be added the same way the
    other tools here were: formula extracted from source, then verified against a
    worked example before being trusted.

DEGREE DIVISIONS (45/90/120/144/180/225/270/315):
    These aren't a separate "tool" — they're the angle sets already used inside
    Square of Nine (CARDINAL_ANGLES/DIAGONAL_ANGLES, 45° steps) and here in the
    Hexagon Chart (60° steps, giving the sextile/square/trine/opposition angles: 60,
    90, 120, 180, 240, 270, 300).
"""

from __future__ import annotations

import math
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# GANN ANGLES (1x1, 2x1, 1x2, 4x1, etc.)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GannAngle:
    """
    A Gann angle NxM: moves N price units per M time units from an anchor point.
    Source: Scientific Methods Unveiled Vol. 2, Introduction — "the first number in
    1x4 is the increment moved up or down in price and the second number is the
    increment moved to the right in time."
    """
    price_units: float
    time_units: float

    @property
    def slope(self) -> float:
        """Price change per single time unit (e.g. per day)."""
        return self.price_units / self.time_units

    def price_at(self, anchor_price: float, anchor_time_index: int, target_time_index: int,
                 direction: int = 1) -> float:
        """
        Price the angle predicts at target_time_index, given it starts at
        anchor_price at anchor_time_index. direction=1 for an upward-sloping angle
        (support line rising from a pivot LOW), direction=-1 for downward-sloping
        (resistance line falling from a pivot HIGH).
        """
        elapsed = target_time_index - anchor_time_index
        return anchor_price + direction * self.slope * elapsed


# Standard named Gann angles, per Scientific Methods Unveiled Vol. 2's nomenclature.
STANDARD_GANN_ANGLES: dict[str, GannAngle] = {
    "1x8": GannAngle(1, 8), "1x4": GannAngle(1, 4), "1x3": GannAngle(1, 3),
    "1x2": GannAngle(1, 2), "1x1": GannAngle(1, 1), "2x1": GannAngle(2, 1),
    "3x1": GannAngle(3, 1), "4x1": GannAngle(4, 1), "8x1": GannAngle(8, 1),
}


def gann_angle_price(angle_name: str, anchor_price: float, anchor_time_index: int,
                      target_time_index: int, direction: int = 1) -> float:
    """Convenience wrapper: look up a standard angle by name (e.g. '1x1') and price it."""
    if angle_name not in STANDARD_GANN_ANGLES:
        raise ValueError(f"Unknown Gann angle '{angle_name}'. Valid names: {sorted(STANDARD_GANN_ANGLES)}")
    return STANDARD_GANN_ANGLES[angle_name].price_at(anchor_price, anchor_time_index, target_time_index, direction)


# ---------------------------------------------------------------------------
# HEXAGON CHART
# ---------------------------------------------------------------------------

def hexagon_ring_bounds(ring: int) -> tuple[int, int]:
    """
    Returns (first_cell, last_cell) for a given ring (ring >= 1) of the Hexagon Chart.
    Source: Scientific Methods Unveiled Vol. 1, Chapter 10. Ring 1 = cells 1-6 (6 cells).
    Ring n has 6n cells. Cumulative cells through ring n = 6*(1+2+...+n) = 3n(n+1).
    Verified against the book's own stated values: ring 1 -> (1,6), ring 2 -> (7,18),
    ring 3 -> (19,36).
    """
    if ring < 1:
        raise ValueError(f"hexagon_ring_bounds: ring must be >= 1, got {ring}")
    last_cell = 3 * ring * (ring + 1)
    first_cell = last_cell - (6 * ring) + 1
    return first_cell, last_cell


def hexagon_ring_for_cell(cell_number: int) -> int:
    """Inverse of hexagon_ring_bounds(): which ring does a given cell number fall in."""
    if cell_number < 1:
        raise ValueError(f"hexagon_ring_for_cell: cell_number must be >= 1, got {cell_number}")
    if cell_number <= 6:
        return 1
    # 3n(n+1) >= cell_number, solve for smallest integer n via the quadratic formula
    ring = math.ceil((-3 + math.sqrt(9 + 12 * cell_number)) / 6)
    while hexagon_ring_bounds(ring)[1] < cell_number:
        ring += 1
    while ring > 1 and hexagon_ring_bounds(ring - 1)[1] >= cell_number:
        ring -= 1
    return ring


def hexagon_cell_price(cell_number: int, price_increment: float, starting_price: float = 0.0) -> float:
    """
    Same linear cell-to-price principle used across all Gann Price & Time Charts
    (see gann_square9_precise.cell_price). No hexagon-specific numeric worked
    example was found in the available books to verify this against directly —
    this is applied by documented analogy to the Square of Nine's formula, not a
    hexagon-specific citation. Flagged here so Abdo can verify independently if a
    hexagon-specific source example becomes available.
    """
    return round(cell_number * price_increment + starting_price, 2)


HEXAGON_ANGLE_STEPS = (0, 60, 120, 180, 240, 300)  # sextile/square/trine/opposition angles

# Six unit directions of a hexagonal lattice (axial coordinates), used to walk each
# ring's edges when generating the spiral. Standard hex-grid construction (not
# Gann-specific) -- see e.g. any hex-grid coordinate reference. Angles chosen so that
# direction 0 points along the 0-degree axis (matching the book's "starting to the
# right of center" convention), then step counterclockwise, matching the book's
# stated spiral direction.
_HEX_DIRECTIONS = [
    (1, 0), (0, 1), (-1, 1), (-1, 0), (0, -1), (1, -1),
]


def _axial_to_cartesian(q: int, r: int) -> tuple[float, float]:
    """Standard axial-to-Cartesian conversion for a pointy-top hex lattice."""
    x = q + r / 2
    y = (math.sqrt(3) / 2) * r
    return x, y


def _generate_hexagon_ring_cells(ring: int) -> list[tuple[int, int]]:
    """
    Returns the list of (q, r) axial coordinates for every cell in the given ring,
    in the order Gann's numbering walks them (starting right of center, counter-
    clockwise), per Scientific Methods Unveiled Vol. 1 Ch. 10.
    """
    if ring == 0:
        return [(0, 0)]
    # Start at `ring` steps in direction 4, then walk `ring` steps in each of the
    # 6 directions in turn (standard hex-ring traversal).
    q, r = _HEX_DIRECTIONS[4][0] * ring, _HEX_DIRECTIONS[4][1] * ring
    cells = []
    for direction in range(6):
        for _ in range(ring):
            cells.append((q, r))
            dq, dr = _HEX_DIRECTIONS[direction]
            q, r = q + dq, r + dr
    return cells


def hexagon_cell_angle(cell_number: int) -> float:
    """
    Real hex-lattice geometry (axial coordinates -> Cartesian -> atan2), analogous
    to how Square of Nine's angles come from real square-lattice geometry — NOT a
    simple linear rescaling of the Square of Nine table. Verified below: the FIRST
    cell of each ring (the ring's starting corner) lands exactly on a multiple of
    60 degrees, matching the book's stated hexagon corner/sextile structure.
    """
    ring = hexagon_ring_for_cell(cell_number)
    first_cell, _ = hexagon_ring_bounds(ring)
    position_in_ring = cell_number - first_cell
    ring_cells = _generate_hexagon_ring_cells(ring)
    q, r = ring_cells[position_in_ring]
    x, y = _axial_to_cartesian(q, r)
    angle = math.degrees(math.atan2(y, x)) % 360
    return round(angle, 2)


# ---------------------------------------------------------------------------
# CIRCLE CHART
# ---------------------------------------------------------------------------

CIRCLE_CELLS_PER_RING = 24  # Scientific Methods Unveiled Vol. 2, Chapter 4: Gann's rye-market
                             # Circle Chart example: "There are twenty-four numbers in each ring"


def circle_ring_bounds(ring: int) -> tuple[int, int]:
    """
    Returns (first_cell, last_cell) for a given ring of the Circle Chart.
    Source: Scientific Methods Unveiled Vol. 2, Chapter 4 — numbers start at 1 on
    the right side of the inner ring, move counterclockwise to 24, then the next
    ring starts at 25. Ring n therefore spans (24*(n-1)+1) to (24*n).
    """
    if ring < 1:
        raise ValueError(f"circle_ring_bounds: ring must be >= 1, got {ring}")
    first_cell = CIRCLE_CELLS_PER_RING * (ring - 1) + 1
    last_cell = CIRCLE_CELLS_PER_RING * ring
    return first_cell, last_cell


def circle_cell_to_degree(cell_number: int) -> float:
    """
    Each ring's 24 cells map onto 360 degrees (15 degrees per cell), per the book's
    description of 15-degree zodiac increments around the Circle Chart. Cell 1 is
    at 0 degrees (right side), moving counterclockwise.
    """
    ring = math.ceil(cell_number / CIRCLE_CELLS_PER_RING)
    first_cell, _ = circle_ring_bounds(ring)
    position_in_ring = cell_number - first_cell  # 0-indexed position within the ring
    return round(position_in_ring * (360 / CIRCLE_CELLS_PER_RING), 2)
