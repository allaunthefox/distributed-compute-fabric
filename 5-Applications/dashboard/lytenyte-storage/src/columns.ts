/**
 * columns.ts — LyteNyte column definitions for spatial hash grid.
 *
 * Uses the headless column API: id + field + cellRenderer for custom rendering.
 */

import { createElement } from "react";
import type { Grid } from "@1771technologies/lytenyte-core";
import type { SpatialHashRow, VoltageMode } from "./data";

export type LnColumn = Grid.Column<Grid.GridSpec<SpatialHashRow>>;

const VOLTAGE_COLORS: Record<VoltageMode, string> = {
  STORE: "#4a90d9",
  COMPUTE: "#50c878",
  APPROX: "#e8a838",
  MORPHIC: "#e05050",
};

/** Interpolate between two hex colors based on t in [0,1] */
function lerpColor(a: string, b: string, t: number): string {
  const ah = parseInt(a.slice(1), 16);
  const bh = parseInt(b.slice(1), 16);
  const ar = (ah >> 16) & 0xff,
    ag = (ah >> 8) & 0xff,
    ab = ah & 0xff;
  const br = (bh >> 16) & 0xff,
    bg = (bh >> 8) & 0xff,
    bb = bh & 0xff;
  const rr = Math.round(ar + (br - ar) * t);
  const rg = Math.round(ag + (bg - ag) * t);
  const rb = Math.round(ab + (bb - ab) * t);
  return `rgb(${rr},${rg},${rb})`;
}

const cellBoxStyle = (bg: string): React.CSSProperties => ({
  backgroundColor: bg,
  color: "#fff",
  width: "100%",
  height: "100%",
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  fontSize: 13,
  fontVariantNumeric: "tabular-nums",
});

export function createColumns(): LnColumn[] {
  return [
    {
      id: "x",
      name: "X",
      field: "x",
      width: 60,
      widthMin: 40,
    },
    {
      id: "y",
      name: "Y",
      field: "y",
      width: 60,
      widthMin: 40,
    },
    {
      id: "z",
      name: "Z",
      field: "z",
      width: 60,
      widthMin: 40,
    },
    {
      id: "density",
      name: "Density",
      field: "density",
      width: 100,
      widthMin: 70,
      cellRenderer: ({ row }) => {
        const v = row.data!.density;
        const t = v / 255;
        const bg = lerpColor("#000000", "#ff3030", t);
        return createElement("div", { style: cellBoxStyle(bg) }, v);
      },
    },
    {
      id: "fd",
      name: "FD",
      field: "fd",
      width: 80,
      widthMin: 60,
      cellRenderer: ({ row }) => {
        const v = row.data!.fd;
        const t = Math.min(1, Math.max(0, v - 2.0));
        const bg = lerpColor("#2040a0", "#ff3030", t);
        return createElement("div", { style: cellBoxStyle(bg) }, v.toFixed(2));
      },
    },
    {
      id: "voltage_mode",
      name: "Voltage Mode",
      field: "voltage_mode",
      width: 130,
      widthMin: 100,
      cellRenderer: ({ row }) => {
        const mode = row.data!.voltage_mode;
        const bg = VOLTAGE_COLORS[mode];
        return createElement(
          "div",
          {
            style: {
              ...cellBoxStyle(bg),
              fontWeight: 600,
              letterSpacing: 0.5,
              fontSize: 12,
            },
          },
          mode
        );
      },
    },
    {
      id: "particle_count",
      name: "Particles",
      field: "particle_count",
      width: 100,
      widthMin: 70,
    },
    {
      id: "max_neighbor",
      name: "Max Neigh",
      field: "max_neighbor",
      width: 90,
      widthMin: 60,
    },
  ];
}
