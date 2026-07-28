"""Presentation helpers that keep templates free of data shaping logic."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence

_METRIC_NAMES = {
    "temperature_c": "Temperature (°C)",
    "humidity_pct": "Humidity (%)",
    "soil_moisture_pct": "Soil moisture (%)",
    "light_lux": "Light (lux)",
}
_TRACE_COLORS = {
    "temperature_c": "#9a5a2f",
    "humidity_pct": "#39708a",
    "soil_moisture_pct": "#2f6b50",
    "light_lux": "#a77a16",
}


def trend_plot_json(report: Mapping[str, object] | None) -> str:
    """Return Plotly-compatible local JSON for daily and weekly means."""

    payload: dict[str, object] = {
        "daily": _period_plot([], "Daily trends"),
        "weekly": _period_plot([], "Weekly trends"),
    }
    if report is not None:
        raw_trends = report.get("trends")
        if isinstance(raw_trends, Mapping):
            daily = _mapping_sequence(raw_trends.get("daily"))
            weekly = _mapping_sequence(raw_trends.get("weekly"))
            payload = {
                "daily": _period_plot(daily, "Daily trends"),
                "weekly": _period_plot(weekly, "Weekly trends"),
            }
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return encoded.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _mapping_sequence(value: object) -> tuple[Mapping[str, object], ...]:
    """Keep only mapping entries from a serialized trend sequence."""

    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return ()
    return tuple(item for item in value if isinstance(item, Mapping))


def _period_plot(
    aggregates: Sequence[Mapping[str, object]],
    title: str,
) -> dict[str, object]:
    """Build independent vertically stacked Plotly axes for four metrics."""

    grouped: defaultdict[str, list[Mapping[str, object]]] = defaultdict(list)
    for aggregate in aggregates:
        metric = aggregate.get("metric")
        if isinstance(metric, str) and metric in _METRIC_NAMES:
            grouped[metric].append(aggregate)

    traces: list[dict[str, object]] = []
    axes: dict[str, object] = {}
    ordered_metrics = tuple(_METRIC_NAMES)
    for index, metric in enumerate(ordered_metrics, start=1):
        values = grouped[metric]
        axis_suffix = "" if index == 1 else str(index)
        traces.append(
            {
                "type": "scatter",
                "mode": "lines+markers",
                "name": _METRIC_NAMES[metric],
                "x": [item.get("period_start") for item in values],
                "y": [item.get("mean") for item in values],
                "customdata": [
                    [
                        item.get("minimum"),
                        item.get("maximum"),
                        item.get("count"),
                    ]
                    for item in values
                ],
                "line": {"color": _TRACE_COLORS[metric], "width": 2},
                "marker": {"size": 5},
                "xaxis": f"x{axis_suffix}",
                "yaxis": f"y{axis_suffix}",
                "hovertemplate": (
                    "%{x}<br>mean %{y:.2f}<br>min %{customdata[0]:.2f}"
                    "<br>max %{customdata[1]:.2f}<br>samples %{customdata[2]}"
                    "<extra></extra>"
                ),
            }
        )
        top = 1.0 - (index - 1) * 0.25
        bottom = top - 0.18
        axes[f"yaxis{axis_suffix}"] = {
            "domain": [bottom, top],
            "title": {"text": _METRIC_NAMES[metric], "font": {"size": 11}},
            "gridcolor": "#d9e3dc",
            "zeroline": False,
        }
        axes[f"xaxis{axis_suffix}"] = {
            "anchor": f"y{axis_suffix}",
            "showticklabels": index == len(ordered_metrics),
            "gridcolor": "#edf2ee",
        }

    layout: dict[str, object] = {
        "title": {"text": title, "font": {"size": 16}, "x": 0.0},
        "height": 690,
        "margin": {"l": 80, "r": 24, "t": 48, "b": 48},
        "paper_bgcolor": "#ffffff",
        "plot_bgcolor": "#ffffff",
        "font": {
            "family": "system-ui, -apple-system, Segoe UI, sans-serif",
            "color": "#17201c",
            "size": 12,
        },
        "showlegend": False,
        "hovermode": "x unified",
        **axes,
    }
    return {"data": traces, "layout": layout}
