# HARNESS-PROVENANCE: deterministic-quality-harness v1.8 — negative fixture, do not "fix"
"""One function far over the ceiling, surrounded by trivial ones.

The trivial neighbours are the point: under a ``top-N`` gate they dilute the ranking and the real
offender can drop out of view. Under an absolute ceiling it is reported every time.
"""


def too_many_branches(value: int) -> str:
    result = ""
    if value == 1:
        result += "a"
    if value == 2:
        result += "b"
    if value == 3:
        result += "c"
    if value == 4:
        result += "d"
    if value == 5:
        result += "e"
    if value == 6:
        result += "f"
    if value == 7:
        result += "g"
    if value == 8:
        result += "h"
    if value == 9:
        result += "i"
    if value == 10:
        result += "j"
    if value == 11:
        result += "k"
    if value == 12:
        result += "l"
    if value == 13:
        result += "m"
    if value == 14:
        result += "n"
    if value == 15:
        result += "o"
    if value == 16:
        result += "p"
    if value == 17:
        result += "q"
    return result


def trivial_one(value: int) -> int:
    return value + 1


def trivial_two(value: int) -> int:
    return value + 2


def trivial_three(value: int) -> int:
    return value + 3


def trivial_four(value: int) -> int:
    return value + 4


def trivial_five(value: int) -> int:
    return value + 5
