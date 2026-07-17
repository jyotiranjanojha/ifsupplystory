"""
LangGraph-powered BOM traversal workflow for IFSP root-cause explainability.

Graph topology
--------------

    check_demand
         |
    (unmet?)---NO---> synthesize ---> END
         |YES
    check_supply
         |
    (no supply & depth < max)---NO---> synthesize ---> END
         |YES
    drill_bom
         |
    (new frontier?)---NO---> synthesize ---> END
         |YES
    check_supply   (loop back)

Each node accumulates planning evidence into shared state without losing
context across loop iterations.
"""

import operator
from pathlib import Path
from typing import Annotated, Any, Dict, List, Optional

from langgraph.graph import END, StateGraph
from typing_extensions import TypedDict

from .analyzer import (
    INPUT_FOLDER,
    OUTPUT_FOLDER,
    _find_file_by_prefix,
    _fmt_date,
    _matches_context,
    _parse_date,
    _resolve_context,
    _safe_float,
    _safe_rows,
)

MAX_BOM_DEPTH = int(3)


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class BomDrillState(TypedDict):
    base_dir: str
    week_id: Optional[str]
    scenario_id: Optional[str]
    root_item: str
    site: str
    frontier: List[str]               # items queued for supply check
    visited: List[str]                # items already checked
    items_with_no_supply: List[str]   # items whose supply is zero (drives next drill)
    supply_map: Dict[str, Any]        # item -> supply evidence dict
    bom_tree: Dict[str, List[str]]    # parent item -> [child SUBORD items]
    demand_evidence: Dict[str, Any]   # demand summary for the root item
    depth: int                        # current BOM depth
    max_depth: int
    findings: Annotated[List[str], operator.add]  # append-only log of discoveries


# ---------------------------------------------------------------------------
# Helper – load supply quantities for one item
# ---------------------------------------------------------------------------

def _load_supply_for_item(
    output_dir: Path,
    item: str,
    week_id: Optional[str],
    scenario_id: Optional[str],
    site: str,
) -> Dict[str, Any]:
    plan_order_qty = 0.0
    plan_purch_qty = 0.0
    plan_arriv_qty = 0.0
    pegged_supply_qty = 0.0
    pegged_demand_qty = 0.0
    supply_dates: List[str] = []

    planorder_file = _find_file_by_prefix(output_dir, "by_if_snop_out_planorder-")
    planpurch_file = _find_file_by_prefix(output_dir, "by_if_snop_out_planpurch-")
    planarriv_file = _find_file_by_prefix(output_dir, "by_if_snop_out_planarriv-")
    inddmdlink_file = _find_file_by_prefix(output_dir, "by_if_snop_out_inddmdlink-")

    if planorder_file:
        for row in _safe_rows(planorder_file):
            if (row.get("ITEM") or "").strip() != item:
                continue
            if site and (row.get("LOC") or "").strip() != site:
                continue
            if not _matches_context(row, week_id, scenario_id):
                continue
            plan_order_qty += _safe_float(row.get("QTY"))
            d = _fmt_date(_parse_date(row.get("SCHEDDATE")))
            if d:
                supply_dates.append(d)

    if planpurch_file:
        for row in _safe_rows(planpurch_file):
            if (row.get("ITEM") or "").strip() != item:
                continue
            if site and (row.get("LOC") or "").strip() != site:
                continue
            if not _matches_context(row, week_id, scenario_id):
                continue
            plan_purch_qty += _safe_float(row.get("QTY"))
            d = _fmt_date(_parse_date(row.get("SCHEDDATE")))
            if d:
                supply_dates.append(d)

    if planarriv_file:
        for row in _safe_rows(planarriv_file):
            if (row.get("ITEM") or "").strip() != item:
                continue
            if site and (row.get("DEST") or "").strip() != site:
                continue
            if not _matches_context(row, week_id, scenario_id):
                continue
            plan_arriv_qty += _safe_float(row.get("QTY"))
            d = _fmt_date(_parse_date(row.get("SCHEDARRIVDATE")))
            if d:
                supply_dates.append(d)

    if inddmdlink_file:
        for row in _safe_rows(inddmdlink_file):
            if (row.get("SUPPLYITEM") or "").strip() != item:
                continue
            if site and (row.get("SUPPLYLOC") or "").strip() != site:
                continue
            if not _matches_context(row, week_id, scenario_id):
                continue
            pegged_supply_qty += _safe_float(row.get("SUPPLYPEGQTY"))
            pegged_demand_qty += _safe_float(row.get("DMDPEGQTY"))

    total_supply = plan_order_qty + plan_purch_qty + plan_arriv_qty
    return {
        "item": item,
        "plan_order_qty": round(plan_order_qty, 3),
        "plan_purch_qty": round(plan_purch_qty, 3),
        "plan_arriv_qty": round(plan_arriv_qty, 3),
        "total_planned_supply": round(total_supply, 3),
        "pegged_supply_qty": round(pegged_supply_qty, 3),
        "pegged_demand_qty": round(pegged_demand_qty, 3),
        "has_supply": total_supply > 0 or pegged_supply_qty > 0,
        "supply_dates_sample": sorted(set(supply_dates))[:5],
    }


