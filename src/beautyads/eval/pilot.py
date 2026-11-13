"""Select dev creatives without consulting analysis results or metrics."""

import random
from collections import defaultdict, deque
from collections.abc import Collection, Sequence
from typing import NamedTuple

from beautyads.domain import Creative, Source, is_analyzable
from beautyads.sources.split import BrandSplit, SplitError, brand_group


class PilotSelection(NamedTuple):
    items: list[Creative]
    shortfall: int


def select_pilot(
    creatives: Sequence[Creative],
    split: BrandSplit,
    *,
    n: int = 20,
    seed: int,
    sources: Collection[Source] = (Source.youtube, Source.instagram),
) -> PilotSelection:
    """Shuffle sorted source/brand strata, then take one per stratum each round."""
    if n < 1:
        raise ValueError("n must be at least 1")
    grouped: dict[tuple[Source, str], list[Creative]] = defaultdict(list)
    for creative in creatives:
        if (
            creative.brand is None
            or not is_analyzable(creative)
            or creative.source not in sources
        ):
            continue
        try:
            group = brand_group(split, creative.brand)
        except SplitError:
            continue
        if group == "dev":
            grouped[creative.source, creative.brand].append(creative)

    rng = random.Random(seed)
    queues = []
    for group in sorted(grouped):
        items = sorted(grouped[group], key=lambda item: item.source_id)
        rng.shuffle(items)
        queues.append(deque(items))
    selected = []
    while queues and len(selected) < n:
        for queue in queues:
            selected.append(queue.popleft())
            if len(selected) == n:
                break
        queues = [queue for queue in queues if queue]
    return PilotSelection(selected, n - len(selected))
