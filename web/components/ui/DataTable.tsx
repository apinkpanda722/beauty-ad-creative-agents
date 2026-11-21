"use client";

import type { ReactNode } from "react";
import { EmptyState } from "./EmptyState";
import type { EmptyStateProps } from "./EmptyState";

export type DataTableColumn<T> = {
  key: string;
  header: ReactNode;
  render: (row: T) => ReactNode;
};
export type DataTableProps<T> = {
  caption: string;
  columns: readonly DataTableColumn<T>[];
  rows: readonly T[];
  rowKey: (row: T) => string;
  value?: string | null;
  onChange?: (value: string) => void;
  emptyState: EmptyStateProps;
};

export function DataTable<T>({ caption, columns, rows, rowKey, value, onChange, emptyState }: DataTableProps<T>) {
  return <div className="gs-ui gs-table-scroll">
    <table className="gs-data-table">
      <caption className="gs-table-caption">{caption}</caption>
      <thead><tr>{columns.map(column => <th key={column.key} scope="col">{column.header}</th>)}</tr></thead>
      <tbody>{rows.length ? rows.map(row => {
        const key = rowKey(row);
        return <tr key={key} className={onChange ? "gs-table-row-selectable" : undefined}
          aria-selected={onChange ? value === key : undefined} tabIndex={onChange ? 0 : undefined}
          onClick={event => {
            if (!(event.target as Element).closest("a, button, input, select, textarea, [role='button']")) onChange?.(key);
          }}
          onKeyDown={event => {
            if (onChange && event.target === event.currentTarget && (event.key === "Enter" || event.key === " ")) {
              event.preventDefault();
              onChange(key);
            }
          }}>
          {columns.map(column => <td key={column.key}>{column.render(row)}</td>)}
        </tr>;
      }) : <tr><td colSpan={Math.max(1, columns.length)}><EmptyState {...emptyState} /></td></tr>}</tbody>
    </table>
  </div>;
}
