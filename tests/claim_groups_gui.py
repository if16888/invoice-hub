"""GUI partition of the claim-group regression suite."""

from tests._claim_groups_partition import make_partition


ClaimGroupsGuiTests = make_partition(__name__, "gui")
