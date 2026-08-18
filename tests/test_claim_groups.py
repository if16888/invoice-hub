"""Compatibility entry point for the complete claim-group regression suite."""

from tests._claim_groups_partition import make_full_case


ClaimGroupsTests = make_full_case(__name__)
