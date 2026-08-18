"""Mailbox/download partition of the claim-group regression suite."""

from tests._claim_groups_partition import make_partition


ClaimGroupsMailTests = make_partition(__name__, "mail")
