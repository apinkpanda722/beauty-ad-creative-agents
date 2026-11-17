"""One-time cleanup of stale ingredient rows left by shorter re-parses; no network."""

import json
from io import StringIO

from beautyads.domain.products import ProductKey
from beautyads.pipeline import ingredient_cleanup as c


class Store:
    def __init__(self, counts):
        self.counts = dict(counts)  # ProductKey -> stored row count
        self.trimmed = []

    def count_ingredients(self, key):
        return self.counts.get(key, 0)

    def trim_ingredients(self, key, keep):
        removed = max(0, self.counts.get(key, 0) - keep)
        self.counts[key] = min(self.counts.get(key, 0), keep)
        self.trimmed.append((key, keep))
        return removed


def candidates():
    return [
        {"index": 1, "brand": "abib", "url": "https://abib.com/p/1"},
        {"index": 2, "brand": "anua", "url": "https://anua.kr/p/2"},
        {"index": 3, "brand": "cosrx", "url": "https://cosrx.co.kr/p/3"},
    ]


def key(item):
    return ProductKey(brand=item["brand"], source_url=item["url"])


def report(*entries):
    return {"products": [{"index": i, "status": s, "n": n} for i, s, n in entries]}


def run_cleanup(report_data, store):
    rows = [
        {
            "index": p["index"],
            "status": p["status"],
            "ingredients": [{}] * p["n"],
        }
        for p in report_data["products"]
    ]
    out = StringIO()
    summary = c.cleanup(rows, candidates(), store, out)
    return summary, out.getvalue()


def test_only_products_with_more_stored_rows_than_the_latest_run_are_trimmed():
    k = [key(x) for x in candidates()]
    store = Store({k[0]: 12, k[1]: 10, k[2]: 7})
    summary, _ = run_cleanup(
        report((1, "done", 10), (2, "done", 10), (3, "done", 9)), store
    )
    assert store.trimmed == [(k[0], 10)]  # equal and smaller counts are untouched
    assert summary["products_checked"] == 3
    assert summary["products_trimmed"] == 1
    assert summary["rows_before"] == 29 and summary["rows_after"] == 27
    assert summary["rows_deleted"] == 2


def test_products_that_were_not_stored_by_the_run_are_never_touched():
    k = [key(x) for x in candidates()]
    store = Store({k[0]: 5})
    summary, _ = run_cleanup(report((1, "held", 0), (2, "pending", 0)), store)
    assert store.trimmed == [] and summary["products_checked"] == 0


def test_a_run_with_no_checked_products_is_not_a_success():
    # "Checked nothing, deleted nothing" must not read as a clean pass.
    summary, _ = run_cleanup(report(), Store({}))
    assert summary["products_checked"] == 0 and summary["ok"] is False


def test_the_cleanup_report_lists_each_trimmed_product_by_index():
    k = [key(x) for x in candidates()]
    store = Store({k[0]: 12})
    _, text = run_cleanup(report((1, "done", 10)), store)
    assert "TRIMMED index=1 before=12 after=10" in text


def test_report_file_is_read_through_main(tmp_path):
    path = tmp_path / "records.json"
    path.write_text(
        json.dumps(
            {
                "products": [
                    {"index": 1, "status": "done", "ingredients": [{}, {}]},
                ]
            }
        )
    )
    k = key(candidates()[0])
    store = Store({k: 4})
    out = StringIO()
    code = c.main(
        ["--report", str(path)],
        out=out,
        deps_factory=lambda: (candidates(), store),
    )
    assert code == 0 and store.counts[k] == 2
    assert '"rows_deleted": 2' in out.getvalue()
    assert (
        c.main(
            ["--report", str(tmp_path / "missing.json")],
            out=StringIO(),
            deps_factory=lambda: (candidates(), store),
        )
        == 2
    )
