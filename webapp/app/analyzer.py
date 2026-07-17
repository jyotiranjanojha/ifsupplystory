import csv
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
from urllib import error, request


INPUT_FOLDER = "by_input"
OUTPUT_FOLDER = "by_output"
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:latest")


def _safe_rows(file_path: Path) -> Iterable[dict]:
    with file_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="|")
        for row in reader:
            yield row


def _list_csv_files(folder: Path) -> List[Path]:
    if not folder.exists():
        return []
    return sorted([p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".csv"])


def _file_summary(file_path: Path) -> Dict:
    row_count = 0
    columns: List[str] = []
    with file_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, delimiter="|")
        for idx, row in enumerate(reader):
            if idx == 0:
                columns = row
            else:
                row_count += 1
    return {
        "file": file_path.name,
        "rows": row_count,
        "columns": columns,
        "column_count": len(columns),
    }


def dataset_inventory(base_dir: Path) -> Dict:
    input_dir = base_dir / INPUT_FOLDER
    output_dir = base_dir / OUTPUT_FOLDER
    input_files = _list_csv_files(input_dir)
    output_files = _list_csv_files(output_dir)
    return {
        "input_folder": str(input_dir),
        "output_folder": str(output_dir),
        "input_files": [_file_summary(f) for f in input_files],
        "output_files": [_file_summary(f) for f in output_files],
        "input_file_count": len(input_files),
        "output_file_count": len(output_files),
    }


def _find_file_by_prefix(folder: Path, prefix: str) -> Optional[Path]:
    candidates = sorted(folder.glob(f"{prefix}*.csv"))
    return candidates[0] if candidates else None


def _load_key_set(file_path: Optional[Path], column: str, normalize_decimal: bool = False) -> set:
    keys = set()
    if not file_path:
        return keys
    for row in _safe_rows(file_path):
        val = (row.get(column) or "").strip()
        if not val:
            continue
        if normalize_decimal and val.endswith(".0"):
            val = val[:-2]
        keys.add(val)
    return keys


def _count_orphans(file_path: Optional[Path], column: str, valid_set: set, normalize_decimal: bool = False) -> int:
    if not file_path:
        return 0
    bad = 0
    for row in _safe_rows(file_path):
        val = (row.get(column) or "").strip()
        if not val:
            continue
        check_val = val[:-2] if normalize_decimal and val.endswith(".0") else val
        if check_val not in valid_set:
            bad += 1
    return bad


def _safe_float(value: Optional[str]) -> float:
    try:
        return float((value or "").strip())
    except (TypeError, ValueError):
        return 0.0


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text, "%d-%b-%Y")
    except ValueError:
        return None


def _fmt_date(value: Optional[datetime]) -> Optional[str]:
    if not value:
        return None
    return value.strftime("%Y-%m-%d")


def _scenario_match(candidate: str, scenario_id: str) -> bool:
    c = candidate.strip().upper()
    s = scenario_id.strip().upper()
    if not c or not s:
        return False
    return c == s or c.startswith(f"{s}_")


def _normalize_week_id(week_id: Optional[str]) -> Optional[str]:
    value = (week_id or "").strip()
    return value or None


def _normalize_scenario_id(scenario_id: Optional[str]) -> Optional[str]:
    value = (scenario_id or "").strip()
    return value or None


def _parse_solve_version_sort_key(value: Optional[str]) -> Tuple[int, str]:
    text = (value or "").strip()
    match = re.search(r"(\d{4}-\d{2}-\d{2})_(\d{4})", text)
    if match:
        try:
            dt = datetime.strptime(f"{match.group(1)} {match.group(2)}", "%Y-%m-%d %H%M")
            return (int(dt.timestamp()), text)
        except ValueError:
            pass
    return (0, text)


def _collect_context_catalog(base_dir: Path) -> Dict:
    output_dir = base_dir / OUTPUT_FOLDER
    catalog = {}

    for file_path in _list_csv_files(output_dir):
        for row in _safe_rows(file_path):
            week = (row.get("CAPTURE_WK") or "").strip()
            scenario = (row.get("SIMULATION_NAME") or "").strip()
            solve_version = (row.get("SOLVE_VERSION") or "").strip()
            capture_type = (row.get("CAPTURE_TYPE") or "").strip()
            if not week:
                continue

            week_bucket = catalog.setdefault(week, {})
            if scenario:
                current = week_bucket.get(scenario)
                sort_key = _parse_solve_version_sort_key(solve_version)
                if current is None or sort_key > current["sort_key"]:
                    week_bucket[scenario] = {
                        "solve_version": solve_version or None,
                        "capture_type": capture_type or None,
                        "sort_key": sort_key,
                    }

    return catalog


def _rank_scenarios(catalog: Dict, week_id: Optional[str]) -> List[str]:
    if not week_id or week_id not in catalog:
        return []
    ranked = sorted(
        catalog[week_id].items(),
        key=lambda item: (item[1]["sort_key"], item[0]),
        reverse=True,
    )
    return [scenario for scenario, _meta in ranked]


def _resolve_context(base_dir: Path, week_id: Optional[str], scenario_id: Optional[str]) -> Dict:
    requested_week = _normalize_week_id(week_id)
    requested_scenario = _normalize_scenario_id(scenario_id)
    catalog = _collect_context_catalog(base_dir)
    weeks = sorted(catalog.keys())
    latest_week = weeks[-1] if weeks else None

    resolved_week = requested_week if requested_week in catalog else (requested_week or latest_week)
    ranked_scenarios = _rank_scenarios(catalog, resolved_week)

    resolved_scenario = requested_scenario
    if requested_scenario and resolved_week in catalog:
        matched = next((name for name in ranked_scenarios if _scenario_match(name, requested_scenario)), None)
        resolved_scenario = matched or requested_scenario
    elif not requested_scenario:
        resolved_scenario = ranked_scenarios[0] if ranked_scenarios else None

    notes = []
    if requested_week is None and resolved_week:
        notes.append(f"Week ID not provided. Defaulted to latest CAPTURE_WK: {resolved_week}.")
    elif requested_week and requested_week not in catalog and latest_week:
        notes.append(f"Requested Week ID '{requested_week}' was not found. Defaulted to latest CAPTURE_WK: {latest_week}.")

    if requested_scenario is None and resolved_scenario:
        notes.append(f"Scenario ID not provided. Defaulted to latest SIMULATION_NAME in week {resolved_week}: {resolved_scenario}.")
    elif requested_scenario and resolved_week in catalog and resolved_scenario == requested_scenario and requested_scenario not in catalog.get(resolved_week, {}):
        notes.append(f"Requested Scenario ID '{requested_scenario}' was not found in SIMULATION_NAME for week {resolved_week}.")

    return {
        "requested_week_id": requested_week,
        "requested_scenario_id": requested_scenario,
        "week_id": resolved_week,
        "scenario_id": resolved_scenario,
        "latest_week_id": latest_week,
        "available_weeks": weeks,
        "available_scenarios_for_week": ranked_scenarios,
        "notes": notes,
    }


