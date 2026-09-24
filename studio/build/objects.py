"""Small edits to game object task headers."""

import re


def set_soldier_team(segment, model, team):
    """Replace a HumanSoldier team ID without changing its model or bone ID."""
    pattern = re.compile(r'("%s", )\d+(, \d+)' % re.escape(model))
    updated, count = pattern.subn(
        lambda match: match.group(1) + str(int(team)) + match.group(2),
        segment,
        count=1,
    )
    if count != 1:
        raise ValueError("could not find HumanSoldier model %r in task" % model)
    return updated
