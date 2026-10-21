"""The fixed vocabulary of things a user can ask to have tested.

The frontend renders these as checkboxes. A module declares which of them it
serves in its `criteria` set.
"""

CRITERIA = {
    "reliability": "Handles bad input and failures without crashing",
    "security-basics": "Does not leak internals or accept hostile input",
    "abuse-protection": "Limits excessive or abusive traffic",
    "api-correctness": "Behaves the way its API description says",
    "performance": "Stays fast and stable under load",
}


def is_known(criterion):
    return criterion in CRITERIA