# ---------------------------------------------------------------------------
# Node 1 – check_demand
# ---------------------------------------------------------------------------

def check_demand(state: BomDrillState) -> Dict[str, Any]:
    base_dir = Path(state["base_dir"])
    root_item = state["root_item"]
    week_id = state["week_id"]
    scenario_id = state["scenario_id"]
    site = state["site"]

    output_dir = base_dir / OUTPUT_FOLDER
    inddmdview_file = _find_file_by_prefix(output_dir, "by_if_snop_out_inddmdview-")

    demand_qty = 0.0
    scheduled_qty = 0.0
    demand_rows_count = 0
    need_dates: List[str] = []
    sched_dates_list: List[str] = []

    if inddmdview_file:
        for row in _safe_rows(inddmdview_file):
            if (row.get("ITEM") or "").strip() != root_item:
                continue
            if site and (row.get("LOC") or "").strip() != site:
                continue
            if not _matches_context(row, week_id, scenario_id):
                continue
            demand_rows_count += 1
            demand_qty += _safe_float(row.get("QTY"))
            scheduled_qty += _safe_float(row.get("SCHEDQTY"))
            d = _fmt_date(_parse_date(row.get("NEEDDATE")))
            if d:
                need_dates.append(d)
            s = _fmt_date(_parse_date(row.get("SCHEDDATE")))
            if s:
                sched_dates_list.append(s)

    unmet_qty = max(0.0, demand_qty - scheduled_qty)
    meet_status = (
        "Met" if demand_qty > 0 and scheduled_qty + 1e-6 >= demand_qty
        else ("Partially Met" if scheduled_qty > 0 else "Not Met")
    )

    evidence = {
        "root_item": root_item,
        "demand_rows": demand_rows_count,
        "demand_qty_total": round(demand_qty, 3),
        "scheduled_qty_total": round(scheduled_qty, 3),
        "unmet_qty": round(unmet_qty, 3),
        "meet_status": meet_status,
        "first_need_date": min(need_dates) if need_dates else None,
        "first_sched_date": min(sched_dates_list) if sched_dates_list else None,
    }

    finding = (
        f"[Depth 0] Root item {root_item}: demand={round(demand_qty,3)}, "
        f"scheduled={round(scheduled_qty,3)}, unmet={round(unmet_qty,3)}, "
        f"status={meet_status}."
    )

    return {
        "demand_evidence": evidence,
        "frontier": [root_item],
        "findings": [finding],
    }


def _route_after_demand(state: BomDrillState) -> str:
    unmet = (state.get("demand_evidence") or {}).get("unmet_qty", 0.0)
    if unmet and unmet > 0:
        return "check_supply"
    return "synthesize"


# ---------------------------------------------------------------------------
# Node 2 – check_supply
# ---------------------------------------------------------------------------