def _resolve_compare_context(base_dir: Path, week_id: Optional[str], base_scenario_id: Optional[str], compare_scenario_id: Optional[str]) -> Dict:
    week_context = _resolve_context(base_dir, week_id, None)
    resolved_week = week_context["week_id"]
    ranked_scenarios = week_context["available_scenarios_for_week"]

    def match_requested(requested: Optional[str]) -> Optional[str]:
        req = _normalize_scenario_id(requested)
        if not req:
            return None
        return next((name for name in ranked_scenarios if _scenario_match(name, req)), req)

    base_resolved = match_requested(base_scenario_id)
    compare_resolved = match_requested(compare_scenario_id)

    if not base_resolved and not compare_resolved:
        if len(ranked_scenarios) >= 2:
            compare_resolved = ranked_scenarios[0]
            base_resolved = ranked_scenarios[1]
        elif len(ranked_scenarios) == 1:
            base_resolved = ranked_scenarios[0]
            compare_resolved = ranked_scenarios[0]
    elif not base_resolved:
        base_resolved = next((name for name in ranked_scenarios if name != compare_resolved), compare_resolved)
    elif not compare_resolved:
        compare_resolved = next((name for name in ranked_scenarios if name != base_resolved), base_resolved)

    notes = list(week_context["notes"])
    if not _normalize_scenario_id(base_scenario_id) and base_resolved:
        notes.append(f"Base Scenario ID not provided. Defaulted using SIMULATION_NAME: {base_resolved}.")
    if not _normalize_scenario_id(compare_scenario_id) and compare_resolved:
        notes.append(f"Compare Scenario ID not provided. Defaulted using SIMULATION_NAME: {compare_resolved}.")
    if len(set([s for s in [base_resolved, compare_resolved] if s])) < 2:
        notes.append("Only one SIMULATION_NAME is available for the resolved week, so scenario comparison is limited.")

    return {
        "requested_week_id": week_context["requested_week_id"],
        "week_id": resolved_week,
        "base_scenario_id": base_resolved,
        "compare_scenario_id": compare_resolved,
        "available_scenarios_for_week": ranked_scenarios,
        "notes": notes,
    }


def _extract_item_candidates(question: str) -> List[str]:
    q = question or ""
    candidates: List[str] = []
    patterns = [
        r"\bdemand\s+(?:for|item)\s*[:=]?\s*([A-Za-z0-9\-]+)",
        r"\bitem\s*[:=]?\s*([A-Za-z0-9\-]+)",
        r"\bfor\s+([A-Za-z0-9\-]{6,})\b",
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, q, flags=re.IGNORECASE):
            value = (match.group(1) or "").strip(" .,:;!?()[]{}")
            if value and value not in candidates:
                candidates.append(value)

    numeric_tokens = re.findall(r"\b\d{6,}\b", q)
    for token in numeric_tokens:
        if token not in candidates:
            candidates.append(token)

    return candidates


def _infer_demand_item_from_question(question: str) -> Dict:
    q = (question or "").strip()
    ql = q.lower()
    candidates = _extract_item_candidates(q)
    demand_language = any(term in ql for term in ["demand", "met", "meet", "unmet", "fulfilled", "root cause", "lineage"])

    selected = candidates[0] if len(candidates) == 1 else None
    if not selected and demand_language and len(candidates) > 0:
        demand_for = re.search(r"\bdemand\s+for\s+([A-Za-z0-9\-]+)", q, flags=re.IGNORECASE)
        if demand_for:
            selected = demand_for.group(1).strip()

    confidence = "high" if selected else ("low" if candidates else "none")
    reason = ""
    if selected:
        reason = "Single likely ITEM candidate found in the question."
    elif len(candidates) > 1:
        reason = "Multiple ITEM-like identifiers were found in the question."
    else:
        reason = "No ITEM-like identifier was found in the question."

    return {
        "selected_item": selected,
        "candidates": candidates,
        "confidence": confidence,
        "demand_language": demand_language,
        "reason": reason,
    }


def _item_demand_evidence(base_dir: Path, week_id: Optional[str], scenario_id: Optional[str], item_id: Optional[str], scope: Dict) -> Dict:
    item = (item_id or "").strip()
    if not item:
        return {"item": None, "demand_rows": 0, "extorder_hits": 0, "headerextref_hits": 0, "site_filtered": bool((scope.get("site") or "").strip())}

    output_dir = base_dir / OUTPUT_FOLDER
    inddmdview_file = _find_file_by_prefix(output_dir, "by_if_snop_out_inddmdview-")
    site = (scope.get("site") or "").strip()
    demand_rows = 0
    extorder_hits = 0
    header_hits = 0

    if inddmdview_file:
        for row in _safe_rows(inddmdview_file):
            if (row.get("ITEM") or "").strip() != item:
                continue
            if site and (row.get("LOC") or "").strip() != site:
                continue
            if not _matches_context(row, week_id, scenario_id):
                continue
            demand_rows += 1
            if (row.get("EXTORDERID") or "").strip():
                extorder_hits += 1
            if (row.get("HEADEREXTREF") or "").strip():
                header_hits += 1

    return {
        "item": item,
        "demand_rows": demand_rows,
        "extorder_hits": extorder_hits,
        "headerextref_hits": header_hits,
        "site_filtered": bool(site),
        "is_demand_item": demand_rows > 0 and (extorder_hits > 0 or header_hits > 0),
    }


def _matches_context(row: Dict[str, str], week_id: Optional[str], scenario_id: Optional[str]) -> bool:
    if week_id and (row.get("CAPTURE_WK") or "").strip() != week_id:
        return False

    if scenario_id:
        scenario_candidates = [
            (row.get("SIMULATION_NAME") or ""),
        ]
        if not any(_scenario_match(value, scenario_id) for value in scenario_candidates):
            return False

    return True


