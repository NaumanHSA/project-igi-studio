"""Where a building's own things stand in it: its doors, its lift, the barrels and
desks that came with it (a placement's `of` and `slot`).

They go with the building when the build sets it down on the ground. How far from
it they stand is what the plan has now, what the map and the 3D view show. A `slot`
is only where a thing first stood: taken as the place, it put back everything moved
on its own since (2026-11-04, barrels moved beside a crate that stayed in the game
where the building first had them)."""
import math


def offset(thing, home):
    """Where thing stands from home, in home's own axes."""
    g = float(home.get("gamma") or 0)
    c, s = math.cos(g), math.sin(g)
    ex, ey = float(thing["x"]) - float(home["x"]), float(thing["y"]) - float(home["y"])
    return {"dx": ex * c + ey * s, "dy": -ex * s + ey * c, "dz": float(thing["z"]) - float(home["z"]),
            "dh": float(thing.get("gamma") or 0) - g}


def offsets(placements):
    """{uid: offset} of everything that came with a building, read before anything has moved."""
    by_uid = {p.get("uid"): p for p in placements if p.get("uid")}
    out = {}
    for p in placements:
        home = by_uid.get(p.get("of"))
        if p.get("uid") and home is not None and isinstance(p.get("slot"), dict):
            out[p["uid"]] = offset(p, home)
    return out


def place(off, home):
    """The x, y, z and gamma of something this far from home, as home stands now."""
    g = float(home.get("gamma") or 0)
    c, s = math.cos(g), math.sin(g)
    return (round(float(home["x"]) + off["dx"] * c - off["dy"] * s, 3),
            round(float(home["y"]) + off["dx"] * s + off["dy"] * c, 3),
            round(float(home["z"]) + off["dz"], 3),
            round((g + off["dh"]) % (2 * math.pi), 5))
