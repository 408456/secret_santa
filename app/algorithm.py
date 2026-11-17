from __future__ import annotations

import random
from collections.abc import Iterable, Sequence


class DrawImpossibleError(ValueError):
    pass


def make_draw(
    participant_ids: Sequence[int],
    exclusions: Iterable[tuple[int, int]] = (),
    *,
    rng: random.Random | None = None,
) -> dict[int, int]:
    """Return a stable-to-store Secret Santa assignment using randomized backtracking."""
    ids = list(dict.fromkeys(participant_ids))
    if len(ids) < 2:
        raise DrawImpossibleError("Нужно хотя бы два участника")

    randomizer = rng or random.SystemRandom()
    forbidden: dict[int, set[int]] = {pid: {pid} for pid in ids}
    known = set(ids)
    for left, right in exclusions:
        if left in known and right in known:
            forbidden[left].add(right)
            forbidden[right].add(left)

    options = {giver: [r for r in ids if r not in forbidden[giver]] for giver in ids}
    if any(not receivers for receivers in options.values()):
        raise DrawImpossibleError("Исключения не оставляют допустимых вариантов")

    result: dict[int, int] = {}
    available = set(ids)

    def search() -> bool:
        if len(result) == len(ids):
            return True
        remaining = [giver for giver in ids if giver not in result]
        minimum = min(len(available.intersection(options[giver])) for giver in remaining)
        candidates = [
            giver for giver in remaining
            if len(available.intersection(options[giver])) == minimum
        ]
        giver = randomizer.choice(candidates)
        receivers = list(available.intersection(options[giver]))
        randomizer.shuffle(receivers)
        for receiver in receivers:
            result[giver] = receiver
            available.remove(receiver)
            if search():
                return True
            available.add(receiver)
            del result[giver]
        return False

    if not search():
        raise DrawImpossibleError("Не удалось провести жеребьёвку с этими исключениями")
    return result

