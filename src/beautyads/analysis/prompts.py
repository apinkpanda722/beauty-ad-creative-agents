"""Draft v0 hook criteria in taxonomy priority order."""

from beautyads.domain import Creative, HookType

HOOK_PROMPT_VERSION = "hook-v0"

_HOOK_CRITERIA = {
    HookType.question: "화면 자막이나 음성이 의문문으로 시작한다",
    HookType.problem: "피부 고민 상태를 화면으로 보여주거나 말로 제시한다 (트러블, 건조, 모공 등)",
    HookType.result_first: "사용 후 결과나 사용 전후 비교가 먼저 나온다",
    HookType.bold_claim: '수치·순위·단정 문장이 자막이나 음성으로 나온다 ("1위", "7일 만에")',
    HookType.product_first: "제품 용기·제형 클로즈업으로 시작하고 위 네 가지에 해당하지 않는다",
    HookType.person_first: "인물이 등장해 말하거나 행동하며 위 다섯 가지에 해당하지 않는다",
    HookType.other: "위 어느 것도 아니다",
}


def build_hook_prompt(creative: Creative) -> str:
    criteria = "\n".join(
        f"{member.value}: {_HOOK_CRITERIA[member]}" for member in HookType
    )
    return (
        "영상의 첫 구간만 보고 훅 유형을 하나 선택한다. "
        "판정 기준은 첫 3초 안에 화면과 음성에서 관찰되는 것이다. "
        "제공된 구간이 더 짧으면 그 구간만 본다.\n"
        f"{criteria}\n"
        "둘 이상 해당하면 위쪽 값을 우선한다.\n"
        "제목·캡션은 참고 정보이며 구간 밖의 내용을 추정하지 않는다.\n"
        f"참고 제목: {creative.title or ''}\n"
        f"참고 캡션: {creative.caption or ''}\n"
        "출력은 hook_type 필드에 선택한 값을 담은 JSON 하나뿐이어야 한다."
    )
