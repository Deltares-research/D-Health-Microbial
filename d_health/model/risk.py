from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)


def calc_infection_risk_beta_poisson(
    dose: np.ndarray,
    alpha: float,
    beta: float,
) -> np.ndarray:
    """Beta-Poisson infection-risk curve.

    Converts an ingested dose (organisms) into a probability of infection:

        risk = 1 - (1 + dose / beta) ** (-alpha)

    where ``alpha`` and ``beta`` are the pathogen's dose-response parameters.
    NaN doses propagate to NaN risks.

    This is the only dose-response kernel implemented today; the pipeline
    hard-wires it via ``PathogenConfig.active.alpha`` / ``.beta``. Adding a
    second distribution would require re-introducing a discriminator field on
    ``PathogenParameters`` and dispatching on it here.
    """
    return 1.0 - (1.0 + dose / beta) ** (-alpha)
