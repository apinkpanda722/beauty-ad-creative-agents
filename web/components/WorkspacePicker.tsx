import type { Workspace } from "../lib/types";
export function WorkspacePicker({ workspaces, value, onChange }: {
  workspaces: Workspace[]; value: string | null; onChange: (tenantId: string | null) => void;
}) {
  return <section className="workspace-picker">
    <label htmlFor="workspace">작업 공간</label>
    <select id="workspace" value={value ?? ""} onChange={e => {
      const workspace = workspaces.find(w => w.tenant_id === e.target.value);
      onChange(workspace?.tenant_id ?? null);
    }}>
      <option value="">작업 공간을 선택하세요</option>
      {workspaces.map(w => <option key={w.tenant_id} value={w.tenant_id}>
        {[w.display_name, w.brand, w.product_name].filter(Boolean).join(" · ")}
      </option>)}
    </select>
    <p className="muted">작업 공간은 서버를 시작할 때 정한 그룹 하나만 보입니다. 바꾸려면 서버를 다시 시작하세요.</p>
  </section>;
}
