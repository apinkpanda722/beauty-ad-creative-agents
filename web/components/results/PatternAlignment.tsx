import type { PatternData } from "../../lib/types";
import { taxonomyNames } from "../../lib/taxonomy";
import type { TaxonomyNames } from "../../lib/taxonomy";
import { displayValue } from "../../lib/localize";
const axes = { hook_type: "훅", angle: "소구", format: "형식" } as const;
export function PatternAlignment({ data, label, names = taxonomyNames() }: { data: PatternData; label: string; names?: TaxonomyNames }) {
  return <section className="gs-pattern-panel gs-detail-card" aria-label="경쟁사 패턴 반영"><h4>경쟁사 패턴 반영</h4>
    <p>비교한 축 {data.compared ?? 0}개 중 같은 축 {data.same_count ?? 0}개</p>
    <div className="gs-result-table-scroll"><table><thead><tr>{["축", "기획안", "지배 패턴", "같음/다름", "점유율"].map(label => <th scope="col" key={label}>{label}</th>)}</tr></thead><tbody>{(Object.keys(axes) as (keyof typeof axes)[]).map(axis => {
      const item = data.axes?.[axis];
      return <tr key={axis}><th scope="row">{axes[axis]}</th>
        <td>기획안: {item?.plan == null ? "정보 없음" : displayValue(names.axisName(axis, item.plan), names)}</td><td>경쟁사 지배 패턴: {item?.dominant?.length ? item.dominant.map(value => displayValue(names.axisName(axis, value), names)).join(", ") : "정보 없음"}</td><td><span className="pattern-fact">{item?.same === true ? "같음" : item?.same === false ? "다름" : "비교 불가"}</span></td><td>{item?.share == null ? "점유율 비교 불가" : `${(item.share * 100).toFixed(1)}%`}</td>
      </tr>;
    })}</tbody></table></div><small>{label}</small>
  </section>;
}

export function PatternSummary({ data }: { data: PatternData }) {
  return <p className="gs-pattern-summary">경쟁사 패턴 반영 · 비교한 축 {data.compared ?? 0}개 중 같은 축 {data.same_count ?? 0}개</p>;
}
