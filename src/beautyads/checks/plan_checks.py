"""Check evidence, taxonomy, expressions, certification, and efficacy in order.

No model, network, or graph implementation is used here. Adapters supplied by
the caller provide lookup results for a fixed snapshot.
"""

import re
from collections.abc import Collection, Sequence

from beautyads.domain.claims import ClaimRule, RuleType, check_plan_fields
from beautyads.domain.labels import Claim
from beautyads.domain.lookups import (
    CertLookup,
    CertStatus,
    EfficacySupportLookup,
    EvidenceIndex,
    SupportStatus,
)
from beautyads.domain.plan import (
    CheckCode,
    CheckIssue,
    CheckSeverity,
    Plan,
    PlanCheckReport,
    validate_plan,
)
from beautyads.domain.tools import EVIDENCE_ID_PATTERN


def run_checks(
    plan: Plan,
    *,
    handoff_evidence_ids: Collection[str],
    rules: Sequence[ClaimRule],
    evidence_index: EvidenceIndex,
    support: EfficacySupportLookup,
    certs: CertLookup,
) -> PlanCheckReport:
    # Revalidate even model_construct/model_copy inputs so bypassing Pydantic
    # cannot silently accept an open classification value.
    return run_checks_on_dict(
        plan.model_dump(warnings=False),
        handoff_evidence_ids=handoff_evidence_ids,
        rules=rules,
        evidence_index=evidence_index,
        support=support,
        certs=certs,
    )


def _evidence_issues(
    evidence_ids: Sequence[str],
    *,
    handoff_evidence_ids: Collection[str],
    evidence_index: EvidenceIndex,
) -> list[CheckIssue]:
    """Use input order for reporting, never set iteration order."""
    issues = []
    if not evidence_ids:
        issues.append(
            CheckIssue(
                code=CheckCode.EVIDENCE_MISSING,
                severity=CheckSeverity.fail,
                field="evidence_ids",
                detail="근거 소재 ID가 비어 있음: 검사 대상 0건",
            )
        )
    handoff = set(handoff_evidence_ids)
    for index, evidence_id in enumerate(evidence_ids):
        if evidence_id not in handoff:
            issues.append(
                CheckIssue(
                    code=CheckCode.EVIDENCE_NOT_IN_HANDOFF,
                    severity=CheckSeverity.fail,
                    field=f"evidence_ids[{index}]",
                    detail=f"핸드오프 목록에 없는 근거 소재 ID: {evidence_id}",
                )
            )
    valid_ids = tuple(
        dict.fromkeys(
            evidence_id
            for evidence_id in evidence_ids
            if re.fullmatch(EVIDENCE_ID_PATTERN, evidence_id)
        )
    )
    existing = evidence_index.existing(valid_ids) if valid_ids else set()
    for index, evidence_id in enumerate(evidence_ids):
        if (
            not re.fullmatch(EVIDENCE_ID_PATTERN, evidence_id)
            or evidence_id not in existing
        ):
            issues.append(
                CheckIssue(
                    code=CheckCode.EVIDENCE_NOT_FOUND,
                    severity=CheckSeverity.fail,
                    field=f"evidence_ids[{index}]",
                    detail=f"형식이 잘못되었거나 그래프에 없는 근거 소재 ID: {evidence_id}",
                )
            )

    return issues


