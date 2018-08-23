import logging
from itertools import cycle

from hades.core import Runnable, State
from hades.profiling import tictoc
from hades.utils import (
    bqm_induced_by, select_localsearch_adversaries, select_random_subgraph,
    chimera_tiles)


logger = logging.getLogger(__name__)


class EnergyImpactDecomposer(Runnable):
    """Selects up to `max_size` variables that contribute the most to energy
    increase.

    Note: currently, list of variables not connected in problem graph might be
    returned.
    """

    def __init__(self, bqm, max_size, min_gain=0.0, min_diff=1, stride=1):
        if max_size > len(bqm):
            raise ValueError("subproblem size cannot be greater than the problem size")
        if min_diff > max_size or min_diff < 0:
            raise ValueError("min_diff must be nonnegative and less than max_size")

        self.bqm = bqm
        self.max_size = max_size
        self.min_gain = min_gain
        self.min_diff = min_diff
        self.stride = stride

        # variables from previous iteration
        self._prev_vars = set()

    @tictoc('energy_impact_decompose')
    def iterate(self, state):
        # select a new subset of `max_size` variables, making sure they differ
        # from previous iteration by at least `min_diff` variables
        sample = state.samples.change_vartype(self.bqm.vartype).first.sample
        variables = select_localsearch_adversaries(
            self.bqm, sample, min_gain=self.min_gain)

        offset = 0
        next_vars = set(variables[offset : offset+self.max_size])
        while len(next_vars ^ self._prev_vars) < self.min_diff:
            offset += self.stride
            next_vars = set(variables[offset : offset+self.max_size])

        logger.debug("Select variables: %r (diff from prev = %r)",
                     next_vars, next_vars ^ self._prev_vars)
        self._prev_vars = next_vars

        # induce sub-bqm based on selected variables and global sample
        subbqm = bqm_induced_by(self.bqm, next_vars, sample)
        return state.updated(ctx=dict(subproblem=subbqm),
                             debug=dict(decomposer=self.__class__.__name__))


class RandomSubproblemDecomposer(Runnable):
    """Selects a random subproblem of size `size`. The subproblem is possibly
    not connected.
    """

    def __init__(self, bqm, size):
        if size > len(bqm):
            raise ValueError("subproblem size cannot be greater than the problem size")

        self.bqm = bqm
        self.size = size

    @tictoc('random_decompose')
    def iterate(self, state):
        variables = select_random_subgraph(self.bqm, self.size)
        sample = state.samples.change_vartype(self.bqm.vartype).first.sample
        subbqm = bqm_induced_by(self.bqm, variables, sample)
        return state.updated(ctx=dict(subproblem=subbqm),
                             debug=dict(decomposer=self.__class__.__name__))


class IdentityDecomposer(Runnable):
    """Copies problem to subproblem."""

    def __init__(self, bqm):
        self.bqm = bqm

    @tictoc('identity_decompose')
    def iterate(self, state):
        return state.updated(ctx=dict(subproblem=self.bqm),
                             debug=dict(decomposer=self.__class__.__name__))


class TilingChimeraDecomposer(Runnable):
    """Returns sequential tile slices of the initial BQM."""

    def __init__(self, bqm, size=(4,4,4), loop=True):
        """Size C(n,m,t) defines a Chimera subgraph returned with each call."""
        self.bqm = bqm
        self.size = size
        self.blocks = iter(chimera_tiles(self.bqm, *self.size).items())
        if loop:
            self.blocks = cycle(self.blocks)

    @tictoc('tiling_chimera_decompose')
    def iterate(self, state):
        """Each call returns a subsequent block of size `self.size` Chimera cells."""
        pos, embedding = next(self.blocks)
        variables = embedding.keys()
        sample = state.samples.change_vartype(self.bqm.vartype).first.sample
        subbqm = bqm_induced_by(self.bqm, variables, sample)
        return state.updated(ctx=dict(subproblem=subbqm, embedding=embedding),
                             debug=dict(decomposer=self.__class__.__name__))
