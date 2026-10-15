import "uplot/dist/uPlot.min.css";

import { Card, Text } from "@mantine/core";
import { useEffect, useRef } from "react";
import uPlot from "uplot";

interface Series {
  name: string;
  points: [string | number, number][];
}

export interface ChartSpec {
  kind: "line" | "bar" | "area";
  title?: string;
  x_type: "time" | "category" | "number";
  unit?: string;
  series: Series[];
}

const COLORS = ["#4c6ef5", "#12b886", "#fa5252", "#fab005", "#7950f2", "#15aabf"];

export function Chart({ spec }: { spec: ChartSpec }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || !spec.series.length) return;
    const labels = spec.series[0].points.map((p) => p[0]);
    const xs =
      spec.x_type === "time"
        ? labels.map((l) => (typeof l === "number" ? l : Date.parse(String(l)) / 1000))
        : spec.x_type === "number"
          ? labels.map(Number)
          : labels.map((_, i) => i);
    const data: uPlot.AlignedData = [xs, ...spec.series.map((s) => s.points.map((p) => p[1]))];
    const bars = spec.kind === "bar" ? uPlot.paths.bars?.({ size: [0.6, 60] }) : undefined;
    const plot = new uPlot(
      {
        width: el.clientWidth || 600,
        height: 280,
        legend: { live: false }, // series names only; no cursor values on a wall display
        scales: { x: { time: spec.x_type === "time" } },
        axes: [
          {
            // Categories: one tick per data point (no fractional splits with repeated labels).
            splits: spec.x_type === "category" ? () => xs : undefined,
            values:
              spec.x_type === "category"
                ? (_u: uPlot, splits: number[]) => splits.map((v) => String(labels[Math.round(v)] ?? ""))
                : undefined,
          },
          { label: spec.unit },
        ],
        series: [
          {},
          ...spec.series.map((s, i) => ({
            label: s.name,
            stroke: COLORS[i % COLORS.length],
            fill: spec.kind === "area" ? `${COLORS[i % COLORS.length]}33` : undefined,
            paths: bars,
            width: 2,
          })),
        ],
      },
      data,
      el,
    );
    const onResize = () => plot.setSize({ width: el.clientWidth, height: 280 });
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      plot.destroy();
    };
  }, [spec]);
  return (
    <Card withBorder>
      {spec.title && (
        <Text fw={600} mb="xs">
          {spec.title}
        </Text>
      )}
      <div ref={ref} style={{ width: "100%" }} />
    </Card>
  );
}
