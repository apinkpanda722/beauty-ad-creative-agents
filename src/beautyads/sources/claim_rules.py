"""Read the confirmed claim dictionary; domain owns format and matching rules."""

from pathlib import Path

import yaml

from beautyads.domain.claims import ClaimRule, ClaimRulesError, parse_claim_rules
from beautyads.sources.config import ConfigError


def load_claim_rules(path: Path) -> list[ClaimRule]:
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise ConfigError("CLAIM_RULES_UNREADABLE") from None
    try:
        return parse_claim_rules(document)
    except ClaimRulesError as error:
        raise ConfigError(str(error)) from None