def _ollama_chat(prompt: str, system_prompt: str) -> Optional[str]:
    return _ollama_chat_with_model(prompt, system_prompt, OLLAMA_MODEL)


def _ollama_chat_with_model(
    prompt: str,
    system_prompt: str,
    model_name: Optional[str],
    history: Optional[List[Dict[str, str]]] = None,
) -> Optional[str]:
    selected_model = (model_name or OLLAMA_MODEL).strip() or OLLAMA_MODEL
    messages = [{"role": "system", "content": system_prompt}]

    for msg in (history or []):
        role = (msg.get("role") or "").strip().lower()
        content = (msg.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": selected_model,
        "stream": False,
        "messages": messages,
        "options": {
            "temperature": 0.2,
        },
    }

    data = json.dumps(payload).encode("utf-8")
    req = request.Request(
        f"{OLLAMA_BASE_URL}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=60) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None

    message = body.get("message") or {}
    content = (message.get("content") or "").strip()
    return content or None


def list_ollama_models() -> Dict:
    req = request.Request(f"{OLLAMA_BASE_URL}/api/tags", method="GET")
    try:
        with request.urlopen(req, timeout=15) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return {
            "provider": "Ollama",
            "reachable": False,
            "default_model": OLLAMA_MODEL,
            "models": [],
        }

    models = []
    for model in body.get("models", []):
        name = (model.get("name") or "").strip()
        if name:
            models.append(name)

    return {
        "provider": "Ollama",
        "reachable": True,
        "default_model": OLLAMA_MODEL,
        "models": models,
    }


def _summarize_with_ollama(
    question: str,
    workflow: str,
    result: Dict,
    note: Optional[str] = None,
    llm_model: Optional[str] = None,
) -> Optional[Dict]:
    system_prompt = (
        "You are a Blue Yonder Enterprise Supply Planning expert for Intel Foundry workflows. "
        "Use only the grounded evidence provided. Do not invent data. "
        "Explain results in simple English for planners. "
        "If evidence is incomplete, say so clearly. "
        "Never claim a field is missing if it is present in the grounded result. "
        "If grounded result shows no data gaps, write 'Data Gaps: None'."
    )

    prompt_parts = [
        f"User question: {question}",
        f"Workflow: {workflow}",
        f"Grounded result JSON: {json.dumps(result, ensure_ascii=True)}",
    ]
    if note:
        prompt_parts.append(f"Additional note: {note}")
    prompt_parts.append(
        "Write a short answer with these sections: Answer, Key Evidence, Data Gaps, Next Step. "
        "Keep it concise and planner-friendly. "
        "Only mention facts that are explicitly present in the grounded result JSON."
    )

    selected_model = (llm_model or OLLAMA_MODEL).strip() or OLLAMA_MODEL
    answer = _ollama_chat_with_model("\n\n".join(prompt_parts), system_prompt, selected_model)
    if not answer:
        return None

    return {
        "Assistant Reply": answer,
        "Workflow": workflow,
        "Grounded Result": result,
        "LLM Provider": "Ollama",
        "LLM Model": selected_model,
    }


def run_validation(base_dir: Path, week_id: Optional[str], scenario_id: Optional[str], scope: Dict, focus_areas: List[str]) -> Dict:
    context = _resolve_context(base_dir, week_id, scenario_id)
    week_id = context["week_id"]
    scenario_id = context["scenario_id"]
    input_dir = base_dir / INPUT_FOLDER
    output_dir = base_dir / OUTPUT_FOLDER

    required_input_prefixes = [
        "if_snop_items-",
        "if_snop_locations-",
        "if_snop_customer-",
        "if_snop_billofmaterials-",
        "if_snop_sku-",
        "if_snop_sourcing-",
        "if_snop_productionmethod-",
    ]
    required_output_prefixes = [
        "by_if_snop_out_planorder-",
        "by_if_snop_out_skuexception-",
        "by_if_snop_out_resloaddetail-",
    ]

    missing_input = [p for p in required_input_prefixes if _find_file_by_prefix(input_dir, p) is None]
    missing_output = [p for p in required_output_prefixes if _find_file_by_prefix(output_dir, p) is None]

    items = _find_file_by_prefix(input_dir, "if_snop_items-")
    locs = _find_file_by_prefix(input_dir, "if_snop_locations-")
    cust = _find_file_by_prefix(input_dir, "if_snop_customer-")
    bom = _find_file_by_prefix(input_dir, "if_snop_billofmaterials-")
    sku = _find_file_by_prefix(input_dir, "if_snop_sku-")
    src = _find_file_by_prefix(input_dir, "if_snop_sourcing-")
    prod = _find_file_by_prefix(input_dir, "if_snop_productionmethod-")

    item_keys = _load_key_set(items, "ITEM")
    loc_keys = _load_key_set(locs, "LOC")
    cust_keys = _load_key_set(cust, "CUST", normalize_decimal=True)

    checks = {
        "bom_orphan_parent_item": _count_orphans(bom, "ITEM", item_keys),
        "bom_orphan_component_item": _count_orphans(bom, "SUBORD", item_keys),
        "bom_orphan_location": _count_orphans(bom, "LOC", loc_keys),
        "sku_missing_item": _count_orphans(sku, "ITEM", item_keys),
        "sku_missing_location": _count_orphans(sku, "LOC", loc_keys),
        "sku_missing_customer": _count_orphans(sku, "CUST", cust_keys, normalize_decimal=True),
        "sourcing_missing_source_location": _count_orphans(src, "SOURCE", loc_keys),
        "sourcing_missing_dest_location": _count_orphans(src, "DEST", loc_keys),
        "prod_method_missing_item": _count_orphans(prod, "ITEM", item_keys),
        "prod_method_missing_location": _count_orphans(prod, "LOC", loc_keys),
    }

    critical = []
    high = []
    medium = []
    low = []

    if missing_input or missing_output:
        critical.append("Missing required input/output datasets.")

    for metric, value in checks.items():
        if value > 0:
            if metric in {"bom_orphan_parent_item", "bom_orphan_component_item", "bom_orphan_location"}:
                high.append(f"{metric}: {value}")
            elif metric in {"sku_missing_customer", "sourcing_missing_dest_location", "sourcing_missing_source_location"}:
                medium.append(f"{metric}: {value}")
            else:
                low.append(f"{metric}: {value}")

    if critical:
        verdict = "Fail"
    elif high:
        verdict = "Conditional Pass"
    else:
        verdict = "Pass"

    scope_summary = {
        "week_id": week_id,
        "scenario_id": scenario_id,
        "week_column": "CAPTURE_WK",
        "scenario_column": "SIMULATION_NAME",
        "scope": scope,
        "focus_areas": focus_areas,
    }

    data_gaps = []
    if not week_id:
        data_gaps.append("no CAPTURE_WK found in available output datasets")
    if not scenario_id:
        data_gaps.append("no SIMULATION_NAME found in available output datasets")

    return {
        "Validation Scope": scope_summary,
        "Datasets and Evidence Used": {
            "source_priority": ["by_input", "by_output", "Snowflake fallback"],
            "missing_input_prefixes": missing_input,
            "missing_output_prefixes": missing_output,
            "context_resolution": context,
        },
        "Checks Executed": checks,
        "Issues Found (Critical, High, Medium, Low)": {
            "Critical": critical,
            "High": high,
            "Medium": medium,
            "Low": low,
        },
        "Readiness Verdict (Pass, Conditional Pass, Fail)": verdict,
        "Root Causes and Likely Planning Impact": [
            "Missing or orphan keys can break demand-supply linkage and planning feasibility.",
            "Missing customer or location mappings can distort allocation and exception interpretation.",
        ],
        "Recommended Fixes (ordered by impact)": [
            "Fix all missing required dataset families first.",
            "Repair orphan BOM references and key mismatches.",
            "Normalize key formats for customer IDs between SKU and customer master.",
            "Re-run validation for the same week/scenario after corrections.",
        ],
        "Confidence and Data Gaps": {
            "confidence": "Medium",
            "data_gaps": data_gaps,
        },
    }


def run_scenario_compare(base_dir: Path, week_id: Optional[str], base_scenario_id: Optional[str], compare_scenario_id: Optional[str], scope: Dict, metrics: List[str]) -> Dict:
    context = _resolve_compare_context(base_dir, week_id, base_scenario_id, compare_scenario_id)
    week_id = context["week_id"]
    base_scenario_id = context["base_scenario_id"]
    compare_scenario_id = context["compare_scenario_id"]
    inventory = dataset_inventory(base_dir)

    data_gaps = []
    if not week_id:
        data_gaps.append("no CAPTURE_WK found in available output datasets")
    if not base_scenario_id or not compare_scenario_id:
        data_gaps.append("SIMULATION_NAME values are insufficient for comparison")

    # Current local files are run snapshots; explicit scenario columns may be absent.
    comparability_notes = [
        "Using by_input and by_output folder snapshots as comparison evidence.",
        "If scenario dimension is absent in file schema, comparison is treated as snapshot-level unless Snowflake metadata is provided.",
    ]

    top_output_tables = sorted(inventory["output_files"], key=lambda x: x["rows"], reverse=True)[:5]

    return {
        "Comparison Scope": {
            "week_id": week_id,
            "week_column": "CAPTURE_WK",
            "base_scenario_id": base_scenario_id,
            "compare_scenario_id": compare_scenario_id,
            "scenario_column": "SIMULATION_NAME",
            "scope": scope,
            "metrics": metrics,
        },
        "Data and Evidence Used": {
            "input_folder": inventory["input_folder"],
            "output_folder": inventory["output_folder"],
            "comparability_notes": comparability_notes,
            "context_resolution": context,
        },
        "Top Delta Metrics (ranked)": [
            "Snapshot comparison requires scenario-tagged evidence.",
            "Provide Snowflake scenario views for metric-accurate deltas.",
        ],
        "Likely Drivers and Root Causes": [
            "Master data, BOM, or parameter changes in by_input can drive output deltas.",
            "Resource exceptions and order link shifts in by_output are likely contributors.",
        ],
        "Confirmed Findings vs Hypotheses": {
            "confirmed": [f"Top output tables by row volume: {[t['file'] for t in top_output_tables]}"],
            "hypotheses": [
                "Scenario-level KPI deltas cannot be fully confirmed without scenario-grain fields or Snowflake joins.",
            ],
        },
        "Confidence and Data Gaps": {
            "confidence": "Low-Medium",
            "data_gaps": data_gaps,
        },
        "Recommended Next Checks": [
            "Provide scenario-grain metadata or Snowflake view mapping.",
            "Pin one metric and one entity scope for first validated delta run.",
        ],
    }


def run_root_cause(base_dir: Path, week_id: Optional[str], scenario_id: Optional[str], demand_id: Optional[str], scope: Dict) -> Dict:
    # In this app, demand_id is treated as the demand ITEM identifier.
    context = _resolve_context(base_dir, week_id, scenario_id)
    week_id = context["week_id"]
    scenario_id = context["scenario_id"]
    demand_item = (demand_id or "").strip()

    input_dir = base_dir / INPUT_FOLDER
    output_dir = base_dir / OUTPUT_FOLDER
    exception_file = _find_file_by_prefix(output_dir, "by_if_snop_out_skuexception-")
    relation_file = _find_file_by_prefix(output_dir, "by_if_snop_out_exceptionorderrelation-")
    inddmdview_file = _find_file_by_prefix(output_dir, "by_if_snop_out_inddmdview-")
    inddmdlink_file = _find_file_by_prefix(output_dir, "by_if_snop_out_inddmdlink-")
    resload_link_file = _find_file_by_prefix(output_dir, "by_if_snop_out_resloadinddmdlink-")
    planarriv_file = _find_file_by_prefix(output_dir, "by_if_snop_out_planarriv-")
    planorder_file = _find_file_by_prefix(output_dir, "by_if_snop_out_planorder-")
    planpurch_file = _find_file_by_prefix(output_dir, "by_if_snop_out_planpurch-")
    dfu_fcst_file = _find_file_by_prefix(input_dir, "if_snop_dfutoskufcst-")
    site = (scope.get("site") or "").strip()

    exception_rows = 0
    relation_rows = 0
    inddmd_item_with_extorder_hits = 0
    inddmd_item_with_extorder_header_hits = 0
    dfu_item_hits = 0
    demand_rows = []
    link_rows = []
    resource_link_rows = 0
    exception_item_rows = 0

    plan_arriv_qty = 0.0
    plan_order_qty = 0.0
    plan_purch_qty = 0.0
    plan_arriv_dates: List[datetime] = []
    plan_order_dates: List[datetime] = []
    plan_purch_dates: List[datetime] = []

    if exception_file:
        exception_rows = _file_summary(exception_file)["rows"]
    if relation_file:
        relation_rows = _file_summary(relation_file)["rows"]
    if inddmdview_file and demand_item:
        for row in _safe_rows(inddmdview_file):
            if (row.get("ITEM") or "").strip() != demand_item:
                continue
            if site and (row.get("LOC") or "").strip() != site:
                continue
            if not _matches_context(row, week_id, scenario_id):
                continue
            demand_rows.append(row)
            if (row.get("EXTORDERID") or "").strip():
                inddmd_item_with_extorder_hits += 1
            if (row.get("HEADEREXTREF") or "").strip():
                inddmd_item_with_extorder_header_hits += 1
    if inddmdlink_file and demand_item:
        for row in _safe_rows(inddmdlink_file):
            if (row.get("DMDITEM") or "").strip() != demand_item:
                continue
            if site and (row.get("DMDLOC") or "").strip() != site:
                continue
            if not _matches_context(row, week_id, scenario_id):
                continue
            link_rows.append(row)
    if resload_link_file and demand_item:
        for row in _safe_rows(resload_link_file):
            if (row.get("DMDITEM") or "").strip() != demand_item:
                continue
            if site and (row.get("DMDLOC") or "").strip() != site:
                continue
            if not _matches_context(row, week_id, scenario_id):
                continue
            resource_link_rows += 1
    if exception_file and demand_item:
        for row in _safe_rows(exception_file):
            if (row.get("ITEM") or "").strip() != demand_item:
                continue
            if site and (row.get("LOC") or "").strip() != site:
                continue
            if not _matches_context(row, week_id, scenario_id):
                continue
            exception_item_rows += 1

    if planarriv_file and demand_item:
        for row in _safe_rows(planarriv_file):
            if (row.get("ITEM") or "").strip() != demand_item:
                continue
            if site and (row.get("DEST") or "").strip() != site:
                continue
            if not _matches_context(row, week_id, scenario_id):
                continue
            plan_arriv_qty += _safe_float(row.get("QTY"))
            d = _parse_date(row.get("SCHEDARRIVDATE"))
            if d:
                plan_arriv_dates.append(d)

    if planorder_file and demand_item:
        for row in _safe_rows(planorder_file):
            if (row.get("ITEM") or "").strip() != demand_item:
                continue
            if site and (row.get("LOC") or "").strip() != site:
                continue
            if not _matches_context(row, week_id, scenario_id):
                continue
            plan_order_qty += _safe_float(row.get("QTY"))
            d = _parse_date(row.get("SCHEDDATE"))
            if d:
                plan_order_dates.append(d)

    if planpurch_file and demand_item:
        for row in _safe_rows(planpurch_file):
            if (row.get("ITEM") or "").strip() != demand_item:
                continue
            if site and (row.get("LOC") or "").strip() != site:
                continue
            if not _matches_context(row, week_id, scenario_id):
                continue
            plan_purch_qty += _safe_float(row.get("QTY"))
            d = _parse_date(row.get("SCHEDDATE"))
            if d:
                plan_purch_dates.append(d)

    if dfu_fcst_file and demand_item:
        for row in _safe_rows(dfu_fcst_file):
            if (row.get("ITEM") or "").strip() == demand_item:
                dfu_item_hits += 1

    demand_qty_total = sum(_safe_float(row.get("QTY")) for row in demand_rows)
    scheduled_qty_total = sum(_safe_float(row.get("SCHEDQTY")) for row in demand_rows)
    unmet_qty = max(demand_qty_total - scheduled_qty_total, 0.0)

    need_dates = [_parse_date(row.get("NEEDDATE")) for row in demand_rows]
    need_dates = [d for d in need_dates if d]
    sched_dates = [_parse_date(row.get("SCHEDDATE")) for row in demand_rows]
    sched_dates = [d for d in sched_dates if d]

    on_time_sched_qty = 0.0
    late_sched_qty = 0.0
    for row in demand_rows:
        sched_qty = _safe_float(row.get("SCHEDQTY"))
        if sched_qty <= 0:
            continue
        need_date = _parse_date(row.get("NEEDDATE"))
        sched_date = _parse_date(row.get("SCHEDDATE"))
        if need_date and sched_date and sched_date <= need_date:
            on_time_sched_qty += sched_qty
        else:
            late_sched_qty += sched_qty

    pegged_demand_qty = sum(_safe_float(row.get("DMDPEGQTY")) for row in link_rows)
    pegged_supply_qty = sum(_safe_float(row.get("SUPPLYPEGQTY")) for row in link_rows)
    supply_avail_dates = [_parse_date(row.get("SUPPLYAVAILDATE")) for row in link_rows]
    supply_avail_dates = [d for d in supply_avail_dates if d]

    supply_methods = sorted({(row.get("SUPPLYMETHOD") or "").strip() for row in link_rows if (row.get("SUPPLYMETHOD") or "").strip()})

    fully_met = demand_qty_total > 0 and scheduled_qty_total + 1e-6 >= demand_qty_total
    met_status = "Met" if fully_met else ("Partially Met" if scheduled_qty_total > 0 else "Not Met")
    met_date = max(sched_dates) if fully_met and sched_dates else None

    gaps = []
    if not week_id:
        gaps.append("no CAPTURE_WK found in available output datasets")
    if not scenario_id:
        gaps.append("no SIMULATION_NAME found in available output datasets")
    if not demand_item:
        gaps.append("demand item (ITEM) missing for direct lineage trace")
    if demand_item and demand_qty_total <= 0:
        gaps.append("no matching demand rows found for item in by_if_snop_out_inddmdview")

    confirmed_findings = [
        "Exception datasets are available for root-cause workflow." if exception_file else "Exception dataset not found.",
        "Exception-to-order relation dataset is available." if relation_file else "Exception-to-order relation dataset not found.",
        "Demand ITEM is evidenced in independent demand with external order reference."
        if (inddmd_item_with_extorder_hits > 0 or inddmd_item_with_extorder_header_hits > 0)
        else "Demand ITEM not found in independent demand with external order reference.",
        "Demand ITEM is evidenced in DFU-to-SKU forecast mapping."
        if dfu_item_hits > 0
        else "Demand ITEM not found in DFU-to-SKU forecast mapping.",
        f"Demand quantity for the item is {demand_qty_total:.3f} and scheduled quantity is {scheduled_qty_total:.3f}.",
        f"Demand meet status is {met_status}." + (f" Fully met by {_fmt_date(met_date)}." if met_date else ""),
    ]

    root_causes = []
    if demand_qty_total <= 0:
        root_causes.append("No demand rows were found for this item in the selected week/scenario scope.")
    if unmet_qty > 0:
        root_causes.append(f"Unmet demand quantity is {unmet_qty:.3f} (demand exceeds scheduled supply).")
    if late_sched_qty > 0:
        root_causes.append(f"Late fulfillment detected: {late_sched_qty:.3f} quantity is scheduled after need date.")
    if pegged_supply_qty + 1e-6 < pegged_demand_qty:
        root_causes.append("Pegged supply quantity is lower than pegged demand quantity in lineage links.")
    if exception_item_rows > 0:
        root_causes.append(f"Item has {exception_item_rows} SKU exception row(s), indicating planning constraints.")
    if not root_causes:
        root_causes.append("Demand appears covered by scheduled and pegged supply in the current dataset scope.")

    return {
        "Explainability Scope": {
            "week_id": week_id,
            "scenario_id": scenario_id,
            "week_column": "CAPTURE_WK",
            "scenario_column": "SIMULATION_NAME",
            "demand_item": demand_item or None,
            "scope": scope,
        },
        "Evidence Used": {
            "context_resolution": context,
            "input_source": "by_input",
            "output_source": "by_output",
            "exception_file": exception_file.name if exception_file else None,
            "exception_rows": exception_rows,
            "exception_relation_file": relation_file.name if relation_file else None,
            "exception_relation_rows": relation_rows,
            "inddmdlink_file": inddmdlink_file.name if inddmdlink_file else None,
            "resload_link_file": resload_link_file.name if resload_link_file else None,
            "planarriv_file": planarriv_file.name if planarriv_file else None,
            "planorder_file": planorder_file.name if planorder_file else None,
            "planpurch_file": planpurch_file.name if planpurch_file else None,
            "demand_mapping_rules": [
                "Demand input is ITEM.",
                "ITEM should exist in by_if_snop_out_inddmdview with EXTORDERID or HEADEREXTREF.",
                "ITEM can also be evidenced in if_snop_dfutoskufcst.",
            ],
            "inddmdview_file": inddmdview_file.name if inddmdview_file else None,
            "dfutoskufcst_file": dfu_fcst_file.name if dfu_fcst_file else None,
            "item_hits_in_inddmdview_with_EXTORDERID": inddmd_item_with_extorder_hits,
            "item_hits_in_inddmdview_with_HEADEREXTREF": inddmd_item_with_extorder_header_hits,
            "item_hits_in_dfutoskufcst": dfu_item_hits,
        },
        "Demand and Supply Summary": {
            "demand_rows": len(demand_rows),
            "demand_qty_total": round(demand_qty_total, 3),
            "scheduled_qty_total": round(scheduled_qty_total, 3),
            "unmet_qty": round(unmet_qty, 3),
            "on_time_scheduled_qty": round(on_time_sched_qty, 3),
            "late_scheduled_qty": round(late_sched_qty, 3),
            "first_need_date": _fmt_date(min(need_dates) if need_dates else None),
            "last_need_date": _fmt_date(max(need_dates) if need_dates else None),
            "first_sched_date": _fmt_date(min(sched_dates) if sched_dates else None),
            "last_sched_date": _fmt_date(max(sched_dates) if sched_dates else None),
            "meet_status": met_status,
            "fully_met_date": _fmt_date(met_date),
        },
        "Lineage Trace": {
            "inddmdlink_rows": len(link_rows),
            "resource_link_rows": resource_link_rows,
            "pegged_demand_qty": round(pegged_demand_qty, 3),
            "pegged_supply_qty": round(pegged_supply_qty, 3),
            "first_supply_avail_date": _fmt_date(min(supply_avail_dates) if supply_avail_dates else None),
            "last_supply_avail_date": _fmt_date(max(supply_avail_dates) if supply_avail_dates else None),
            "supply_methods_seen": supply_methods[:10],
        },
        "Planned Supply Evidence": {
            "plan_arrival_qty": round(plan_arriv_qty, 3),
            "plan_order_qty": round(plan_order_qty, 3),
            "plan_purchase_qty": round(plan_purch_qty, 3),
            "plan_arrival_first_date": _fmt_date(min(plan_arriv_dates) if plan_arriv_dates else None),
            "plan_order_first_date": _fmt_date(min(plan_order_dates) if plan_order_dates else None),
            "plan_purchase_first_date": _fmt_date(min(plan_purch_dates) if plan_purch_dates else None),
        },
        "Confirmed Findings": confirmed_findings,
        "Root Causes": root_causes,
        "Hypotheses and Missing Evidence": {
            "hypotheses": [
                "Unmet demand likely links to capacity, sourcing, or BOM constraints where exception density is high.",
            ],
            "missing_evidence": gaps,
        },
        "Confidence Level": "Medium" if demand_qty_total > 0 and len(link_rows) > 0 else "Low-Medium",
        "Recommended Next Checks": [
            "Provide demand ITEM and scope for targeted lineage trace.",
            "Compare demand need dates with supply available and scheduled dates for lateness diagnosis.",
            "Join exception, demand-link, and resource-link outputs with capacity and sourcing inputs for final constraint attribution.",
        ],
    }


def run_knowledge_graph(base_dir: Path, week_id: Optional[str], scenario_id: Optional[str], item_id: Optional[str], scope: Dict) -> Dict:
    context = _resolve_context(base_dir, week_id, scenario_id)
    week_id = context["week_id"]
    scenario_id = context["scenario_id"]
    demand_item = (item_id or "").strip()
    site = (scope.get("site") or "").strip()

    output_dir = base_dir / OUTPUT_FOLDER
    inddmdview_file = _find_file_by_prefix(output_dir, "by_if_snop_out_inddmdview-")
    inddmdlink_file = _find_file_by_prefix(output_dir, "by_if_snop_out_inddmdlink-")
    resload_link_file = _find_file_by_prefix(output_dir, "by_if_snop_out_resloadinddmdlink-")

    demand_rows = []
    link_rows = []
    resource_rows = []

    if inddmdview_file and demand_item:
        for row in _safe_rows(inddmdview_file):
            if (row.get("ITEM") or "").strip() != demand_item:
                continue
            if site and (row.get("LOC") or "").strip() != site:
                continue
            if not _matches_context(row, week_id, scenario_id):
                continue
            demand_rows.append(row)

    if inddmdlink_file and demand_item:
        for row in _safe_rows(inddmdlink_file):
            if (row.get("DMDITEM") or "").strip() != demand_item:
                continue
            if site and (row.get("DMDLOC") or "").strip() != site:
                continue
            if not _matches_context(row, week_id, scenario_id):
                continue
            link_rows.append(row)

    if resload_link_file and demand_item:
        for row in _safe_rows(resload_link_file):
            if (row.get("DMDITEM") or "").strip() != demand_item:
                continue
            if site and (row.get("DMDLOC") or "").strip() != site:
                continue
            if not _matches_context(row, week_id, scenario_id):
                continue
            resource_rows.append(row)

    nodes = []
    edges = []
    seen_nodes = set()
    seen_edges = set()

    def add_node(node_id: str, label: str, node_type: str, meta: Optional[Dict] = None):
        if not node_id or node_id in seen_nodes:
            return
        seen_nodes.add(node_id)
        nodes.append({
            "id": node_id,
            "label": label,
            "type": node_type,
            "meta": meta or {},
        })

    def add_edge(source: str, target: str, label: str, value: float = 0.0):
        edge_id = (source, target, label)
        if not source or not target or edge_id in seen_edges:
            return
        seen_edges.add(edge_id)
        edges.append({
            "source": source,
            "target": target,
            "label": label,
            "value": round(value, 3),
        })

    add_node(
        f"demand:{demand_item}",
        demand_item or "Demand Item",
        "demand_item",
        {
            "week_id": week_id,
            "scenario_id": scenario_id,
            "site": site or None,
            "demand_rows": len(demand_rows),
        },
    )

    demand_locs = sorted({(row.get("LOC") or "").strip() for row in demand_rows if (row.get("LOC") or "").strip()})[:5]
    for loc in demand_locs:
        loc_id = f"loc:{loc}"
        add_node(loc_id, loc, "location")
        add_edge(loc_id, f"demand:{demand_item}", "demand at")

    supply_item_totals: Dict[Tuple[str, str], float] = {}
    supply_method_totals: Dict[str, float] = {}
    supply_loc_totals: Dict[str, float] = {}
    resource_totals: Dict[str, float] = {}

    for row in link_rows:
        supply_item = (row.get("SUPPLYITEM") or "").strip()
        supply_loc = (row.get("SUPPLYLOC") or "").strip()
        supply_method = (row.get("SUPPLYMETHOD") or "").strip()
        pegged_qty = _safe_float(row.get("SUPPLYPEGQTY"))
        if supply_item:
            supply_item_totals[(supply_item, supply_loc)] = supply_item_totals.get((supply_item, supply_loc), 0.0) + pegged_qty
        if supply_method:
            supply_method_totals[supply_method] = supply_method_totals.get(supply_method, 0.0) + pegged_qty
        if supply_loc:
            supply_loc_totals[supply_loc] = supply_loc_totals.get(supply_loc, 0.0) + pegged_qty

    for row in resource_rows:
        res = (row.get("RES") or "").strip()
        qty = _safe_float(row.get("CAPACITYPEGQTY"))
        if res:
            resource_totals[res] = resource_totals.get(res, 0.0) + qty

    top_supply_items = sorted(supply_item_totals.items(), key=lambda item: item[1], reverse=True)[:6]
    top_supply_methods = sorted(supply_method_totals.items(), key=lambda item: item[1], reverse=True)[:6]
    top_supply_locs = sorted(supply_loc_totals.items(), key=lambda item: item[1], reverse=True)[:4]
    top_resources = sorted(resource_totals.items(), key=lambda item: item[1], reverse=True)[:5]

    for (supply_item, supply_loc), qty in top_supply_items:
        supply_item_id = f"supply-item:{supply_item}:{supply_loc or 'na'}"
        add_node(supply_item_id, supply_item, "supply_item", {"location": supply_loc or None, "pegged_qty": round(qty, 3)})
        add_edge(supply_item_id, f"demand:{demand_item}", "pegs to", qty)
        if supply_loc:
            loc_id = f"supply-loc:{supply_loc}"
            add_node(loc_id, supply_loc, "supply_location", {"pegged_qty": round(supply_loc_totals.get(supply_loc, 0.0), 3)})
            add_edge(loc_id, supply_item_id, "supplies from", supply_loc_totals.get(supply_loc, 0.0))

    for method, qty in top_supply_methods:
        method_id = f"method:{method}"
        add_node(method_id, method, "supply_method", {"pegged_qty": round(qty, 3)})
        for (supply_item, supply_loc), item_qty in top_supply_items:
            if method.startswith(f"{supply_item}_"):
                add_edge(method_id, f"supply-item:{supply_item}:{supply_loc or 'na'}", "executes", qty)

    for res, qty in top_resources:
        res_id = f"resource:{res}"
        add_node(res_id, res, "resource", {"capacity_pegged_qty": round(qty, 3)})
        for method, method_qty in top_supply_methods[:3]:
            add_edge(res_id, f"method:{method}", "loads", min(qty, method_qty))

    demand_qty_total = sum(_safe_float(row.get("QTY")) for row in demand_rows)
    scheduled_qty_total = sum(_safe_float(row.get("SCHEDQTY")) for row in demand_rows)
    unmet_qty = max(demand_qty_total - scheduled_qty_total, 0.0)

    return {
        "Graph Scope": {
            "week_id": week_id,
            "scenario_id": scenario_id,
            "week_column": "CAPTURE_WK",
            "scenario_column": "SIMULATION_NAME",
            "item_id": demand_item or None,
            "scope": scope,
        },
        "Graph Summary": {
            "demand_qty_total": round(demand_qty_total, 3),
            "scheduled_qty_total": round(scheduled_qty_total, 3),
            "unmet_qty": round(unmet_qty, 3),
            "demand_rows": len(demand_rows),
            "link_rows": len(link_rows),
            "resource_rows": len(resource_rows),
            "node_count": len(nodes),
            "edge_count": len(edges),
        },
        "Context Resolution": context,
        "Prompt for User": {
            "title": "Knowledge Graph",
            "description": "Start with ITEM. Add week, scenario, and site when available for a cleaner lineage graph.",
        },
        "nodes": nodes,
        "edges": edges,
    }


def run_chat_assistant(
    base_dir: Path,
    question: str,
    week_id: Optional[str],
    scenario_id: Optional[str],
    scope: Dict,
    llm_enabled: bool = True,
    llm_model: Optional[str] = None,
    history: Optional[List[Dict[str, str]]] = None,
) -> Dict:
    q = (question or "").strip()
    ql = q.lower()

    if not q:
        return {
            "Assistant Reply": "Please type your question so I can help.",
            "Suggested Next Step": "Try: 'Validate data for week 2026-W30 scenario S2'.",
        }

    summary_terms = ["summary", "dataset", "datasets", "files", "inventory", "what is available"]
    validation_terms = ["validate", "validation", "quality", "check data", "readiness", "bom", "master data"]
    compare_terms = ["compare", "difference", "delta", "scenario compare", "versus", "vs"]
    root_terms = ["root cause", "why unmet", "unmet", "why demand", "explain demand", "lineage", "genealogy", "met", "meet", "fulfilled"]
    item_inference = _infer_demand_item_from_question(q)
    demand_item = item_inference["selected_item"]
    history_window = (history or [])[-10:]

    if any(term in ql for term in validation_terms):
        result = run_validation(
            base_dir,
            week_id,
            scenario_id,
            scope,
            ["master_data", "bom", "parameters", "output_sanity"],
        )
        fallback = {
            "Assistant Reply": "I ran validation based on your question.",
            "Workflow": "Validation Gate",
            "Result": result,
        }
        return (_summarize_with_ollama(q, "Validation Gate", result, llm_model=llm_model) if llm_enabled else None) or fallback

    if any(term in ql for term in summary_terms):
        inv = dataset_inventory(base_dir)
        largest_input = max(inv["input_files"], key=lambda x: x["rows"], default=None)
        largest_output = max(inv["output_files"], key=lambda x: x["rows"], default=None)
        result = {
            "input_file_count": inv["input_file_count"],
            "output_file_count": inv["output_file_count"],
            "largest_input_file": largest_input["file"] if largest_input else None,
            "largest_output_file": largest_output["file"] if largest_output else None,
        }
        fallback = {
            "Assistant Reply": "I checked your available planning datasets.",
            "Findings": result,
            "Suggested Next Step": "Ask me to run validation, compare scenarios, or explain root cause.",
        }
        return (_summarize_with_ollama(q, "Dataset Summary", result, llm_model=llm_model) if llm_enabled else None) or fallback

    if any(term in ql for term in compare_terms):
        result = run_scenario_compare(
            base_dir,
            week_id,
            None,
            None,
            scope,
            ["unmet_demand", "capacity_utilization", "lateness"],
        )
        note = "For exact compare output, provide base and compare scenario IDs."
        fallback = {
            "Assistant Reply": "I ran scenario comparison in summary mode.",
            "Workflow": "Scenario Comparison",
            "Result": result,
            "Note": note,
        }
        return (_summarize_with_ollama(q, "Scenario Comparison", result, note, llm_model=llm_model) if llm_enabled else None) or fallback

    if any(term in ql for term in root_terms):
        context = _resolve_context(base_dir, week_id, scenario_id)
        resolved_week = context["week_id"]
        resolved_scenario = context["scenario_id"]

        if not demand_item:
            return {
                "Assistant Reply": "I can check demand status, but I need the demand ITEM first.",
                "Workflow": "Root Cause Clarification",
                "Clarification Needed": {
                    "question": "Which ITEM should I evaluate as demand?",
                    "expected_fields": ["ITEM", "Week ID = CAPTURE_WK (optional)", "Scenario ID = SIMULATION_NAME (optional)", "Site (optional)"],
                    "examples": [
                        "Check if the demand for ITEM 100000000008 was met",
                        "Was demand item 100000000008 met for CAPTURE_WK 202547 and SIMULATION_NAME CONSTRAINED?",
                    ],
                },
                "Parsing Evidence": item_inference,
                "Context Resolution": context,
            }

        demand_evidence = _item_demand_evidence(base_dir, resolved_week, resolved_scenario, demand_item, scope)
        if item_inference["confidence"] != "high" or not demand_evidence["is_demand_item"]:
            return {
                "Assistant Reply": f"I found ITEM {demand_item}, but I cannot confirm yet that it is the demand item for the resolved context.",
                "Workflow": "Root Cause Clarification",
                "Clarification Needed": {
                    "question": "Do you want me to treat this ITEM as a demand item, or do you want to provide a different demand ITEM/site/week/scenario?",
                    "examples": [
                        f"Yes, treat {demand_item} as the demand item",
                        f"Use ITEM {demand_item} for site 1004",
                        "Use demand ITEM 100000000004 for CAPTURE_WK 202547 and SIMULATION_NAME CONSTRAINED",
                    ],
                },
                "Parsing Evidence": item_inference,
                "Demand Evidence Check": demand_evidence,
                "Context Resolution": context,
            }

        result = run_root_cause(base_dir, week_id, scenario_id, demand_item, scope)
        note = "For best accuracy, include week and scenario IDs along with ITEM."
        fallback = {
            "Assistant Reply": "I ran root-cause analysis based on your question.",
            "Workflow": "Root Cause",
            "Result": result,
            "Note": note,
            "Parsing Evidence": item_inference,
        }
        return (_summarize_with_ollama(q, "Root Cause", result, note, llm_model=llm_model) if llm_enabled else None) or fallback

    fallback = {
        "Assistant Reply": "I can help with data summary, validation, scenario comparison, and root-cause checks.",
        "Your Question": q,
        "Suggested Prompts": [
            "Show dataset summary",
            "Validate data for week 2026-W30 scenario S2",
            "Compare scenarios S1 and S2 for week 2026-W30",
            "Why is demand unmet for scenario S2?",
        ],
    }

    if llm_enabled:
        conversational_system = (
            "You are IFSP Planning Copilot for Intel Foundry. "
            "Behave like a helpful chat assistant: understand follow-up questions, answer concisely, and ask clarifying questions when needed. "
            "Stay in IFSP/BY ESP planning scope. "
            "If a request needs specific identifiers (item, week, scenario, site), ask for them clearly."
        )
        conversational_reply = _ollama_chat_with_model(
            q,
            conversational_system,
            llm_model,
            history=history_window,
        )
        if conversational_reply:
            return {
                "Assistant Reply": conversational_reply,
                "Workflow": "Conversational Chat",
                "LLM Provider": "Ollama",
                "LLM Model": (llm_model or OLLAMA_MODEL).strip() or OLLAMA_MODEL,
            }

    return fallback
