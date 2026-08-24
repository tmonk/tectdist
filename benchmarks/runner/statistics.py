"""Paired summaries with deterministic bootstrap confidence intervals."""
import random
import statistics


def percentile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    return values[min(len(values) - 1, round((len(values) - 1) * fraction))]


def paired_summary(differences, iterations=2000):
    """Summarise candidate-minus-competitor milliseconds.

    A negative value favours the candidate. No samples are discarded.
    """
    if not differences:
        return {"count": 0}
    rng = random.Random(0)
    means = []
    for _ in range(iterations):
        sample = [differences[rng.randrange(len(differences))]
                  for _ in differences]
        means.append(statistics.mean(sample))
    return {"count": len(differences), "median_difference_ms": statistics.median(differences),
            "mean_difference_ms": statistics.mean(differences),
            "ci95_ms": [percentile(means, .025), percentile(means, .975)]}
