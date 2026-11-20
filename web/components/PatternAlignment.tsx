import type { PatternData } from "../lib/types";
import { taxonomyNames } from "../lib/taxonomy";
import type { TaxonomyNames } from "../lib/taxonomy";
const axes = { hook_type: "훅", angle: "소구", format: "형식" } as const;
export function PatternAlignment({ data, label, names = taxonomyNames() }: { data: PatternData; label: string; names?: TaxonomyNames }) {
  return <section className="pattern-panel" aria-label="경쟁사 패턴 반영"><h4>경쟁사 패턴 반영</h4>
    <p>비교한 축 {data.compared ?? 0}개 중 같은 축 {data.same_count ?? 0}개</p>
    <ul>{(Object.keys(axes) as (keyof typeof axes)[]).map(axis => {
      const item = data.axes?.[axis];
      return <li key={axis}><strong>{axes[axis]}</strong><p>
        기획안: {item?.plan == null ? "정보 없음" : names.axisName(axis, item.plan)} · 경쟁사 지배 패턴: {item?.dominant?.length ? item.dominant.map(value => names.axisName(axis, value)).join(", ") : "정보 없음"} · <span className="pattern-fact">{item?.same === true ? "같음" : item?.same === false ? "다름" : "비교 불가"}</span> · <span>{item?.share == null ? "점유율 비교 불가" : `점유율 ${(item.share * 100).toFixed(1)}%`}</span>
      </p></li>;
    })}</ul><small>{label}</small>
  </section>;
}
