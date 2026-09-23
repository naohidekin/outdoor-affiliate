import test from "node:test";
import assert from "node:assert/strict";
import { selectDateRangeMetricValues } from "../src/lib/ga4-date-range.mjs";

test("GA4の行順が前週・対象週でも date_range ラベルで正しく分類する", () => {
  const rows = [
    {
      dimensionValues: [{ value: "date_range_1" }],
      metricValues: [{ value: "1102" }, { value: "945" }],
    },
    {
      dimensionValues: [{ value: "date_range_0" }],
      metricValues: [{ value: "860" }, { value: "760" }],
    },
  ];

  const ranges = selectDateRangeMetricValues(rows);

  assert.deepEqual(ranges.current, [{ value: "860" }, { value: "760" }]);
  assert.deepEqual(ranges.previous, [{ value: "1102" }, { value: "945" }]);
});
