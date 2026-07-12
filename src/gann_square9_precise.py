"""
gann_square9_precise.py — Layer 1 (Mathematical/Geometric): precise Square of Nine
implementation using the EXACT formulas from "The Definitive Guide to Forecasting
Using W.D. Gann's Square of Nine" by Patrick Mikula (project knowledge, Chapter 1-11).

This REPLACES the earlier approximation in gann_square9.py's square_of_nine() function
(which used an ad-hoc sqrt+offset shortcut from Abdo's own GannAnalyzer v1.0). This
version implements Gann's actual documented cell/rotation/angle system.

PROVENANCE — every formula below is cited to its exact book location so Abdo can
verify against the source rather than trust it blindly:

    cell_price()            <- Chapter 6 "Forecasting Prices Using Progression":
                                Cell Number * Price Increment + Starting Price = Cell Price
                                Verified against book's own worked example: MRK cell 86,
                                increment 0.25, starting price 38.50 -> price 60.00 (exact).

    cells_in_rotation()     <- Chapter 1 "Formula for Calculating the Amount of Cells
                                in a Rotation": sqrt(ending_odd_square)/2 - 0.5, times 8.
                                Verified: ending square 361 -> 72 cells (book's own example).

    move_around_square()    <- Chapter 1 "Formula for Moving Around the Square of Nine":
                                sqrt(start) +/- {0.25, 0.5, 1, 2} for {1/8, 1/4, 1/2, 1}
                                rotation, then re-square.
                                Verified: 225, move inward 1 full rotation -> 169 (exact).

    CELL_ANGLE_TABLE         <- Chapter 1 "Angle Degree for Each Cell", cells 2-361
                                (rotations 1-9), transcribed directly from the book's
                                printed table. NOT a general closed-form trig formula —
                                the book itself says deriving the full trigonometric
                                relationship is out of scope, and provides the table
                                as the reference instead. This module does the same:
                                cells beyond 361 raise an explicit error rather than
                                extrapolating a guessed pattern.

CARDINAL/DIAGONAL CROSS METHOD (Chapter 1 + Chapter 2 worked examples):
    Gann's own stated rule (per the book, repeated across every worked example):
    the cells falling on the cardinal cross (0/90/180/270 degrees) and diagonal
    cross (45/135/225/315 degrees) are the historically significant support/
    resistance levels — not an arbitrary proximity search like the earlier
    gann_square9.py approximation did.

    find_cross_levels() locates the nearest cell to a pivot price, then walks
    outward through the angle table to find cells that land on cardinal/diagonal
    angles, and returns their prices as the support/resistance levels — this is
    the actual documented Gann method, not a shortcut.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# Transcribed directly from the book's "Angle Degree for Each Cell" table
# (Chapter 1), rotations 1 through 9, cells 2-361.
CELL_ANGLE_TABLE: dict[int, float] = {
    2: 180, 3: 135, 4: 90, 5: 45, 6: 0, 7: 315, 8: 270, 9: 225,
    10: 206.56, 11: 180, 12: 153.43, 13: 135, 14: 116.56, 15: 90, 16: 63.43,
    17: 45, 18: 26.56, 19: 0, 20: 333.43, 21: 315, 22: 296.56, 23: 270,
    24: 243.43, 25: 225,
    26: 213.69, 27: 198.43, 28: 180, 29: 161.56, 30: 146.31, 31: 135,
    32: 123.69, 33: 108.43, 34: 90, 35: 71.56, 36: 56.30, 37: 45, 38: 33.69,
    39: 18.43, 40: 0, 41: 341.56, 42: 326.31, 43: 315, 44: 303.69, 45: 288.43,
    46: 270, 47: 251.56, 48: 236.31, 49: 225,
    50: 216.87, 51: 206.56, 52: 194.03, 53: 180, 54: 165.96, 55: 153.43,
    56: 143.13, 57: 135, 58: 126.87, 59: 116.56, 60: 104.03, 61: 90,
    62: 75.96, 63: 63.43, 64: 53.13, 65: 45, 66: 36.87, 67: 26.56, 68: 14.03,
    69: 0, 70: 345.96, 71: 333.43, 72: 323.13, 73: 315, 74: 306.86,
    75: 296.56, 76: 284.03, 77: 270, 78: 255.96, 79: 243.43, 80: 233.13,
    81: 225,
    82: 218.65, 83: 210.96, 84: 201.84, 85: 191.31, 86: 180, 87: 168.69,
    88: 158.19, 89: 149.03, 90: 141.34, 91: 135, 92: 128.65, 93: 120.96,
    94: 111.80, 95: 101.30, 96: 90, 97: 78.69, 98: 68.19, 99: 59.03,
    100: 51.34, 101: 45, 102: 38.65, 103: 30.96, 104: 21.80, 105: 11.31,
    106: 0, 107: 348.69, 108: 338.19, 109: 329.03, 110: 321.34, 111: 315,
    112: 308.65, 113: 300.96, 114: 291.80, 115: 281.30, 116: 270,
    117: 258.69, 118: 248.19, 119: 239.03, 120: 231.34, 121: 225,
    122: 219.80, 123: 213.69, 124: 206.56, 125: 198.43, 126: 189.46,
    127: 180, 128: 170.53, 129: 161.56, 130: 153.43, 131: 146.31,
    132: 140.19, 133: 135, 134: 129.80, 135: 123.69, 136: 116.56,
    137: 108.43, 138: 99.46, 139: 90, 140: 80.53, 141: 71.56, 142: 63.43,
    143: 56.31, 144: 50.19, 145: 45, 146: 39.80, 147: 33.69, 148: 26.56,
    149: 18.43, 150: 9.46, 151: 0, 152: 350.53, 153: 341.56, 154: 333.43,
    155: 326.31, 156: 320.19, 157: 315, 158: 309.80, 159: 303.69,
    160: 296.56, 161: 288.43, 162: 279.46, 163: 270, 164: 260.53,
    165: 251.56, 166: 243.43, 167: 236.31, 168: 230.19, 169: 225,
    170: 220.60, 171: 215.53, 172: 209.74, 173: 203.19, 174: 195.94,
    175: 188.13, 176: 180, 177: 171.86, 178: 164.05, 179: 156.80,
    180: 150.25, 181: 144.46, 182: 139.39, 183: 135, 184: 130.60,
    185: 125.53, 186: 119.74, 187: 113.19, 188: 105.94, 189: 98.13,
    190: 90, 191: 81.86, 192: 74.05, 193: 66.80, 194: 60.25, 195: 54.46,
    196: 49.39, 197: 45, 198: 40.60, 199: 35.53, 200: 29.74, 201: 23.19,
    202: 15.94, 203: 8.13, 204: 0, 205: 351.87, 206: 344.04, 207: 336.80,
    208: 330.25, 209: 324.46, 210: 319.39, 211: 315, 212: 310.60,
    213: 305.53, 214: 299.74, 215: 293.19, 216: 285.94, 217: 278.13,
    218: 270, 219: 261.86, 220: 254.05, 221: 246.80, 222: 240.25,
    223: 234.46, 224: 229.39, 225: 225,
    226: 221.18, 227: 216.86, 228: 212.00, 229: 206.56, 230: 200.55,
    231: 194.03, 232: 187.12, 233: 180, 234: 172.87, 235: 165.96,
    236: 159.44, 237: 153.43, 238: 147.99, 239: 143.13, 240: 138.81,
    241: 135, 242: 131.18, 243: 126.86, 244: 122.00, 245: 116.56,
    246: 110.55, 247: 104.03, 248: 97.12, 249: 90, 250: 82.87, 251: 75.96,
    252: 69.44, 253: 63.43, 254: 57.99, 255: 53.13, 256: 48.81, 257: 45,
    258: 41.18, 259: 36.86, 260: 32.00, 261: 26.56, 262: 20.55, 263: 14.03,
    264: 7.12, 265: 0, 266: 352.87, 267: 345.96, 268: 339.44, 269: 333.43,
    270: 327.99, 271: 323.13, 272: 318.81, 273: 315, 274: 311.18,
    275: 306.86, 276: 302.00, 277: 296.56, 278: 290.55, 279: 284.03,
    280: 277.12, 281: 270, 282: 262.87, 283: 255.96, 284: 249.44,
    285: 243.43, 286: 237.99, 287: 233.13, 288: 228.81, 289: 225,
    290: 221.63, 291: 217.87, 292: 213.69, 293: 209.05, 294: 203.96,
    295: 198.43, 296: 192.52, 297: 186.34, 298: 180, 299: 173.65,
    300: 167.47, 301: 161.56, 302: 156.03, 303: 150.94, 304: 146.31,
    305: 142.12, 306: 138.36, 307: 135, 308: 131.63, 309: 127.87,
    310: 123.69, 311: 119.05, 312: 113.96, 313: 108.43, 314: 102.52,
    315: 96.34, 316: 90, 317: 83.65, 318: 77.47, 319: 71.56, 320: 66.03,
    321: 60.94, 322: 56.30, 323: 52.12, 324: 48.36, 325: 45, 326: 41.63,
    327: 37.87, 328: 33.69, 329: 29.05, 330: 23.96, 331: 18.43, 332: 12.52,
    333: 6.34, 334: 0, 335: 353.65, 336: 347.47, 337: 341.56, 338: 336.03,
    339: 330.94, 340: 326.30, 341: 322.12, 342: 318.36, 343: 315,
    344: 311.63, 345: 307.87, 346: 303.69, 347: 299.05, 348: 293.96,
    349: 288.43, 350: 282.52, 351: 276.34, 352: 270, 353: 263.65,
    354: 257.47, 355: 251.56, 356: 246.03, 357: 240.94, 358: 236.30,
    359: 232.12, 360: 228.36, 361: 225,
}
MAX_TABLED_CELL = 361

CARDINAL_ANGLES = {0, 90, 180, 270}
DIAGONAL_ANGLES = {45, 135, 225, 315}
CARDINAL_DIAGONAL_ANGLES = CARDINAL_ANGLES | DIAGONAL_ANGLES


def cell_price(cell_number: float, price_increment: float, starting_price: float = 0.0) -> float:
    """
    Chapter 6 formula: Cell Number * Price Increment + Starting Price = Cell Price.
    With starting_price=0, this is the "Zero Base" method from Chapter 10.
    Book's own worked example (Merck, Chapter 6): cell_price(86, 0.25, 38.5) == 60.0
    """
    return round(cell_number * price_increment + starting_price, 2)


def cells_in_rotation(ending_odd_square: int) -> int:
    """
    Chapter 1 formula: sqrt(ending_odd_square)/2 - 0.5, result * 8.
    Book's own worked example: cells_in_rotation(361) == 72.
    """
    r = math.sqrt(ending_odd_square)
    return int(round((r / 2 - 0.5) * 8))


def move_around_square(start_number: float, rotations: float) -> float:
    """
    Chapter 1 "Formula for Moving Around the Square of Nine".
    `rotations` is signed: +1.0 = one full rotation outward, -1.0 = one full
    rotation inward, -0.5 = half rotation inward, etc. (matches the book's
    add/subtract-then-resquare steps exactly: 1 rotation = +/-2 on the sqrt,
    1/2 = +/-1, 1/4 = +/-0.5, 1/8 = +/-0.25).
    Book's own worked example: move_around_square(225, -1.0) == 169.0
    """
    r = math.sqrt(start_number)
    new_r = r + (rotations * 2)
    if new_r < 0:
        raise ValueError(f"move_around_square: resulting square root {new_r} is negative "
                          f"(start={start_number}, rotations={rotations}) — invalid move.")
    return round(new_r ** 2, 5)


def cell_angle(cell_number: int) -> float:
    """
    Chapter 1 "Angle Degree for Each Cell" table, transcribed from the book.
    Only covers cells 2-361 (the book's own documented range) — raises for
    anything outside that rather than guessing an extrapolated value.
    """
    if cell_number == 1:
        return 0.0  # center cell, angle undefined/degenerate in the book's own convention
    if cell_number not in CELL_ANGLE_TABLE:
        raise ValueError(
            f"cell_angle: cell {cell_number} is outside the book's documented table "
            f"(valid range: 2-{MAX_TABLED_CELL}). No extrapolation is performed — "
            f"this would require deriving the general trigonometric relationship, "
            f"which the book explicitly states is out of its scope."
        )
    return CELL_ANGLE_TABLE[cell_number]


def nearest_cell_to_price(price: float, price_increment: float, starting_price: float = 0.0) -> int:
    """Inverse of cell_price(): given a price, find which cell number it falls closest to."""
    raw_cell = (price - starting_price) / price_increment
    return max(1, round(raw_cell))


@dataclass(frozen=True)
class CrossLevel:
    angle: float
    cell_number: int
    price: float
    is_cardinal: bool  # True = cardinal (0/90/180/270), False = diagonal (45/135/225/315)


def find_cross_levels(pivot_price: float, price_increment: float,
                       starting_price: float = 0.0, search_radius_cells: int = 40) -> list[CrossLevel]:
    """
    "Using Cell Numbers" method (Chapters 2-3): support/resistance from cells whose
    FIXED angle (measured from the center of the Square of Nine) is cardinal/diagonal,
    searched near the pivot's cell. This is a real, book-documented method — but it is
    NOT the method used in the book's "overlay" chapters (3, 5, 7, 9, 11), which anchor
    the cardinal/diagonal cross to the PIVOT ITSELF rather than the square's center.
    See find_overlay_levels() for that method, which is what most of the book's
    higher-chapter worked examples (including the Wellpoint Ch.11 example this module
    was tested against) actually use, and is the one this project uses for signals.
    """
    center_cell = nearest_cell_to_price(pivot_price, price_increment, starting_price)
    levels = []
    for offset in range(-search_radius_cells, search_radius_cells + 1):
        candidate_cell = center_cell + offset
        if candidate_cell < 2 or candidate_cell > MAX_TABLED_CELL:
            continue
        angle = cell_angle(candidate_cell)
        if angle in CARDINAL_DIAGONAL_ANGLES:
            price = cell_price(candidate_cell, price_increment, starting_price)
            levels.append(CrossLevel(
                angle=angle, cell_number=candidate_cell, price=price,
                is_cardinal=angle in CARDINAL_ANGLES,
            ))
    return sorted(levels, key=lambda lvl: lvl.price)


# Overlay rotation steps: 45/90/135/180/225/270/315/360 degrees = 1/8, 1/4, 3/8, 1/2,
# 5/8, 3/4, 7/8, 1 full rotation. Each step's `rotations` value is what
# move_around_square() expects (1.0 = one full rotation).
OVERLAY_STEPS: dict[str, float] = {
    "45": 0.125, "90": 0.25, "135": 0.375, "180": 0.5,
    "225": 0.625, "270": 0.75, "315": 0.875, "360": 1.0,
}


def find_overlay_levels(pivot_price: float, price_increment: float,
                         starting_price: float = 0.0) -> list[CrossLevel]:
    """
    "Overlay" method (Chapters 3, 5, 7, 9, 11 — the book's more advanced technique,
    used in most of its later worked examples). The cardinal/diagonal cross is
    anchored to the PIVOT price itself (the overlay's "0° angle"), and support/
    resistance levels are found by moving OUTWARD and INWARD from the pivot's own
    cell in 1/8-rotation (45-degree) increments, using move_around_square().

    VERIFIED against the book's own Wellpoint (WLP) Chapter 11 example: pivot=89.20,
    increment=0.5, starting_price=0 (zero base) -> one full rotation inward from the
    pivot's cell lands on cell 129, price 64.50 (book states 64.53, i.e. a match
    within the book's own rounding). This confirms the overlay/rotation method is
    the correct one for pivot-anchored support/resistance, NOT find_cross_levels()
    above (which uses the square's fixed center-angle table instead and does NOT
    reproduce this worked example).
    """
    pivot_cell = nearest_cell_to_price(pivot_price, price_increment, starting_price)
    levels = []
    for angle_label, rotations in OVERLAY_STEPS.items():
        for direction in (1, -1):
            moved_cell = move_around_square(pivot_cell, rotations * direction)
            rounded_cell = round(moved_cell)
            if rounded_cell < 1 or rounded_cell > MAX_TABLED_CELL:
                continue
            price = cell_price(rounded_cell, price_increment, starting_price)
            levels.append(CrossLevel(
                angle=float(angle_label), cell_number=rounded_cell, price=price,
                is_cardinal=angle_label in ("90", "180", "270", "360"),
            ))
    # de-duplicate (inward/outward can sometimes land on the same cell near the center)
    seen = set()
    unique_levels = []
    for lvl in sorted(levels, key=lambda l: l.price):
        key = (lvl.cell_number, lvl.price)
        if key not in seen:
            seen.add(key)
            unique_levels.append(lvl)
    return unique_levels
