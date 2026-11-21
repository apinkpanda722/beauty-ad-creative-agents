import { scoreExplanations, scoreNames } from "../../lib/localize";
import { Tooltip } from "../ui";

export function ScoreLabel({ name }: { name: "differentiation" | "fit" }) {
  return <Tooltip content={scoreExplanations[name]}>{scoreNames[name]}</Tooltip>;
}