def check_supply(state: BomDrillState) -> Dict[str, Any]:
    base_dir = Path(state["base_dir"])
    week_id = state["week_id"]
    scenario_id = state["scenario_id"]
    site = state["site"]
    depth = state["depth"]
    frontier = state["frontier"]

    output_dir = base_dir / OUTPUT_FOLDER
    supply_map = dict(state.get("supply_map") or {})
    visited = list(state.get("visited") or [])
    items_with_no_supply: List[str] = []
    new_findings: List[str] = []

    for item in frontier:
        if item in visited:
            continue
        evidence = _load_supply_for_item(output_dir, item, week_id, scenario_id, site)
        supply_map[item] = evidence
        visited.append(item)

        if not evidence["has_supply"]:
            items_with_no_supply.append(item)
            new_findings.append(
                f"[Depth {depth}] Item {item}: NO supply found "
                f"(planorder=0, planpurch=0, planarriv=0, pegged=0) — queuing for BOM drill."
            )
        else:
            new_findings.append(
                f"[Depth {depth}] Item {item}: supply found — "
                f"total_planned={evidence['total_planned_supply']}, "
                f"pegged={evidence['pegged_supply_qty']}."
            )

    return {
        "supply_map": supply_map,
        "visited": visited,
        "frontier": [],
        "items_with_no_supply": items_with_no_supply,
        "findings": new_findings,
    }


def _route_after_supply(state: BomDrillState) -> str:
    no_supply = state.get("items_with_no_supply") or []
    depth = state.get("depth", 0)
    max_depth = state.get("max_depth", MAX_BOM_DEPTH)
    if no_supply and depth < max_depth:
        return "drill_bom"
    return "synthesize"


# ---------------------------------------------------------------------------
# Node 3 – drill_bom
# ---------------------------------------------------------------------------

def drill_bom(state: BomDrillState) -> Dict[str, Any]:
    base_dir = Path(state["base_dir"])
    site = state["site"]
    items_with_no_supply = state.get("items_with_no_supply") or []
    visited = list(state.get("visited") or [])
    bom_tree = dict(state.get("bom_tree") or {})
    depth = state.get("depth", 0)

    input_dir = base_dir / INPUT_FOLDER
    bom_file = _find_file_by_prefix(input_dir, "if_snop_billofmaterials-")
    alt_bom_file = _find_file_by_prefix(input_dir, "if_snop_altbillofmaterials-")

    new_frontier: List[str] = []
    new_findings: List[str] = []

    for parent_item in items_with_no_supply:
        children: List[str] = []

        if bom_file:
            for row in _safe_rows(bom_file):
                if (row.get("ITEM") or "").strip() != parent_item:
                    continue
                if site and (row.get("LOC") or "").strip() != site:
                    continue
                child = (row.get("SUBORD") or "").strip()
                if child and child not in children:
                    children.append(child)

        if alt_bom_file:
            for row in _safe_rows(alt_bom_file):
                if (row.get("ITEM") or "").strip() != parent_item:
                    continue
                if site and (row.get("LOC") or "").strip() != site:
                    continue
                child = (row.get("SUBORD") or "").strip()
                if child and child not in children:
                    children.append(child)

        bom_tree[parent_item] = children

        if children:
            new_findings.append(
                f"[Depth {depth}→{depth+1}] BOM drill: {parent_item} has "
                f"{len(children)} component(s): {children[:10]}."
            )
            for child in children:
                if child not in visited and child not in new_frontier:
                    new_frontier.append(child)
        else:
            new_findings.append(
                f"[Depth {depth}→{depth+1}] BOM drill: {parent_item} has NO BOM components — "
                "leaf item or missing BOM entry."
            )

    return {
        "bom_tree": bom_tree,
        "frontier": new_frontier,
        "depth": depth + 1,
        "findings": new_findings,
    }


def _route_after_drill(state: BomDrillState) -> str:
    frontier = state.get("frontier") or []
    if frontier:
        return "check_supply"
    return "synthesize"


# ---------------------------------------------------------------------------
# Node 4 – synthesize
# ---------------------------------------------------------------------------