def run_checks_on_dict(
    data: dict,
    *,
    handoff_evidence_ids: Collection[str],
    rules: Sequence[ClaimRule],
    evidence_index: EvidenceIndex,
    support: EfficacySupportLookup,
    certs: CertLookup,
) -> PlanCheckReport:
    """Report evidence before schema failures; check text only for valid plans."""
    plan, validation_issues = validate_plan(data)
    report = PlanCheckReport(issues=[], rule_count=len(rules))
    # 1. Even invalid classification values must not hide evidence failures.
    evidence_ids = plan.evidence_ids if plan is not None else data.get("evidence_ids")
    if isinstance(evidence_ids, list) and all(
        isinstance(value, str) for value in evidence_ids
    ):
        report.issues.extend(
            _evidence_issues(
                evidence_ids,
                handoff_evidence_ids=handoff_evidence_ids,
                evidence_index=evidence_index,
            )
        )
    # 2. Validation failures use domain issues without a Pydantic dependency here.
    report.issues.extend(validation_issues)
    if plan is None:
        return report

    # 3. Title and all displayed text share the domain dictionary matcher.
    fields = {"title": plan.title, "hook_text": plan.hook_text}
    fields.update((f"scene[{i}]", text) for i, text in enumerate(plan.scenes))
    fields.update((f"copy_lines[{i}]", text) for i, text in enumerate(plan.copy_lines))
    if plan.image_brief is not None:
        fields["image_brief"] = plan.image_brief
    by_id = {rule.rule_id: rule for rule in rules}
    product_url = (
        plan.product_url if plan.product_url and plan.product_url.strip() else None
    )
    for field, matches in check_plan_fields(fields, rules).fields.items():
        for match in matches:
            detail = f"{field}: 규칙 {match.rule_id}, 표현 {match.term}"
            if match.rule_type == RuleType.prohibited:
                report.issues.append(
                    CheckIssue(
                        code=CheckCode.PROHIBITED_EXPRESSION,
                        severity=CheckSeverity.fail,
                        field=field,
                        detail=detail,
                    )
                )
            elif match.rule_type == RuleType.requires_functional_cert:
                efficacies = list(
                    dict.fromkeys(
                        Claim(scope.value)
                        for scope in by_id[match.rule_id].applies_to
                        if scope.kind == "efficacy"
                    )
                )
                if not efficacies:
                    report.issues.append(
                        CheckIssue(
                            code=CheckCode.CERT_REQUIRED_UNVERIFIED,
                            severity=CheckSeverity.unknown,
                            field=field,
                            detail=f"{detail}: 규칙의 효능 연결 없음, 인증 확인 불가",
                        )
                    )
                for efficacy in efficacies:
                    status = (
                        certs.cert_status(product_url, efficacy)
                        if product_url is not None
                        else CertStatus.unknown
                    )
                    if status != CertStatus.certified:
                        report.issues.append(
                            CheckIssue(
                                code=CheckCode.CERT_REQUIRED_UNVERIFIED,
                                severity=(
                                    CheckSeverity.fail
                                    if status == CertStatus.not_certified
                                    else CheckSeverity.unknown
                                ),
                                field=field,
                                detail=(
                                    f"{detail}, 효능 {efficacy.value}: "
                                    + (
                                        "인증되지 않음"
                                        if status == CertStatus.not_certified
                                        else "인증 연결 없음 (제품 URL 없음)"
                                        if product_url is None
                                        else "인증 연결 없음"
                                    )
                                ),
                            )
                        )
            else:
                # Substantiation is an observation, not a legal determination.
                # The declared efficacies are checked below, including unknowns.
                report.substantiation_observations.append(f"{detail}: 실증 필요")

    # 4. Unknown records missing links and never implies unsupported efficacy.
    if product_url is None and not plan.claimed_efficacy:
        report.issues.append(
            CheckIssue(
                code=CheckCode.EFFICACY_UNKNOWN,
                severity=CheckSeverity.unknown,
                field="product_url",
                detail="근거 연결 없음 (제품 URL 없음): 효능 근거 검사 대상 0건",
            )
        )
    for index, efficacy in enumerate(plan.claimed_efficacy):
        status = (
            support.efficacy_support(product_url, efficacy)
            if product_url is not None
            else SupportStatus.unknown
        )
        if status == SupportStatus.supported:
            continue
        report.issues.append(
            CheckIssue(
                code=(
                    CheckCode.EFFICACY_UNSUPPORTED
                    if status == SupportStatus.unsupported
                    else CheckCode.EFFICACY_UNKNOWN
                ),
                severity=(
                    CheckSeverity.fail
                    if status == SupportStatus.unsupported
                    else CheckSeverity.unknown
                ),
                field=f"claimed_efficacy[{index}]",
                detail=f"효능 {efficacy.value}: "
                + (
                    "제품의 효능 근거가 뒷받침하지 않음"
                    if status == SupportStatus.unsupported
                    else "근거 연결 없음 (제품 URL 없음)"
                    if product_url is None
                    else "근거 연결 없음"
                ),
            )
        )
    return report
