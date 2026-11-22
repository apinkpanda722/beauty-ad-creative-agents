import type { PatternData } from "../../lib/types";
import { taxonomyNames } from "../../lib/taxonomy";
import type { TaxonomyNames } from "../../lib/taxonomy";
import { axisNames, displayValue } from "../../lib/localize";
const columns = [
  { label: "축", title: "비교하는 광고 분류" },
  { label: "기획안", title: "기획안이 고른 방식" },
  { label: "시장 최다 방식", title: "같은 분류의 시장 광고 중 가장 많이 쓰인 방식" },
  { label: "일치 여부", title: "기획안의 방식이 시장 최다 방식과 같은지" },
  { label: "시장 내 비중", title: "시장 광고 전체 중 기획안과 같은 방식을 쓴 광고의 비율" },
];
export function PatternAlignment({ data, names = taxonomyNames() }: { data: PatternData; names?: TaxonomyNames }) {
  return <section className="gs-pattern-panel gs-detail-card" aria-label="시장 패턴 반영"><h4>시장 패턴 반영</h4>
    <p>비교한 축 {data.compared ?? 0}개 중 같은 축 {data.same_count ?? 0}개</p>
    <div className="gs-result-table-scroll"><table><thead><tr>{columns.map(column => <th scope="col" key={column.label} title={column.title}>{column.label}</th>)}</tr></thead><tbody>{(["hook_type", "angle", "format"] as const).map(axis => {
      const item = data.axes?.[axis];
      return <tr key={axis}><th scope="row">{axisNames[axis]}</th>
        <td>{item?.plan == null ? "정보 없음" : displayValue(names.axisName(axis, item.plan), names)}</td><td>{item?.dominant?.length ? item.dominant.map(value => displayValue(names.axisName(axis, value), names)).join(", ") : "정보 없음"}</td><td><span className="pattern-fact">{item?.same === true ? "같음" : item?.same === false ? "다름" : "비교 불가"}</span></td><td>{item?.share == null ? "비교 불가" : `${(item.share * 100).toFixed(1)}%`}</td>
      </tr>;
    })}</tbody></table></div>
    <p className="gs-insight-note">시장 최다 방식: 같은 분류의 시장 광고 중 가장 많이 쓰인 방식</p>
    <p className="gs-insight-note">시장 내 비중: 시장 광고 전체 중 기획안과 같은 방식을 쓴 광고의 비율</p>
  </section>;
}

export function PatternSummary({ data }: { data: PatternData }) {
  return <p className="gs-pattern-summary">시장 패턴 반영 · 비교한 축 {data.compared ?? 0}개 중 같은 축 {data.same_count ?? 0}개</p>;
}