def synthesize(state: BomDrillState) -> Dict[str, Any]:
    demand = state.get("demand_evidence") or {}
    supply_map = state.get("supply_map") or {}
    bom_tree = state.get("bom_tree") or {}
    findings = state.get("findings") or []
    root_item = state.get("root_item", "")

    # Build BOM path summary (root → children → grandchildren …)
    def _bom_path(item: str, tree: Dict[str, List[str]], depth: int = 0, visited: Optional[set] = None) -> List[str]:
        if visited is None:
            visited = set()
        if item in visited or depth > 10:
            return []
        visited.add(item)
        lines = [f"{'  ' * depth}{item}"]
        for child in tree.get(item, []):
            lines.extend(_bom_path(child, tree, depth + 1, visited))
        return lines

    bom_path_lines = _bom_path(root_item, bom_tree)

    # Identify gaps: items with no supply and no BOM children (true bottlenecks)
    bottleneck_items = [
        item for item, evidence in supply_map.items()
        if not evidence.get("has_supply") and not bom_tree.get(item)
    ]

    return {
        "findings": [
            f"[Synthesis] BOM traversal complete. "
            f"Depth reached: {state.get('depth', 0)}. "
            f"Items checked: {len(supply_map)}. "
            f"Bottleneck leaf items (no supply, no BOM): {bottleneck_items or 'none'}."
        ],
    }


# ---------------------------------------------------------------------------
# Graph compilation
# ---------------------------------------------------------------------------

def _build_graph() -> Any:
    builder: StateGraph = StateGraph(BomDrillState)

    builder.add_node("check_demand", check_demand)
    builder.add_node("check_supply", check_supply)
    builder.add_node("drill_bom", drill_bom)
    builder.add_node("synthesize", synthesize)

    builder.set_entry_point("check_demand")

    builder.add_conditional_edges(
        "check_demand",
        _route_after_demand,
        {"check_supply": "check_supply", "synthesize": "synthesize"},
    )
    builder.add_conditional_edges(
        "check_supply",
        _route_after_supply,
        {"drill_bom": "drill_bom", "synthesize": "synthesize"},
    )
    builder.add_conditional_edges(
        "drill_bom",
        _route_after_drill,
        {"check_supply": "check_supply", "synthesize": "synthesize"},
    )
    builder.add_edge("synthesize", END)

    return builder.compile()


_graph = _build_graph()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_bom_drill(
    base_dir: Path,
    week_id: Optional[str],
    scenario_id: Optional[str],
    root_item: str,
    scope: Dict[str, Any],
    max_depth: int = MAX_BOM_DEPTH,
) -> Dict[str, Any]:
    """
    Run the LangGraph BOM traversal workflow for a given root demand item.

    Traverses: check_demand → check_supply → drill_bom (loop) → synthesize.

    Returns a structured dict with demand evidence, supply map, BOM tree,
    bottleneck items, and ordered findings.
    """
    context = _resolve_context(base_dir, week_id, scenario_id)
    resolved_week = context.get("week_id")
    resolved_scenario = context.get("scenario_id")
    site = (scope.get("site") or "").strip()

    initial_state: BomDrillState = {
        "base_dir": str(base_dir),
        "week_id": resolved_week,
        "scenario_id": resolved_scenario,
        "root_item": root_item.strip(),
        "site": site,
        "frontier": [],
        "visited": [],
        "items_with_no_supply": [],
        "supply_map": {},
        "bom_tree": {},
        "demand_evidence": {},
        "depth": 0,
        "max_depth": max_depth,
        "findings": [],
    }

    final_state: BomDrillState = _graph.invoke(initial_state)

    demand = final_state.get("demand_evidence") or {}
    supply_map = final_state.get("supply_map") or {}
    bom_tree = final_state.get("bom_tree") or {}
    findings = final_state.get("findings") or []

    bottleneck_items = [
        item for item, ev in supply_map.items()
        if not ev.get("has_supply") and not bom_tree.get(item)
    ]

    return {
        "Workflow": "BOM Drill (LangGraph)",
        "Context Resolution": context,
        "Root Item": root_item,
        "Demand Evidence": demand,
        "BOM Tree": bom_tree,
        "Supply Map": supply_map,
        "Bottleneck Items (no supply, no BOM children)": bottleneck_items,
        "Depth Reached": final_state.get("depth", 0),
        "Items Checked": len(supply_map),
        "Traversal Findings": findings,
        "Note": (
            "BOM traversal follows: demand check → supply check → BOM component drill "
            f"(max {max_depth} levels). Context is preserved across all loop iterations."
        ),
    }
