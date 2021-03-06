Introduction
============

The E\_vs\_r\_scan calculation calculation creates a plot of the
cohesive energy vs interatomic spacing, :math:`r`, for a given atomic
system. The system size is uniformly scaled (:math:`b/a` and :math:`c/a`
ratios held fixed) and the energy is calculated at a number of sizes
without relaxing the system. All box sizes corresponding to energy
minima are identified.

This calculation was created as a quick method for scanning the phase
space of a crystal structure with a given potential in order to identify
starting guesses for further structure refinement calculations.

**Disclaimer #1**: the minima identified by this calculation do not
guarantee that the associated crystal structure will be stable as no
relaxation is performed by this calculation. Upon relaxation, the atomic
positions and box dimensions may transform the system to a different
structure.

**Disclaimer #2**: it is possible that the calculation may miss an
existing minima for a crystal structure if it is outside the range of
:math:`r` values scanned, or has :math:`b/a`, :math:`c/a` values far
from the ideal.
