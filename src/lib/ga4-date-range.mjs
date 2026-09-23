export function selectDateRangeMetricValues(rows = []) {
  const metricsFor = (dateRange) =>
    rows.find((row) =>
      row.dimensionValues?.some((dimension) => dimension.value === dateRange)
    )?.metricValues || [];

  return {
    current: metricsFor("date_range_0"),
    previous: metricsFor("date_range_1"),
  };
}
