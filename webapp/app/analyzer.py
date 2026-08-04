import csv
import json
import math
import os
import re
import smtplib
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from enum import Enum
from pathlib import Path
from typing import Dict, Generator, Iterable, List, Optional, Tuple
from urllib import error, request
import http.client
import threading
import urllib.parse

from .rag import ensure_rag_index, query_rag


INPUT_FOLDER = "by_input"
OUTPUT_FOLDER = "by_output"

# =====================================================================
# LLM PROVIDER CONFIGURATION (Production-Ready)
# =====================================================================
# Supported providers: 'nollama', 'openai', 'azure', 'anthropic', 'custom', 'openvino'
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "nollama").lower()

# Nollama Configuration (Local, OpenAI-compatible v1 API)
NOLLAMA_BASE_URL = os.getenv("NOLLAMA_BASE_URL", "http://localhost:8000")
NOLLAMA_MODEL = os.getenv("NOLLAMA_MODEL", "qwen2@GPU")
NOLLAMA_JUDGE_MODEL = os.getenv("NOLLAMA_JUDGE_MODEL", "qwen2@GPU")
NOLLAMA_VISION_MODEL = os.getenv("NOLLAMA_VISION_MODEL", "qwen2@GPU")

# OpenAI Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4")
OPENAI_JUDGE_MODEL = os.getenv("OPENAI_JUDGE_MODEL", "gpt-4")
OPENAI_VISION_MODEL = os.getenv("OPENAI_VISION_MODEL", "gpt-4-vision-preview")

# Anthropic Configuration
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_BASE_URL = os.getenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-20241022")
ANTHROPIC_JUDGE_MODEL = os.getenv("ANTHROPIC_JUDGE_MODEL", "claude-3-5-haiku-20241022")
ANTHROPIC_VISION_MODEL = os.getenv("ANTHROPIC_VISION_MODEL", "claude-3-5-sonnet-20241022")

# Azure OpenAI Configuration
# Endpoint format: https://{resource}.openai.azure.com/openai/deployments/{deployment}
AZURE_OPENAI_API_KEY     = os.getenv("AZURE_OPENAI_API_KEY", "")
AZURE_OPENAI_ENDPOINT    = os.getenv("AZURE_OPENAI_ENDPOINT", "")   # e.g. https://myresource.openai.azure.com
AZURE_OPENAI_DEPLOYMENT  = os.getenv("AZURE_OPENAI_DEPLOYMENT", "") # deployment name (= model alias)
AZURE_OPENAI_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01")
AZURE_OPENAI_JUDGE_DEPLOYMENT  = os.getenv("AZURE_OPENAI_JUDGE_DEPLOYMENT", AZURE_OPENAI_DEPLOYMENT or "")
AZURE_OPENAI_VISION_DEPLOYMENT = os.getenv("AZURE_OPENAI_VISION_DEPLOYMENT", AZURE_OPENAI_DEPLOYMENT or "")

# Generic OpenAI-compatible API Configuration (for other providers)
CUSTOM_LLM_API_KEY = os.getenv("CUSTOM_LLM_API_KEY", "")
CUSTOM_LLM_BASE_URL = os.getenv("CUSTOM_LLM_BASE_URL", "")
CUSTOM_LLM_MODEL = os.getenv("CUSTOM_LLM_MODEL", "")

# OpenVINO Configuration (Optimized local inference with latency hints)
_OV_DEFAULT_PATH = r"C:\Users\jojha\OneDrive - Intel Corporation\Documents\NoLlama\model"
OPENVINO_MODEL_PATH = os.getenv("OPENVINO_MODEL_PATH", _OV_DEFAULT_PATH)
OPENVINO_DEVICE = os.getenv("OPENVINO_DEVICE", "GPU")  # GPU, CPU, NPU, etc.
OPENVINO_PERFORMANCE_HINT = os.getenv("OPENVINO_PERFORMANCE_HINT", "LATENCY")  # LATENCY or THROUGHPUT
OPENVINO_NUM_STREAMS = int(os.getenv("OPENVINO_NUM_STREAMS", "1"))  # For THROUGHPUT mode
OPENVINO_MODEL = os.getenv("OPENVINO_MODEL", "DeepSeek-R1-Distill-Qwen-7B")
OPENVINO_JUDGE_MODEL = os.getenv("OPENVINO_JUDGE_MODEL", "DeepSeek-R1-Distill-Qwen-7B")
OPENVINO_VISION_MODEL = os.getenv("OPENVINO_VISION_MODEL", "DeepSeek-R1-Distill-Qwen-7B")

# Judge/Review LLM Enable Flag
JUDGE_LLM_ENABLED = os.getenv("JUDGE_LLM_ENABLED", "true")

# Global OpenVINO pipeline (cached)
_OPENVINO_PIPELINE = None

def _get_openvino_pipeline():
    """Lazy-load OpenVINO pipeline with performance hints."""
    global _OPENVINO_PIPELINE
    if _OPENVINO_PIPELINE is not None:
        return _OPENVINO_PIPELINE
    
    try:
        import openvino_genai as ov_genai
        
        # Configure performance hint
        config_dict = {"PERFORMANCE_HINT": OPENVINO_PERFORMANCE_HINT}
        if OPENVINO_PERFORMANCE_HINT == "THROUGHPUT":
            config_dict["NUM_STREAMS"] = OPENVINO_NUM_STREAMS
        
        print(f"[OpenVINO] Loading model from: {OPENVINO_MODEL_PATH}")
        print(f"[OpenVINO] Device: {OPENVINO_DEVICE}, Hint: {OPENVINO_PERFORMANCE_HINT}")
        
        _OPENVINO_PIPELINE = ov_genai.LLMPipeline(
            OPENVINO_MODEL_PATH,
            OPENVINO_DEVICE,
            config_dict
        )
        print(f"[OpenVINO] Pipeline loaded successfully")
        return _OPENVINO_PIPELINE
    except ImportError:
        raise ImportError("openvino_genai not installed. Install with: pip install openvino-genai")
    except Exception as e:
        raise RuntimeError(f"Failed to load OpenVINO model: {e}")

# Determine active provider and configuration
def _get_active_llm_config():
    """Get the active LLM provider configuration based on LLM_PROVIDER env var."""
    if LLM_PROVIDER == "openai":
        if not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY not set. Required for OpenAI provider.")
        return {
            "provider": "openai",
            "base_url": OPENAI_BASE_URL,
            "api_key": OPENAI_API_KEY,
            "auth_header": "Authorization",  # Bearer token
            "model": OPENAI_MODEL,
            "judge_model": OPENAI_JUDGE_MODEL,
            "vision_model": OPENAI_VISION_MODEL,
        }
    elif LLM_PROVIDER == "anthropic":
        if not ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY not set. Required for Anthropic provider.")
        return {
            "provider": "anthropic",
            "base_url": ANTHROPIC_BASE_URL,
            "api_key": ANTHROPIC_API_KEY,
            "auth_header": "x-api-key",  # Anthropic uses x-api-key, not Bearer
            "model": ANTHROPIC_MODEL,
            "judge_model": ANTHROPIC_JUDGE_MODEL,
            "vision_model": ANTHROPIC_VISION_MODEL,
        }
    elif LLM_PROVIDER == "azure":
        if not AZURE_OPENAI_API_KEY or not AZURE_OPENAI_ENDPOINT or not AZURE_OPENAI_DEPLOYMENT:
            raise ValueError("AZURE_OPENAI_API_KEY, AZURE_OPENAI_ENDPOINT, and AZURE_OPENAI_DEPLOYMENT are all required for Azure provider.")
        # Azure base_url encodes the deployment; chat completions appended without /v1/
        azure_base = f"{AZURE_OPENAI_ENDPOINT.rstrip('/')}/openai/deployments/{AZURE_OPENAI_DEPLOYMENT}"
        return {
            "provider": "azure",
            "base_url": azure_base,
            "api_key": AZURE_OPENAI_API_KEY,
            "auth_header": "api-key",  # Azure uses api-key, not Authorization Bearer
            "api_version": AZURE_OPENAI_API_VERSION,
            "model": AZURE_OPENAI_DEPLOYMENT,      # Azure uses deployment name as model
            "judge_model": AZURE_OPENAI_JUDGE_DEPLOYMENT or AZURE_OPENAI_DEPLOYMENT,
            "vision_model": AZURE_OPENAI_VISION_DEPLOYMENT or AZURE_OPENAI_DEPLOYMENT,
        }
    elif LLM_PROVIDER == "custom":
        if not CUSTOM_LLM_BASE_URL or not CUSTOM_LLM_MODEL:
            raise ValueError("CUSTOM_LLM_BASE_URL and CUSTOM_LLM_MODEL required for custom provider.")
        return {
            "provider": "custom",
            "base_url": CUSTOM_LLM_BASE_URL,
            "api_key": CUSTOM_LLM_API_KEY,
            "auth_header": "Authorization",  # assume Bearer by default for custom
            "model": CUSTOM_LLM_MODEL,
            "judge_model": CUSTOM_LLM_MODEL,
            "vision_model": CUSTOM_LLM_MODEL,
        }
    elif LLM_PROVIDER == "openvino":
        # Verify OpenVINO is available
        try:
            _get_openvino_pipeline()
        except Exception as e:
            raise ValueError(f"OpenVINO provider unavailable: {e}")
        return {
            "provider": "openvino",
            "base_url": None,
            "api_key": None,
            "model": OPENVINO_MODEL,
            "judge_model": OPENVINO_JUDGE_MODEL,
            "vision_model": OPENVINO_VISION_MODEL,
            "pipeline": _get_openvino_pipeline(),
        }
    else:  # Default to Nollama
        return {
            "provider": "nollama",
            "base_url": NOLLAMA_BASE_URL,
            "api_key": None,
            "auth_header": "Authorization",
            "model": NOLLAMA_MODEL,
            "judge_model": NOLLAMA_JUDGE_MODEL,
            "vision_model": NOLLAMA_VISION_MODEL,
        }

# Get active configuration
try:
    LLM_CONFIG = _get_active_llm_config()
except ValueError as e:
    print(f"[WARNING] LLM Configuration Error: {e}")
    print(f"[WARNING] Falling back to Nollama configuration")
    LLM_CONFIG = {
        "provider": "nollama",
        "base_url": NOLLAMA_BASE_URL,
        "api_key": None,
        "model": NOLLAMA_MODEL,
        "judge_model": NOLLAMA_JUDGE_MODEL,
        "vision_model": NOLLAMA_VISION_MODEL,
    }

# Legacy OLLAMA env vars (for backward compatibility)
OLLAMA_BASE_URL = LLM_CONFIG["base_url"]
OLLAMA_MODEL = LLM_CONFIG["model"]
OLLAMA_JUDGE_MODEL = LLM_CONFIG["judge_model"]
OLLAMA_JUDGE_ENABLED = JUDGE_LLM_ENABLED
OLLAMA_VISION_MODEL = LLM_CONFIG["vision_model"]

# Aliases for internal use
NOLLAMA_BASE_URL = LLM_CONFIG["base_url"] if LLM_CONFIG["provider"] == "nollama" else NOLLAMA_BASE_URL
NOLLAMA_MODEL = LLM_CONFIG["model"] if LLM_CONFIG["provider"] == "nollama" else NOLLAMA_MODEL
NOLLAMA_JUDGE_MODEL = LLM_CONFIG["judge_model"] if LLM_CONFIG["provider"] == "nollama" else NOLLAMA_JUDGE_MODEL
NOLLAMA_VISION_MODEL = LLM_CONFIG["vision_model"] if LLM_CONFIG["provider"] == "nollama" else NOLLAMA_VISION_MODEL

INPUT_DQ_VIEW_CONFIG = {
    "BY_ITEM": {"prefix": "if_snop_items-", "primary_key": ["ITEM"], "not_null_cols": ["ITEM", "DESCR", "ITEMCLASS"]},
    "BY_LOC": {"prefix": "if_snop_locations-", "primary_key": ["LOC"], "not_null_cols": ["LOC"]},
    "BY_RES": {"prefix": "if_snop_res-", "primary_key": ["RES", "LOC"], "not_null_cols": ["RES", "LOC"]},
    "BY_CAL": {"prefix": "if_snop_calendars-", "primary_key": ["CAL"], "not_null_cols": ["CAL"]},
    "BY_CALPATTERN": {"prefix": "if_snop_calpattern-", "primary_key": ["CAL", "PATTERNSEQNUM"], "not_null_cols": ["CAL", "PATTERNSEQNUM"]},
    "BY_CALATTRIBUTE": {"prefix": "if_snop_calattribute-", "primary_key": ["CAL", "PATTERNSEQNUM", "ATTRIBUTE"], "not_null_cols": ["CAL", "PATTERNSEQNUM"]},
    "BY_BOM": {"prefix": "if_snop_billofmaterials-", "primary_key": ["ITEM", "SUBORD", "LOC", "BOMNUM"], "not_null_cols": ["ITEM", "SUBORD", "LOC", "BOMNUM"]},
    "BY_ALTBOM": {"prefix": "if_snop_altbillofmaterials-", "primary_key": ["ITEM", "SUBORD", "LOC", "BOMNUM", "ALTSUBORD"], "not_null_cols": ["ITEM", "SUBORD", "LOC", "BOMNUM", "ALTSUBORD"]},
    "BY_NETWORK": {"prefix": "if_snop_network-", "primary_key": ["SOURCE", "DEST", "TRANSMODE"], "not_null_cols": ["SOURCE", "DEST", "TRANSMODE"]},
    "BY_PRODUCTIONMETHOD": {"prefix": "if_snop_productionmethod-", "primary_key": ["ITEM", "LOC", "PRODUCTIONMETHOD"], "not_null_cols": ["ITEM", "LOC", "PRODUCTIONMETHOD"]},
    "BY_PRODUCTIONSTEP": {"prefix": "if_snop_productionstep-", "primary_key": ["ITEM", "LOC", "PRODUCTIONMETHOD", "STEPNUM", "EFF"], "not_null_cols": ["ITEM", "LOC", "PRODUCTIONMETHOD", "STEPNUM", "EFF"]},
    "BY_ALTPRODUCTIONSTEP": {"prefix": "if_snop_altproductionstep-", "primary_key": ["ITEM", "LOC", "PRODUCTIONMETHOD", "PRIMARYSTEPNUM", "EFF"], "not_null_cols": ["ITEM", "LOC", "PRODUCTIONMETHOD", "PRIMARYSTEPNUM", "EFF"]},
    "BY_INVENTORY": {"prefix": "if_snop_inventory-", "primary_key": ["ITEM", "LOC"], "not_null_cols": ["ITEM", "LOC"]},
    "BY_SKUALL": {"prefix": "if_snop_sku-", "primary_key": ["ITEM", "LOC"], "not_null_cols": ["ITEM", "LOC"]},
    "BY_SKUEFFINVENTORYPARAM": {"prefix": "if_snop_skueffinventoryparam-", "primary_key": ["ITEM", "LOC", "EFF"], "not_null_cols": ["ITEM", "LOC", "EFF"]},
    "BY_CUSTOMERORDER": {"prefix": "if_snop_customerorder-", "primary_key": ["ORDERID", "ITEM", "LOC", "LINEITEMEXTREF"], "not_null_cols": ["ORDERID", "ITEM", "LOC", "QTY", "LINEITEMEXTREF"]},
    "BY_CUSTOMER_MASTER": {"prefix": "if_snop_customer-", "primary_key": ["CUST"], "not_null_cols": ["CUST"]},
    "BY_DFUTOSKUFCST": {"prefix": "if_snop_dfutoskufcst-", "primary_key": ["ITEM", "DMDGROUP", "TYPE", "DUR"], "not_null_cols": ["ITEM", "DMDGROUP", "TYPE", "DUR"]},
    "BY_PURCHMETHOD": {"prefix": "if_snop_purchmethod-", "primary_key": ["ITEM", "LOC", "PURCHMETHOD"], "not_null_cols": ["ITEM", "LOC", "PURCHMETHOD"]},
    "BY_SCHEDRCPTS": {"prefix": "if_snop_schedrcpts-", "primary_key": ["ITEM", "LOC", "SCHED_DATE", "SEQNUM"], "not_null_cols": ["ITEM", "LOC", "SCHED_DATE", "SEQNUM"]},
    "BY_SOURCING": {"prefix": "if_snop_sourcing-", "primary_key": ["ITEM", "SOURCE", "DEST", "SOURCING"], "not_null_cols": ["ITEM", "SOURCE", "DEST", "SOURCING"]},
    "BY_SUPERSESSION": {"prefix": "if_snop_supersession-", "primary_key": ["ITEM", "LOC", "ALTITEM", "DMDGROUP"], "not_null_cols": ["ITEM", "LOC", "ALTITEM", "DMDGROUP"]},
}

INPUT_DQ_RI_CHECKS = [
    ("BY_BOM", ["ITEM"], "BY_ITEM", ["ITEM"], "BOM parent item must exist in Item master"),
    ("BY_BOM", ["SUBORD"], "BY_ITEM", ["ITEM"], "BOM subordinate item must exist in Item master"),
    ("BY_BOM", ["LOC"], "BY_LOC", ["LOC"], "BOM location must exist in Location master"),
    ("BY_ALTBOM", ["ITEM"], "BY_ITEM", ["ITEM"], "AltBOM item must exist in Item master"),
    ("BY_ALTBOM", ["LOC"], "BY_LOC", ["LOC"], "AltBOM location must exist in Location master"),
    ("BY_ALTBOM", ["ITEM", "SUBORD", "LOC", "BOMNUM"], "BY_BOM", ["ITEM", "SUBORD", "LOC", "BOMNUM"], "AltBOM must reference valid BOM"),
    ("BY_INVENTORY", ["ITEM"], "BY_ITEM", ["ITEM"], "Inventory item must exist in Item master"),
    ("BY_INVENTORY", ["LOC"], "BY_LOC", ["LOC"], "Inventory location must exist in Location master"),
    ("BY_SKUALL", ["ITEM"], "BY_ITEM", ["ITEM"], "SKU item must exist in Item master"),
    ("BY_SKUALL", ["LOC"], "BY_LOC", ["LOC"], "SKU location must exist in Location master"),
    ("BY_SKUEFFINVENTORYPARAM", ["ITEM"], "BY_ITEM", ["ITEM"], "SKU Eff Inventory Param item must exist in Item master"),
    ("BY_SKUEFFINVENTORYPARAM", ["LOC"], "BY_LOC", ["LOC"], "SKU Eff Inventory Param location must exist in Location master"),
    ("BY_SKUEFFINVENTORYPARAM", ["ITEM", "LOC"], "BY_SKUALL", ["ITEM", "LOC"], "SKU Eff Inventory Param must reference valid SKU"),
    ("BY_PRODUCTIONMETHOD", ["ITEM"], "BY_ITEM", ["ITEM"], "Production Method item must exist in Item master"),
    ("BY_PRODUCTIONMETHOD", ["LOC"], "BY_LOC", ["LOC"], "Production Method location must exist in Location master"),
    ("BY_PRODUCTIONSTEP", ["ITEM"], "BY_ITEM", ["ITEM"], "Production Step item must exist in Item master"),
    ("BY_PRODUCTIONSTEP", ["LOC"], "BY_LOC", ["LOC"], "Production Step location must exist in Location master"),
    ("BY_PRODUCTIONSTEP", ["ITEM", "LOC", "PRODUCTIONMETHOD"], "BY_PRODUCTIONMETHOD", ["ITEM", "LOC", "PRODUCTIONMETHOD"], "Production Step must reference valid Production Method"),
    ("BY_PRODUCTIONSTEP", ["RES"], "BY_RES", ["RES"], "Production Step resource must exist in Resource master"),
    ("BY_ALTPRODUCTIONSTEP", ["ITEM"], "BY_ITEM", ["ITEM"], "Alt Production Step item must exist in Item master"),
    ("BY_ALTPRODUCTIONSTEP", ["LOC"], "BY_LOC", ["LOC"], "Alt Production Step location must exist in Location master"),
    ("BY_ALTPRODUCTIONSTEP", ["ITEM", "LOC", "PRODUCTIONMETHOD"], "BY_PRODUCTIONMETHOD", ["ITEM", "LOC", "PRODUCTIONMETHOD"], "Alt Production Step must reference valid Production Method"),
    ("BY_NETWORK", ["SOURCE"], "BY_LOC", ["LOC"], "Network source must exist in Location master"),
    ("BY_NETWORK", ["DEST"], "BY_LOC", ["LOC"], "Network destination must exist in Location master"),
    ("BY_SOURCING", ["ITEM"], "BY_ITEM", ["ITEM"], "Sourcing item must exist in Item master"),
    ("BY_SOURCING", ["SOURCE"], "BY_LOC", ["LOC"], "Sourcing source location must exist in Location master"),
    ("BY_SOURCING", ["DEST"], "BY_LOC", ["LOC"], "Sourcing destination location must exist in Location master"),
    ("BY_CUSTOMERORDER", ["ITEM"], "BY_ITEM", ["ITEM"], "Customer Order item must exist in Item master"),
    ("BY_CUSTOMERORDER", ["LOC"], "BY_LOC", ["LOC"], "Customer Order location must exist in Location master"),
    ("BY_CUSTOMERORDER", ["CUST"], "BY_CUSTOMER_MASTER", ["CUST"], "Customer Order customer must exist in Customer master"),
    ("BY_DFUTOSKUFCST", ["ITEM"], "BY_ITEM", ["ITEM"], "DFU to SKU Forecast item must exist in Item master"),
    ("BY_PURCHMETHOD", ["ITEM"], "BY_ITEM", ["ITEM"], "Purchase Method item must exist in Item master"),
    ("BY_PURCHMETHOD", ["LOC"], "BY_LOC", ["LOC"], "Purchase Method location must exist in Location master"),
    ("BY_SUPERSESSION", ["ITEM"], "BY_ITEM", ["ITEM"], "Supersession item must exist in Item master"),
    ("BY_SUPERSESSION", ["ALTITEM"], "BY_ITEM", ["ITEM"], "Supersession alternate item must exist in Item master"),
    ("BY_SUPERSESSION", ["LOC"], "BY_LOC", ["LOC"], "Supersession location must exist in Location master"),
    ("BY_SCHEDRCPTS", ["ITEM"], "BY_ITEM", ["ITEM"], "Sched Receipts item must exist in Item master"),
    ("BY_SCHEDRCPTS", ["LOC"], "BY_LOC", ["LOC"], "Sched Receipts location must exist in Location master"),
    ("BY_CALPATTERN", ["CAL"], "BY_CAL", ["CAL"], "Calendar Pattern must reference valid Calendar"),
    ("BY_CALATTRIBUTE", ["CAL"], "BY_CAL", ["CAL"], "Calendar Attribute must reference valid Calendar"),
    ("BY_RES", ["CAL"], "BY_CAL", ["CAL"], "Resource calendar must exist in Calendar master"),
    ("BY_CALATTRIBUTE", ["CAL", "PATTERNSEQNUM"], "BY_CALPATTERN", ["CAL", "PATTERNSEQNUM"], "Calendar Attribute must reference valid Calendar Pattern"),
]


class DemandEntityType(str, Enum):
    ITEM = "item"
    ORDER = "order"
    FORECAST = "forecast"
    TRANSFER = "transfer"
    DEPENDENT = "dependent"


class FulfillmentStatus(str, Enum):
    MET = "Met"
    PARTIALLY_MET = "Partially Met"
    NOT_MET = "Not Met"
    MET_LATE = "Met Late"


class EvidenceGrade(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


@dataclass
class DomainDemandEntity:
    entity_type: DemandEntityType
    entity_id: str
    resolved_item: Optional[str] = None
    resolution_note: str = ""

    def to_dict(self) -> Dict:
        return {
            "type": self.entity_type.value,
            "id": self.entity_id,
            "resolved_item": self.resolved_item,
            "resolution_note": self.resolution_note,
        }


class ConstraintAttributionPolicy:
    @staticmethod
    def evaluate(
        unmet_qty: float,
        late_sched_qty: float,
        pegged_demand_qty: float,
        pegged_supply_qty: float,
        setup_flags: Dict[str, bool],
        capacity_exception_count: int,
        resource_link_rows: int,
        competing_higher_priority_count: int,
        demand_qty_total: float,
        scheduled_qty_total: float,
    ) -> Dict[str, int]:
        return {
            "master_data_setup_risk": int(
                not setup_flags.get("item_exists_in_master", False)
                or not setup_flags.get("sku_coverage_exists", False)
                or (
                    not setup_flags.get("production_method_exists", False)
                    and not setup_flags.get("sourcing_path_exists", False)
                )
            ),
            "capacity_constraint_risk": int(capacity_exception_count > 0 or (resource_link_rows > 0 and late_sched_qty > 0)),
            "priority_allocation_risk": int(competing_higher_priority_count > 0),
            "supply_shortage_risk": int(unmet_qty > 0 and (scheduled_qty_total + 1e-6 < demand_qty_total)),
            "pegging_mismatch_risk": int(pegged_supply_qty + 1e-6 < pegged_demand_qty),
        }

BY_ESP_DOMAIN_KNOWLEDGE = {
    "solver": {
        "name": "Blue Yonder Enterprise Supply Planning (BY ESP) LP Optimization",
        "summary": "LP optimization balances demand service, supply cost, sourcing, and capacity limits under planning constraints.",
        "core_mechanics": [
            "Objective function optimizes weighted business outcomes such as service, margin, and penalties.",
            "Constraints enforce capacity, material flow, lead-time, lot-size, calendar, and sourcing rules.",
            "Pegs and links provide explainability from demand to supply, method, and resource consumption.",
        ],
    },
    "table_guidance": {
        "if_snop_items": "Item master and core product-level attributes.",
        "if_snop_locations": "Location/plant master used by planning network entities.",
        "if_snop_sku": "Item-location-customer planning grain used for policy and execution context.",
        "if_snop_billofmaterials": "Primary BOM parent-component relationships.",
        "if_snop_altbillofmaterials": "Alternate BOM options for substitution and flexibility.",
        "if_snop_sourcing": "Source-destination sourcing options and policies.",
        "if_snop_productionmethod": "Production pathways and method-level behavior.",
        "if_snop_res": "Resource master used for capacity assignment.",
        "by_if_snop_out_inddmdview": "Demand view including quantity, schedule quantity, and status context.",
        "by_if_snop_out_inddmdlink": "Demand-to-supply linkage records for explainability.",
        "by_if_snop_out_planorder": "Planned production order outputs.",
        "by_if_snop_out_planpurch": "Planned purchase supply outputs.",
        "by_if_snop_out_planarriv": "Planned arrival supply outputs.",
        "by_if_snop_out_resloaddetail": "Resource loading detail by plan and period.",
        "by_if_snop_out_resloadinddmdlink": "Resource-load linkage to demand entities.",
        "by_if_snop_out_skuprojstatic": "SKU projection summary with demand/supply and service indicators.",
        "by_if_snop_out_resprojstatic": "Resource projection summary including utilization fields.",
    },
    "linkages": [
        {
            "from": "if_snop_billofmaterials",
            "to": "if_snop_items",
            "keys": ["ITEM", "SUBORD"],
            "purpose": "Validates parent/component item references.",
        },
        {
            "from": "if_snop_sku",
            "to": "if_snop_items / if_snop_locations / if_snop_customer",
            "keys": ["ITEM", "LOC", "CUST"],
            "purpose": "Enforces SKU-level referential integrity.",
        },
        {
            "from": "by_if_snop_out_inddmdview",
            "to": "by_if_snop_out_inddmdlink",
            "keys": ["ITEM", "LOC", "CAPTURE_WK", "SIMULATION_NAME"],
            "purpose": "Connects demand records to linkage/pegging structure.",
        },
        {
            "from": "by_if_snop_out_inddmdlink",
            "to": "by_if_snop_out_planorder / by_if_snop_out_planarriv / by_if_snop_out_planpurch",
            "keys": ["ITEM", "LOC", "CAPTURE_WK", "SIMULATION_NAME"],
            "purpose": "Traces planned supply supporting demand.",
        },
        {
            "from": "by_if_snop_out_resloadinddmdlink",
            "to": "by_if_snop_out_resloaddetail",
            "keys": ["RES", "LOC", "CAPTURE_WK", "SIMULATION_NAME"],
            "purpose": "Links demand-driven loads to resource utilization.",
        },
    ],
}

BY_ESP_DOMAIN_FRAMEWORK = {
    "Fulfillment": {
        "bounded_context": "Context A: Demand Fulfillment (The Why did not we ship? Domain)",
        "user_story": "As a planner, I want to ask why Customer Order X was not met so that I can see the exact constraint (material, capacity, or calendar) that blocked it.",
        "key_inputs_outputs": ["Demand Postings", "Allocation Output", "Shortage Tables"],
        "focus": "Customer commitments and service level effectiveness.",
        "met_demand_metrics": ["OTIF", "Case Fill Rate", "Perfect Order Index"],
        "unmet_demand_metrics": ["Stockouts", "Lost Sales", "Backorders"],
        "delayed_order_metrics": ["Backlog Age", "DSO", "Delivery Lead Time Variability"],
        "intent_terms": [
            "fulfillment",
            "why didn't we ship",
            "why did not we ship",
            "why not shipped",
            "customer order not met",
            "otif",
            "fill rate",
            "stockout",
            "backorder",
            "shortage",
        ],
    },
    "Generation": {
        "bounded_context": "Context B: Supply Generation (The Why did not we build or buy? Domain)",
        "user_story": "As a planner, I want to know why no planned orders were generated for SKU Y in Week 24, despite an active forecast.",
        "key_inputs_outputs": ["SKU Master (Min-lot, Lead times)", "Production Capacity", "Sourcing Yields", "Planned Orders Output"],
        "focus": "Constraints, policies, and parameters that drive the supply plan.",
        "capacity_metrics": ["Machine Downtime", "Labor Shortages", "OEE"],
        "lead_time_metrics": ["Supplier Lead Time", "Transit Time", "Variability"],
        "calendar_gap_metrics": ["Holiday Shutdowns", "Planned Maintenance", "Shift Variances"],
        "intent_terms": [
            "generation",
            "why didn't we build",
            "why did not we build",
            "why didn't we buy",
            "why did not we buy",
            "no planned orders",
            "planned order not generated",
            "capacity",
            "lead time",
            "active forecast",
        ],
    },
    "Data Hygiene": {
        "bounded_context": "Context C: Data Hygiene (Garbage In, Garbage Out Domain)",
        "user_story": "As a planner, I want to check if a sudden drop in planned supply is due to a data input error rather than a physical supply chain constraint.",
        "key_inputs_outputs": ["Calendars", "Sourcing or Routing Masters", "Inventory On-Hand inputs"],
        "focus": "Structural integrity and quality of planning data feeding the planning engine.",
        "bad_master_metrics": ["Outdated BOM", "Incorrect Routings", "Duplicate Item Codes"],
        "parameter_gap_metrics": ["Unmaintained Safety Stock", "Missing MOQ", "Incorrect Lot Sizes"],
        "intent_terms": [
            "data hygiene",
            "garbage in garbage out",
            "data input error",
            "master data error",
            "master data",
            "data quality",
            "sudden drop in planned supply",
            "routing master",
            "calendar issue",
            "inventory input",
            "moq",
            "lot size",
        ],
    },
}


def _detect_domain_focus_candidates(question: str) -> List[str]:
    q = (question or "").lower()
    matched: List[str] = []
    for domain_name, domain_meta in BY_ESP_DOMAIN_FRAMEWORK.items():
        terms = [str(t).lower() for t in domain_meta.get("intent_terms", [])]
        if any(term in q for term in terms):
            matched.append(domain_name)
    return matched


def _detect_domain_focus(question: str) -> Optional[str]:
    candidates = _detect_domain_focus_candidates(question)
    return candidates[0] if candidates else None


def _run_domain_focus_workflow(
    base_dir: Path,
    domain_focus: str,
    week_id: Optional[str],
    scenario_id: Optional[str],
    scope: Dict,
) -> Dict:
    insights = run_insights(base_dir, week_id, scenario_id, None, None, scope)
    trend = insights.get("Trend Analysis", {}) if isinstance(insights, dict) else {}

    if domain_focus == "Fulfillment":
        fill_rate_rows = ((trend.get("Fill Rate") or {}).get("workweek") or [])[:12]
        demand_supply_rows = ((trend.get("Demand vs Supply") or {}).get("workweek") or [])[:12]
        met_split = trend.get("Demand Met vs UnMet vs Partially Met") or {}
        return {
            "workflow": "Domain Focus - Fulfillment",
            "result": {
                "domain": BY_ESP_DOMAIN_FRAMEWORK["Fulfillment"],
                "bounded_context": BY_ESP_DOMAIN_FRAMEWORK["Fulfillment"].get("bounded_context"),
                "user_story": BY_ESP_DOMAIN_FRAMEWORK["Fulfillment"].get("user_story"),
                "kpi_summary": insights.get("KPI Summary", {}),
                "fill_rate_trend_workweek": fill_rate_rows,
                "demand_supply_trend_workweek": demand_supply_rows,
                "met_unmet_split": met_split,
                "context": (insights.get("Insights Scope") or {}).get("context_resolution"),
            },
            "note": "Fulfillment domain analysis grounded on demand/supply and service behavior trends.",
        }

    if domain_focus == "Generation":
        capacity_rows = ((trend.get("Capacity Utilization") or {}).get("workweek") or [])[:12]
        return {
            "workflow": "Domain Focus - Generation",
            "result": {
                "domain": BY_ESP_DOMAIN_FRAMEWORK["Generation"],
                "bounded_context": BY_ESP_DOMAIN_FRAMEWORK["Generation"].get("bounded_context"),
                "user_story": BY_ESP_DOMAIN_FRAMEWORK["Generation"].get("user_story"),
                "capacity_trend_workweek": capacity_rows,
                "kpi_summary": insights.get("KPI Summary", {}),
                "context": (insights.get("Insights Scope") or {}).get("context_resolution"),
                "notes": [
                    "Generation domain focuses on capacity, lead-time, and calendar-policy effects.",
                    "Some metrics (downtime, OEE, labor shortage) may require additional operational datasets.",
                ],
            },
            "note": "Generation domain analysis grounded on capacity and timing signals from planning outputs.",
        }

    validation = run_validation(base_dir, week_id, scenario_id, scope, ["master_data", "bom", "parameters", "output_sanity"])
    return {
        "workflow": "Domain Focus - Data Hygiene",
        "result": {
            "domain": BY_ESP_DOMAIN_FRAMEWORK["Data Hygiene"],
            "bounded_context": BY_ESP_DOMAIN_FRAMEWORK["Data Hygiene"].get("bounded_context"),
            "user_story": BY_ESP_DOMAIN_FRAMEWORK["Data Hygiene"].get("user_story"),
            "validation_summary": {
                "verdict": validation.get("Readiness Verdict (Pass, Conditional Pass, Fail)"),
                "checks_executed": validation.get("Checks Executed", {}),
                "issues": validation.get("Issues Found (Critical, High, Medium, Low)", {}),
            },
            "context": (validation.get("Datasets and Evidence Used") or {}).get("context_resolution"),
        },
        "note": "Data Hygiene domain analysis grounded on referential integrity and parameter quality checks.",
    }


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


def _find_latest_file_by_prefix(folder: Path, prefix: str) -> Optional[Path]:
    candidates = sorted(folder.glob(f"{prefix}*.csv"))
    return candidates[-1] if candidates else None


def _is_blank(value: Optional[str]) -> bool:
    return value is None or str(value).strip() == ""


def _row_matches_week_scenario(row: Dict, week_id: Optional[str], scenario_id: Optional[str]) -> bool:
    if week_id:
        if "CAPTURE_WK" in row and (row.get("CAPTURE_WK") or "").strip() and (row.get("CAPTURE_WK") or "").strip() != week_id:
            return False
    if scenario_id:
        if "SIMULATION_NAME" in row and (row.get("SIMULATION_NAME") or "").strip():
            if not _scenario_match((row.get("SIMULATION_NAME") or "").strip(), scenario_id):
                return False
    return True


def _table_rows_by_view(base_dir: Path, week_id: Optional[str], scenario_id: Optional[str]) -> Tuple[Dict[str, Optional[Path]], Dict[str, List[Dict]]]:
    input_dir = base_dir / INPUT_FOLDER
    files_by_view: Dict[str, Optional[Path]] = {}
    rows_by_view: Dict[str, List[Dict]] = {}
    for view_name, cfg in INPUT_DQ_VIEW_CONFIG.items():
        file_path = _find_latest_file_by_prefix(input_dir, cfg["prefix"])
        files_by_view[view_name] = file_path
        if not file_path:
            rows_by_view[view_name] = []
            continue
        rows = [row for row in _safe_rows(file_path) if _row_matches_week_scenario(row, week_id, scenario_id)]
        rows_by_view[view_name] = rows
    return files_by_view, rows_by_view


def _dq_status_counts(rows: List[Dict]) -> Dict[str, int]:
    counts = {"PASS": 0, "FAIL": 0, "ERROR": 0, "SKIP": 0}
    for row in rows:
        status = str(row.get("Status", "")).upper()
        if status in counts:
            counts[status] += 1
    return counts


def run_input_data_quality(base_dir: Path, week_id: Optional[str], scenario_id: Optional[str]) -> Dict:
    generated_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    files_by_view, rows_by_view = _table_rows_by_view(base_dir, week_id, scenario_id)

    duplicate_rows: List[Dict] = []
    not_null_rows: List[Dict] = []
    ri_rows: List[Dict] = []

    for view_name, cfg in INPUT_DQ_VIEW_CONFIG.items():
        file_path = files_by_view.get(view_name)
        table_rows = rows_by_view.get(view_name, [])
        key_cols = cfg["primary_key"]

        if not file_path:
            duplicate_rows.append(
                {
                    "View": view_name,
                    "Key Columns": ", ".join(key_cols),
                    "Total Rows": 0,
                    "Duplicate Count": 0,
                    "Status": "SKIP",
                    "Details": "Input file not found for this view.",
                }
            )
        elif not table_rows:
            duplicate_rows.append(
                {
                    "View": view_name,
                    "Key Columns": ", ".join(key_cols),
                    "Total Rows": 0,
                    "Duplicate Count": 0,
                    "Status": "PASS",
                    "Details": "No rows found for selected filters.",
                }
            )
        else:
            missing_key_cols = [c for c in key_cols if c not in table_rows[0]]
            if missing_key_cols:
                duplicate_rows.append(
                    {
                        "View": view_name,
                        "Key Columns": ", ".join(key_cols),
                        "Total Rows": len(table_rows),
                        "Duplicate Count": "ERROR",
                        "Status": "ERROR",
                        "Details": f"Missing key columns: {', '.join(missing_key_cols)}",
                    }
                )
            else:
                seen = {}
                dup_count = 0
                for row in table_rows:
                    key = tuple((row.get(col) or "").strip() for col in key_cols)
                    seen[key] = seen.get(key, 0) + 1
                for cnt in seen.values():
                    if cnt > 1:
                        dup_count += cnt - 1
                duplicate_rows.append(
                    {
                        "View": view_name,
                        "Key Columns": ", ".join(key_cols),
                        "Total Rows": len(table_rows),
                        "Duplicate Count": dup_count,
                        "Status": "PASS" if dup_count == 0 else "FAIL",
                        "Details": "",
                    }
                )

        for col_name in cfg["not_null_cols"]:
            if not file_path:
                not_null_rows.append(
                    {
                        "View": view_name,
                        "Column": col_name,
                        "Total Rows": 0,
                        "Null Count": 0,
                        "Null %": 0.0,
                        "Status": "SKIP",
                        "Details": "Input file not found for this view.",
                    }
                )
                continue
            if not table_rows:
                not_null_rows.append(
                    {
                        "View": view_name,
                        "Column": col_name,
                        "Total Rows": 0,
                        "Null Count": 0,
                        "Null %": 0.0,
                        "Status": "PASS",
                        "Details": "No rows found for selected filters.",
                    }
                )
                continue
            if col_name not in table_rows[0]:
                not_null_rows.append(
                    {
                        "View": view_name,
                        "Column": col_name,
                        "Total Rows": len(table_rows),
                        "Null Count": "ERROR",
                        "Null %": "ERROR",
                        "Status": "ERROR",
                        "Details": f"Column {col_name} not found.",
                    }
                )
                continue

            null_count = 0
            for row in table_rows:
                if _is_blank(row.get(col_name)):
                    null_count += 1
            null_pct = round((null_count / len(table_rows) * 100), 2) if table_rows else 0.0
            not_null_rows.append(
                {
                    "View": view_name,
                    "Column": col_name,
                    "Total Rows": len(table_rows),
                    "Null Count": null_count,
                    "Null %": null_pct,
                    "Status": "PASS" if null_count == 0 else "FAIL",
                    "Details": "",
                }
            )

    for child_view, child_cols, parent_view, parent_cols, description in INPUT_DQ_RI_CHECKS:
        child_file = files_by_view.get(child_view)
        parent_file = files_by_view.get(parent_view)
        child_rows = rows_by_view.get(child_view, [])
        parent_rows = rows_by_view.get(parent_view, [])

        if not child_file or not parent_file:
            ri_rows.append(
                {
                    "Child View": child_view,
                    "Child Column(s)": ", ".join(child_cols),
                    "Parent View": parent_view,
                    "Parent Column(s)": ", ".join(parent_cols),
                    "Description": description,
                    "Orphan Records": 0,
                    "Status": "SKIP",
                    "Details": "Missing child or parent input file.",
                }
            )
            continue

        if child_rows and any(col not in child_rows[0] for col in child_cols):
            missing = [col for col in child_cols if col not in child_rows[0]]
            ri_rows.append(
                {
                    "Child View": child_view,
                    "Child Column(s)": ", ".join(child_cols),
                    "Parent View": parent_view,
                    "Parent Column(s)": ", ".join(parent_cols),
                    "Description": description,
                    "Orphan Records": "ERROR",
                    "Status": "ERROR",
                    "Details": f"Missing child columns: {', '.join(missing)}",
                }
            )
            continue

        if parent_rows and any(col not in parent_rows[0] for col in parent_cols):
            missing = [col for col in parent_cols if col not in parent_rows[0]]
            ri_rows.append(
                {
                    "Child View": child_view,
                    "Child Column(s)": ", ".join(child_cols),
                    "Parent View": parent_view,
                    "Parent Column(s)": ", ".join(parent_cols),
                    "Description": description,
                    "Orphan Records": "ERROR",
                    "Status": "ERROR",
                    "Details": f"Missing parent columns: {', '.join(missing)}",
                }
            )
            continue

        parent_keys = set()
        for row in parent_rows:
            parent_key = tuple((row.get(col) or "").strip() for col in parent_cols)
            parent_keys.add(parent_key)

        orphan_count = 0
        for row in child_rows:
            child_key = tuple((row.get(col) or "").strip() for col in child_cols)
            if all(_is_blank(val) for val in child_key):
                continue
            if child_key not in parent_keys:
                orphan_count += 1

        ri_rows.append(
            {
                "Child View": child_view,
                "Child Column(s)": ", ".join(child_cols),
                "Parent View": parent_view,
                "Parent Column(s)": ", ".join(parent_cols),
                "Description": description,
                "Orphan Records": orphan_count,
                "Status": "PASS" if orphan_count == 0 else "FAIL",
                "Details": "",
            }
        )

    dup_counts = _dq_status_counts(duplicate_rows)
    not_null_counts = _dq_status_counts(not_null_rows)
    ri_counts = _dq_status_counts(ri_rows)

    total_pass = dup_counts["PASS"] + not_null_counts["PASS"] + ri_counts["PASS"]
    total_fail = dup_counts["FAIL"] + not_null_counts["FAIL"] + ri_counts["FAIL"]
    total_error = dup_counts["ERROR"] + not_null_counts["ERROR"] + ri_counts["ERROR"]
    total_skip = dup_counts["SKIP"] + not_null_counts["SKIP"] + ri_counts["SKIP"]
    score_base = total_pass + total_fail
    score = round((total_pass / score_base * 100), 1) if score_base > 0 else 100.0

    snapshot_files = []
    for view_name, cfg in INPUT_DQ_VIEW_CONFIG.items():
        path = files_by_view.get(view_name)
        if path:
            snapshot_files.append({"view": view_name, "file": path.name})

    return {
        "Report Type": "BY Input Data Quality",
        "Generated At": generated_at,
        "Validation Scope": {
            "week_id": week_id,
            "scenario_id": scenario_id,
            "source": "by_input",
            "notes": [
                "This report currently evaluates BY input CSV datasets.",
                "Snowflake-backed validation can be enabled later using the same output format.",
            ],
        },
        "Summary": {
            "overall_score_pct": score,
            "total_pass": total_pass,
            "total_fail": total_fail,
            "total_error": total_error,
            "total_skip": total_skip,
            "duplicate_checks": dup_counts,
            "not_null_checks": not_null_counts,
            "referential_integrity_checks": ri_counts,
        },
        "Snapshot Files": snapshot_files,
        "Duplicate Check": duplicate_rows,
        "Not Null Check": not_null_rows,
        "Referential Integrity Check": ri_rows,
    }


def generate_input_dq_html_report(report: Dict) -> str:
    summary = report.get("Summary", {}) if isinstance(report, dict) else {}
    ri_summary = summary.get("referential_integrity_checks", {}) if isinstance(summary, dict) else {}
    title = "BY Input Data Quality Report"

    def _table(rows: List[Dict]) -> str:
        if not rows:
            return "<p>No rows.</p>"
        cols = list(rows[0].keys())
        header = "".join([f"<th>{c}</th>" for c in cols])
        body_rows = []
        for row in rows:
            status = str(row.get("Status", "")).upper()
            row_style = " style=\"background:#ffeef0;\"" if status in {"FAIL", "ERROR"} else ""
            cells = "".join([f"<td>{row.get(c, '')}</td>" for c in cols])
            body_rows.append(f"<tr{row_style}>{cells}</tr>")
        body = "\n".join(body_rows)
        return f"<table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>"

    return f"""
<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <title>{title}</title>
  <style>
    body {{ font-family: Segoe UI, Arial, sans-serif; margin: 20px; background: #f4f7fb; color: #10243a; }}
    .wrap {{ max-width: 1400px; margin: auto; background: #fff; padding: 24px; border-radius: 12px; border: 1px solid #d9e5f2; }}
    h1 {{ margin-top: 0; }}
    h2 {{ margin-top: 28px; }}
    .kpi {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); gap: 10px; }}
    .card {{ background: #f8fbff; border: 1px solid #dbe8f5; border-radius: 10px; padding: 10px 12px; }}
    .card strong {{ display: block; color: #2a4f77; font-size: 12px; text-transform: uppercase; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; margin-top: 10px; }}
    th {{ text-align: left; background: #0d5f9e; color: #fff; padding: 8px; }}
    td {{ border-bottom: 1px solid #e6edf5; padding: 7px 8px; }}
  </style>
</head>
<body>
  <div class=\"wrap\">
    <h1>{title}</h1>
    <p>Generated at: {report.get('Generated At', '')}</p>
    <div class=\"kpi\">
      <div class=\"card\"><strong>Overall Score %</strong>{summary.get('overall_score_pct', '')}</div>
      <div class=\"card\"><strong>Total Pass</strong>{summary.get('total_pass', '')}</div>
      <div class=\"card\"><strong>Total Fail</strong>{summary.get('total_fail', '')}</div>
      <div class=\"card\"><strong>Total Error</strong>{summary.get('total_error', '')}</div>
      <div class=\"card\"><strong>Total Skip</strong>{summary.get('total_skip', '')}</div>
    </div>
        <h2>Referential Integrity Snapshot</h2>
        <div class=\"kpi\">
            <div class=\"card\"><strong>Total RI Checks</strong>{(ri_summary.get('PASS', 0) or 0) + (ri_summary.get('FAIL', 0) or 0) + (ri_summary.get('ERROR', 0) or 0) + (ri_summary.get('SKIP', 0) or 0)}</div>
            <div class=\"card\"><strong>RI Pass</strong>{ri_summary.get('PASS', 0)}</div>
            <div class=\"card\"><strong>RI Fail</strong>{ri_summary.get('FAIL', 0)}</div>
            <div class=\"card\"><strong>RI Error</strong>{ri_summary.get('ERROR', 0)}</div>
            <div class=\"card\"><strong>RI Skip</strong>{ri_summary.get('SKIP', 0)}</div>
        </div>
    <h2>Duplicate Check</h2>
    {_table(report.get('Duplicate Check', []))}
    <h2>Not Null Check</h2>
    {_table(report.get('Not Null Check', []))}
    <h2>Referential Integrity Check</h2>
    {_table(report.get('Referential Integrity Check', []))}
  </div>
</body>
</html>
"""


def generate_validation_html_report(report: Dict, title: str = "Validation Report") -> str:
    generated_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    def _escape(value: object) -> str:
        text = "" if value is None else str(value)
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
        )

    def _render_value(value: object) -> str:
        if isinstance(value, list):
            if not value:
                return "<p>None</p>"
            if all(isinstance(item, dict) for item in value):
                return _render_table(value)
            items = "".join([f"<li>{_escape(item)}</li>" for item in value])
            return f"<ul>{items}</ul>"
        if isinstance(value, dict):
            rows = "".join(
                [
                    f"<tr><th>{_escape(k)}</th><td>{_render_value(v)}</td></tr>"
                    for k, v in value.items()
                ]
            )
            return f"<table><tbody>{rows}</tbody></table>"
        return _escape(value)

    def _render_table(rows: List[Dict]) -> str:
        if not rows:
            return "<p>None</p>"
        columns = list(rows[0].keys())
        header = "".join([f"<th>{_escape(col)}</th>" for col in columns])
        body_rows = []
        for row in rows:
            status = str(row.get("Status", "")).upper()
            row_style = " style=\"background:#ffeef0;\"" if status in {"FAIL", "ERROR"} else ""
            cells = "".join([f"<td>{_escape(row.get(col, ''))}</td>" for col in columns])
            body_rows.append(f"<tr{row_style}>{cells}</tr>")
        body = "\n".join(body_rows)
        return f"<table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>"

    sections = []
    if isinstance(report, dict):
        for key, value in report.items():
            sections.append(f"<section><h2>{_escape(key)}</h2>{_render_value(value)}</section>")

    return f"""
<!doctype html>
<html>
<head>
  <meta charset=\"utf-8\" />
  <title>{_escape(title)}</title>
  <style>
    body {{ font-family: Segoe UI, Arial, sans-serif; margin: 20px; background: #f4f7fb; color: #10243a; }}
    .wrap {{ max-width: 1500px; margin: auto; background: #fff; padding: 24px; border-radius: 12px; border: 1px solid #d9e5f2; }}
    h1 {{ margin-top: 0; }}
    h2 {{ margin-top: 26px; color: #114876; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 8px; font-size: 13px; }}
    th {{ text-align: left; background: #0d5f9e; color: #fff; padding: 8px; vertical-align: top; }}
    td {{ border-bottom: 1px solid #e6edf5; padding: 7px 8px; vertical-align: top; }}
    ul {{ margin: 6px 0 0 18px; padding: 0; }}
    p {{ margin: 6px 0; }}
  </style>
</head>
<body>
  <div class=\"wrap\">
    <h1>{_escape(title)}</h1>
    <p>Generated at: {_escape(generated_at)}</p>
    {''.join(sections)}
  </div>
</body>
</html>
"""


def send_html_email_report(recipient_email: str, subject: str, html_content: str, text_content: str) -> Tuple[bool, str]:
    configured_hosts = (os.getenv("SMTP_HOST") or "smtp.intel.com,mail.intel.com").strip()
    smtp_hosts = [host.strip() for host in configured_hosts.split(",") if host.strip()]
    smtp_port = int((os.getenv("SMTP_PORT") or "25").strip())
    smtp_user = (os.getenv("SMTP_USER") or "").strip()
    smtp_password = (os.getenv("SMTP_PASSWORD") or "").strip()
    smtp_from = (os.getenv("SMTP_FROM") or recipient_email or smtp_user).strip()
    smtp_use_tls = (os.getenv("SMTP_USE_TLS") or "false").strip().lower() in {"1", "true", "yes"}

    if not smtp_hosts or not smtp_from:
        return False, "SMTP configuration is missing. Set SMTP_HOST and SMTP_FROM (and credentials if required)."

    msg = EmailMessage()
    msg["From"] = smtp_from
    msg["To"] = recipient_email
    msg["Subject"] = subject
    msg.set_content(text_content)
    msg.add_alternative(html_content, subtype="html")

    last_error = None
    for smtp_host in smtp_hosts:
        try:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as smtp:
                if smtp_use_tls:
                    smtp.starttls()
                if smtp_user and smtp_password:
                    smtp.login(smtp_user, smtp_password)
                smtp.send_message(msg)
            return True, f"Email sent successfully via {smtp_host}:{smtp_port}."
        except Exception as exc:
            last_error = f"{smtp_host}:{smtp_port} -> {str(exc)}"

    return False, f"Email send failed. {last_error or 'No SMTP host succeeded.'}"


def smtp_health_check() -> Dict:
    configured_hosts = (os.getenv("SMTP_HOST") or "smtp.intel.com,mail.intel.com").strip()
    smtp_hosts = [host.strip() for host in configured_hosts.split(",") if host.strip()]
    smtp_port = int((os.getenv("SMTP_PORT") or "25").strip())
    smtp_user = (os.getenv("SMTP_USER") or "").strip()
    smtp_password = (os.getenv("SMTP_PASSWORD") or "").strip()
    smtp_from = (os.getenv("SMTP_FROM") or "").strip()
    smtp_use_tls = (os.getenv("SMTP_USE_TLS") or "false").strip().lower() in {"1", "true", "yes"}

    results: List[Dict[str, object]] = []
    any_ok = False

    for smtp_host in smtp_hosts:
        try:
            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as smtp:
                smtp.ehlo()
                if smtp_use_tls:
                    smtp.starttls()
                    smtp.ehlo()
                if smtp_user and smtp_password:
                    smtp.login(smtp_user, smtp_password)
                code, _ = smtp.noop()
            ok = int(code) in {250}
            any_ok = any_ok or ok
            results.append(
                {
                    "host": smtp_host,
                    "port": smtp_port,
                    "ok": ok,
                    "stage": "noop",
                    "detail": f"SMTP handshake succeeded (NOOP {code}).",
                }
            )
        except Exception as exc:
            results.append(
                {
                    "host": smtp_host,
                    "port": smtp_port,
                    "ok": False,
                    "stage": "connect_or_handshake",
                    "detail": str(exc),
                }
            )

    return {
        "healthy": any_ok,
        "message": "SMTP relay reachable." if any_ok else "SMTP relay not reachable.",
        "config": {
            "smtp_hosts": smtp_hosts,
            "smtp_port": smtp_port,
            "smtp_use_tls": smtp_use_tls,
            "smtp_from_configured": bool(smtp_from),
            "smtp_auth_configured": bool(smtp_user and smtp_password),
        },
        "results": results,
    }


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


def _safe_int(value: Optional[str]) -> Optional[int]:
    text = (value or "").strip()
    if not text:
        return None
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return None


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


_ITEM_EXTRACT_KEYWORD_BLOCKLIST = frozenset({
    "item", "for", "the", "a", "an", "this", "that", "all", "any",
    "some", "met", "not", "was", "check", "demand", "supply",
    "if", "is", "it", "in", "or", "of", "at", "by", "on",
    "product", "products",  # prevent 'for product' capturing the word itself
})


def _extract_item_candidates(question: str) -> List[str]:
    q = question or ""
    candidates: List[str] = []
    patterns = [
        # Most specific first: "demand for item XXXX" / "demand item XXXX"
        r"\bdemand\s+for\s+item\s*[:=]?\s*([A-Za-z0-9\-]+)",
        r"\bdemand\s+item\s*[:=]?\s*([A-Za-z0-9\-]+)",
        # "item XXXX" or "product XXXX"
        r"\bitem\s*[:=]?\s*([A-Za-z0-9\-]+)",
        r"\bproduct\s*[:=]?\s*([A-Za-z0-9\-]+)",
        # "for XXXXXXXX" (long token only)
        r"\bfor\s+([A-Za-z0-9\-]{6,})\b",
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, q, flags=re.IGNORECASE):
            value = (match.group(1) or "").strip(" .,:;!?()[]{}")
            if value and value.lower() not in _ITEM_EXTRACT_KEYWORD_BLOCKLIST and value not in candidates:
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
    demand_language = any(term in ql for term in [
        "demand", "met", "meet", "unmet", "fulfilled",
        "root cause", "lineage",
        # EOH / inventory queries
        "eoh", "end of horizon", "end-of-horizon", "projected inventory",
        "closing inventory", "horizon inventory",
        # fill rate / utilization root-cause queries
        "fill rate", "utilization", "late", "short", "early",
    ])

    selected = candidates[0] if len(candidates) == 1 else None
    if not selected and demand_language and len(candidates) > 0:
        # "demand for item XXXX" — skip the word "item" and grab what follows it
        demand_for = re.search(r"\bdemand\s+for\s+item\s+([A-Za-z0-9\-]+)", q, flags=re.IGNORECASE)
        if not demand_for:
            demand_for = re.search(r"\bdemand\s+for\s+([A-Za-z0-9\-]+)", q, flags=re.IGNORECASE)
        if demand_for:
            val = demand_for.group(1).strip()
            if val.lower() not in _ITEM_EXTRACT_KEYWORD_BLOCKLIST:
                selected = val
        if not selected:
            # pick the first candidate that looks like an identifier (not a plain word)
            selected = next(
                (c for c in candidates if c.lower() not in _ITEM_EXTRACT_KEYWORD_BLOCKLIST),
                None,
            )

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


def _infer_recent_item_from_history(history: Optional[List[Dict[str, str]]]) -> Optional[str]:
    for msg in reversed(history or []):
        role = (msg.get("role") or "").strip().lower()
        if role != "user":
            continue
        content = (msg.get("content") or "").strip()
        if not content:
            continue
        inference = _infer_demand_item_from_question(content)
        if inference.get("selected_item"):
            return inference["selected_item"]
    return None


def _resolve_chat_item(question: str, history: Optional[List[Dict[str, str]]]) -> Dict:
    current = _infer_demand_item_from_question(question)
    selected = current.get("selected_item")
    source = "question" if selected else None

    if not selected:
        ql = (question or "").lower()
        reference_terms = [
            "for the item",
            "that item",
            "this item",
            "same item",
            "the item",
        ]
        demand_supply_terms = ["demand", "supply", "unmet", "root cause", "lineage", "details"]
        is_reference_question = any(term in ql for term in reference_terms)
        is_demand_supply_followup = any(term in ql for term in demand_supply_terms)
        if is_reference_question or is_demand_supply_followup:
            prior_item = _infer_recent_item_from_history(history)
            if prior_item:
                selected = prior_item
                source = "history"

    return {
        "selected_item": selected,
        "source": source,
        "question_inference": current,
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


def _parse_demand_entity(demand_id: Optional[str], demand_entity: Optional[Dict]) -> DomainDemandEntity:
    if demand_entity:
        entity_type_raw = (demand_entity.get("type") or "").strip().lower()
        entity_id = (demand_entity.get("id") or "").strip()
        try:
            entity_type = DemandEntityType(entity_type_raw)
        except ValueError:
            entity_type = DemandEntityType.ITEM
        return DomainDemandEntity(entity_type=entity_type, entity_id=entity_id, resolved_item=entity_id if entity_type == DemandEntityType.ITEM else None)

    fallback_id = (demand_id or "").strip()
    return DomainDemandEntity(
        entity_type=DemandEntityType.ITEM,
        entity_id=fallback_id,
        resolved_item=fallback_id or None,
        resolution_note="Legacy demand_id interpreted as ITEM.",
    )


def _resolve_entity_to_item(
    inddmdview_file: Optional[Path],
    entity: DomainDemandEntity,
    week_id: Optional[str],
    scenario_id: Optional[str],
    site: Optional[str],
) -> DomainDemandEntity:
    if entity.entity_type == DemandEntityType.ITEM:
        entity.resolved_item = entity.entity_id or None
        if not entity.resolution_note:
            entity.resolution_note = "Demand entity type item maps directly to ITEM."
        return entity

    if not inddmdview_file or not entity.entity_id:
        entity.resolution_note = "Could not resolve demand entity to ITEM due to missing demand output evidence."
        return entity

    target = entity.entity_id.strip()
    item_totals: Dict[str, float] = {}
    site_filter = (site or "").strip()

    dmdtype_map = {
        DemandEntityType.FORECAST: "fcst",
        DemandEntityType.TRANSFER: "xfer",
        DemandEntityType.DEPENDENT: "dep",
    }

    for row in _safe_rows(inddmdview_file):
        if site_filter and (row.get("LOC") or "").strip() != site_filter:
            continue
        if not _matches_context(row, week_id, scenario_id):
            continue

        item = (row.get("ITEM") or "").strip()
        if not item:
            continue

        matched = False
        if entity.entity_type == DemandEntityType.ORDER:
            if (row.get("EXTORDERID") or "").strip() == target or (row.get("HEADEREXTREF") or "").strip() == target:
                matched = True
        elif entity.entity_type in {DemandEntityType.FORECAST, DemandEntityType.TRANSFER, DemandEntityType.DEPENDENT}:
            dmd_type = (row.get("DMDTYPE") or "").strip().lower()
            token = dmdtype_map.get(entity.entity_type, "")
            if token and token in dmd_type and (item == target or not target):
                matched = True

        if matched:
            item_totals[item] = item_totals.get(item, 0.0) + _safe_float(row.get("QTY"))

    if not item_totals:
        entity.resolution_note = (
            f"Demand entity type '{entity.entity_type.value}' with id '{target}' could not be resolved to ITEM in by_if_snop_out_inddmdview."
        )
        return entity

    entity.resolved_item = max(item_totals.items(), key=lambda kv: kv[1])[0]
    entity.resolution_note = (
        f"Demand entity type '{entity.entity_type.value}' id '{target}' resolved to ITEM '{entity.resolved_item}' by highest matched demand quantity."
    )
    return entity


def _grade_evidence(demand_qty_total: float, link_rows_count: int, gaps: List[str]) -> EvidenceGrade:
    if demand_qty_total > 0 and link_rows_count > 0 and len(gaps) == 0:
        return EvidenceGrade.HIGH
    if demand_qty_total > 0:
        return EvidenceGrade.MEDIUM
    return EvidenceGrade.LOW


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return numerator / denominator


def _stddev(values: List[float]) -> Optional[float]:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    var = sum((x - mean) ** 2 for x in values) / len(values)
    return math.sqrt(var)


def _build_domain_focus_assessment(
    demand_qty_total: float,
    scheduled_qty_total: float,
    unmet_qty: float,
    on_time_sched_qty: float,
    late_sched_qty: float,
    lateness_days: List[float],
    supply_lead_variability_days: Optional[float],
    capacity_exception_count: int,
    capacity_overutil_qty: float,
    competing_higher_priority_count: int,
    setup_flags: Dict[str, bool],
    bom_parent_rows: List[Dict],
    bom_component_rows: List[Dict],
    production_rows: List[Dict],
    sourcing_out_rows: List[Dict],
    sourcing_in_rows: List[Dict],
    evidence_grade: EvidenceGrade,
) -> Dict:
    case_fill_rate = _safe_ratio(scheduled_qty_total, demand_qty_total) * 100.0
    otif = _safe_ratio(on_time_sched_qty, demand_qty_total) * 100.0
    perfect_order_index = min(otif, case_fill_rate)

    delayed_orders_count_proxy = len([x for x in lateness_days if x > 0])
    lead_time_variability = _stddev(lateness_days)

    return {
        "Fulfillment Domain": {
            "bounded_context": BY_ESP_DOMAIN_FRAMEWORK["Fulfillment"].get("bounded_context"),
            "user_story": BY_ESP_DOMAIN_FRAMEWORK["Fulfillment"].get("user_story"),
            "key_inputs_outputs": BY_ESP_DOMAIN_FRAMEWORK["Fulfillment"].get("key_inputs_outputs"),
            "focus": "Customer commitments and service level effectiveness.",
            "Met Demand": {
                "OTIF_pct": round(otif, 2),
                "Case_Fill_Rate_pct": round(case_fill_rate, 2),
                "Perfect_Order_Index_proxy_pct": round(perfect_order_index, 2),
            },
            "Unmet Demand": {
                "Stockouts_qty_proxy": round(unmet_qty, 3),
                "Lost_Sales_qty": None,
                "Backorders_qty_proxy": round(max(unmet_qty + late_sched_qty, 0.0), 3),
            },
            "Delayed Orders": {
                "Backlog_Age_days": None,
                "DSO_days": None,
                "Delivery_Lead_Time_Variability_days": round(lead_time_variability, 3) if lead_time_variability is not None else None,
                "Delayed_Order_Count_proxy": delayed_orders_count_proxy,
            },
            "evidence_grade": evidence_grade.value,
        },
        "Generation Domain": {
            "bounded_context": BY_ESP_DOMAIN_FRAMEWORK["Generation"].get("bounded_context"),
            "user_story": BY_ESP_DOMAIN_FRAMEWORK["Generation"].get("user_story"),
            "key_inputs_outputs": BY_ESP_DOMAIN_FRAMEWORK["Generation"].get("key_inputs_outputs"),
            "focus": "Constraints, policies, and parameters driving the supply plan.",
            "Capacity": {
                "Machine_Downtime": None,
                "Labor_Shortages": None,
                "OEE_pct": None,
                "Capacity_Exception_Rows": int(capacity_exception_count),
                "Capacity_Overutil_Qty": round(capacity_overutil_qty, 3),
            },
            "Lead Time": {
                "Supplier_Lead_Time_days": None,
                "Transit_Time_days": None,
                "Lead_Time_Variability_days": round(supply_lead_variability_days, 3) if supply_lead_variability_days is not None else None,
            },
            "Calendar Gaps": {
                "Holiday_Shutdowns": None,
                "Planned_Maintenance": None,
                "Shift_Variances": None,
            },
            "allocation_pressure": {
                "Higher_Priority_Competing_Rows": int(competing_higher_priority_count),
            },
            "evidence_grade": evidence_grade.value,
        },
        "Data Hygiene Domain": {
            "bounded_context": BY_ESP_DOMAIN_FRAMEWORK["Data Hygiene"].get("bounded_context"),
            "user_story": BY_ESP_DOMAIN_FRAMEWORK["Data Hygiene"].get("user_story"),
            "key_inputs_outputs": BY_ESP_DOMAIN_FRAMEWORK["Data Hygiene"].get("key_inputs_outputs"),
            "focus": "Structural integrity and quality of planning master and parameter data.",
            "Bad Masters": {
                "Outdated_BOM_proxy": int(len(bom_parent_rows) == 0 and len(bom_component_rows) == 0),
                "Incorrect_Routings_proxy": int(len(production_rows) == 0),
                "Duplicate_Item_Codes": None,
            },
            "Parameter Gaps": {
                "Unmaintained_Safety_Stock": None,
                "Missing_MOQ": None,
                "Incorrect_Lot_Sizes": None,
            },
            "setup_integrity": {
                "item_exists_in_master": setup_flags.get("item_exists_in_master"),
                "sku_coverage_exists": setup_flags.get("sku_coverage_exists"),
                "production_method_exists": setup_flags.get("production_method_exists"),
                "sourcing_path_exists": setup_flags.get("sourcing_path_exists"),
                "sourcing_out_paths": len(sourcing_out_rows),
                "sourcing_in_paths": len(sourcing_in_rows),
            },
            "evidence_grade": evidence_grade.value,
        },
        "Notes": [
            "Metrics marked null are not directly available from current snapshot schema and require upstream KPI or finance datasets.",
            "OTIF and fill-rate values are computed proxies from demand and scheduled quantities in current by_output evidence.",
        ],
    }


def _ollama_chat(prompt: str, system_prompt: str) -> Optional[str]:
    return _ollama_chat_with_model(prompt, system_prompt, LLM_CONFIG["model"])


# ---------------------------------------------------------------------------
# Streaming LLM — yields text chunks via SSE (all HTTP providers + OpenVINO)
# ---------------------------------------------------------------------------

def stream_llm(
    prompt: str,
    system_prompt: str,
    model_name: Optional[str] = None,
    history: Optional[List[Dict[str, str]]] = None,
) -> Generator[str, None, None]:
    """
    Yield LLM response text incrementally.
    HTTP providers: uses 'stream: true' + SSE (text/event-stream).
    OpenVINO: uses openvino_genai TextStreamer (in-process callback, zero network overhead).
    Each yielded value is a plain text chunk (delta), not the full response.
    """
    selected_model = (model_name or LLM_CONFIG["model"]).strip() or LLM_CONFIG["model"]
    provider = LLM_CONFIG["provider"]

    # ── OpenVINO path: in-process streaming via TextStreamer callback ──────────
    if provider == "openvino":
        yield from _stream_openvino(prompt, system_prompt, selected_model)
        return

    # ── HTTP path: SSE streaming (stream=true) ────────────────────────────────
    messages = [{"role": "system", "content": system_prompt}]
    for msg in (history or []):
        role = (msg.get("role") or "").strip().lower()
        content = (msg.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": selected_model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 600,
        "stream": True,            # ← key change: enables SSE streaming
    }
    data = json.dumps(payload).encode("utf-8")

    base_url = LLM_CONFIG["base_url"]
    if provider == "azure":
        endpoint = f"{base_url}/chat/completions?api-version={LLM_CONFIG.get('api_version', '2024-02-01')}"
    else:
        endpoint = f"{base_url}/v1/chat/completions"

    headers = {"Content-Type": "application/json"}
    if LLM_CONFIG.get("api_key"):
        auth_hdr = LLM_CONFIG.get("auth_header", "Authorization")
        headers[auth_hdr] = f"Bearer {LLM_CONFIG['api_key']}" if auth_hdr == "Authorization" else LLM_CONFIG['api_key']
    if provider == "anthropic":
        headers["anthropic-version"] = "2023-06-01"

    req = request.Request(endpoint, data=data, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=300) as resp:
            in_think = False
            for raw_line in resp:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or line == "data: [DONE]":
                    continue
                if not line.startswith("data: "):
                    continue
                try:
                    chunk = json.loads(line[6:])
                except json.JSONDecodeError:
                    continue
                delta = (chunk.get("choices") or [{}])[0].get("delta") or {}
                text  = delta.get("content") or ""
                if not text:
                    continue
                # Strip DeepSeek-R1 think block incrementally
                if "</think>" in text:
                    text = text.split("</think>", 1)[-1]
                    in_think = False
                if "<think>" in text or in_think:
                    in_think = True
                    continue
                if text:
                    yield text
    except (error.URLError, TimeoutError, OSError):
        return


def _stream_openvino(prompt: str, system_prompt: str, selected_model: str) -> Generator[str, None, None]:
    """Stream tokens from openvino_genai using TextStreamer (zero HTTP overhead)."""
    import openvino_genai as ov_genai
    from queue import Queue, Empty

    pipeline = LLM_CONFIG.get("pipeline") or _get_openvino_pipeline()
    q: Queue = Queue()

    class _QueueStreamer(ov_genai.StreamerBase):
        def put(self, token_id: int) -> ov_genai.StreamingStatus:  # type: ignore[override]
            decoded = pipeline.get_tokenizer().decode([token_id])
            q.put(decoded)
            return ov_genai.StreamingStatus.RUNNING

        def end(self):
            q.put(None)  # sentinel

    formatted = (
        f"<|im_start|>system\n{system_prompt}<|im_end|>\n"
        f"<|im_start|>user\n{prompt}<|im_end|>\n"
        f"<|im_start|>assistant\n"
    )

    import threading
    streamer = _QueueStreamer()
    t = threading.Thread(
        target=pipeline.generate,
        args=(formatted,),
        kwargs={"max_new_tokens": 900, "temperature": 0.1, "do_sample": False, "streamer": streamer},
        daemon=True,
    )
    t.start()

    in_think = False
    buffer = ""
    while True:
        try:
            token = q.get(timeout=30)
        except Empty:
            break
        if token is None:
            break
        buffer += token
        # Strip DeepSeek-R1 think block
        if "</think>" in buffer:
            buffer = buffer.split("</think>", 1)[-1]
            in_think = False
        if "<think>" in buffer or in_think:
            in_think = True
            continue
        if buffer:
            yield buffer
            buffer = ""


def _env_flag(value: Optional[str], default: bool = False) -> bool:
    text = (value or "").strip().lower()
    if not text:
        return default
    return text in {"1", "true", "yes", "on"}


def _parse_json_object_from_text(text: str) -> Optional[Dict]:
    content = (text or "").strip()
    if not content:
        return None

    try:
        parsed = json.loads(content)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None

    try:
        parsed = json.loads(content[start : end + 1])
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        return None
    return None


def _judge_llm_output(
    question: str,
    answer: str,
    workflow_name: str,
    context: Dict,
    grounded_result: Optional[Dict],
    llm_model: Optional[str],
) -> Optional[Dict]:
    if not _env_flag(NOLLAMA_JUDGE_ENABLED, default=True):
        return None

    system_prompt = (
        "You are a strict LLM judge for IFSP planning assistant quality. "
        "Evaluate assistant output for factuality, groundedness, completeness, and clarity. "
        "Never invent evidence. If answer is weak, provide concise correction guidance. "
        "Return JSON only."
    )

    prompt = "\n\n".join(
        [
            f"User question: {question}",
            f"Assistant answer: {answer}",
            f"Workflow: {workflow_name}",
            f"Context: {json.dumps(context, ensure_ascii=True)}",
            f"Grounded result JSON: {json.dumps(grounded_result or {}, ensure_ascii=True)}",
            (
                "Return only valid JSON with keys: "
                "verdict (pass|needs_revision|fail), overall_score (0-100), factuality (0-100), "
                "groundedness (0-100), completeness (0-100), clarity (0-100), "
                "issues (array of strings), recommended_fixes (array of strings), revised_answer (string)."
            ),
        ]
    )

    review_text = _ollama_chat_with_model(prompt, system_prompt, LLM_CONFIG["judge_model"])
    if not review_text:
        return {
            "status": "unavailable",
            "judge_model": LLM_CONFIG["judge_model"],
            "reason": "Judge model did not return a response.",
        }

    parsed = _parse_json_object_from_text(review_text)
    if not parsed:
        return {
            "status": "parse_error",
            "judge_model": LLM_CONFIG["judge_model"],
            "raw_review": review_text,
            "reason": "Judge response was not valid JSON.",
        }

    parsed["status"] = parsed.get("status") or "ok"
    parsed["judge_model"] = parsed.get("judge_model") or LLM_CONFIG["judge_model"]
    parsed["target_llm_model"] = parsed.get("target_llm_model") or ((llm_model or LLM_CONFIG["model"]).strip() or LLM_CONFIG["model"])
    return parsed


def _ollama_chat_with_model(
    prompt: str,
    system_prompt: str,
    model_name: Optional[str],
    history: Optional[List[Dict[str, str]]] = None,
) -> Optional[str]:
    """
    Call the configured LLM provider with a chat message.
    Supports: Nollama (local), OpenAI, Custom, and OpenVINO (optimized local).
    """
    selected_model = (model_name or LLM_CONFIG["model"]).strip() or LLM_CONFIG["model"]
    
    # Handle OpenVINO provider (local optimized inference)
    if LLM_CONFIG["provider"] == "openvino":
        return _openvino_chat_with_model(prompt, system_prompt, selected_model)
    
    # Handle OpenAI-compatible providers (Nollama, OpenAI, Custom)
    messages = [{"role": "system", "content": system_prompt}]

    for msg in (history or []):
        role = (msg.get("role") or "").strip().lower()
        content = (msg.get("content") or "").strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": prompt})

    # Build request for OpenAI-compatible API (works for Nollama, OpenAI, Anthropic, Azure, custom)
    payload = {
        "model": selected_model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 900,
    }

    data = json.dumps(payload).encode("utf-8")
    
    # Azure uses /chat/completions?api-version=... (no /v1/ prefix); all others use /v1/chat/completions
    base_url = LLM_CONFIG["base_url"]
    if LLM_CONFIG.get("provider") == "azure":
        endpoint = f"{base_url}/chat/completions?api-version={LLM_CONFIG.get('api_version', '2024-02-01')}"
    else:
        endpoint = f"{base_url}/v1/chat/completions"
    
    # Prepare headers — auth_header key controls whether to use Bearer, x-api-key, or api-key
    headers = {"Content-Type": "application/json"}
    if LLM_CONFIG.get("api_key"):
        auth_hdr = LLM_CONFIG.get("auth_header", "Authorization")
        headers[auth_hdr] = f"Bearer {LLM_CONFIG['api_key']}" if auth_hdr == "Authorization" else LLM_CONFIG['api_key']
    if LLM_CONFIG.get("provider") == "anthropic":
        headers["anthropic-version"] = "2023-06-01"
    
    req = request.Request(
        endpoint,
        data=data,
        headers=headers,
        method="POST",
    )

    try:
        with request.urlopen(req, timeout=300) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (error.URLError, TimeoutError, json.JSONDecodeError, OSError) as e:
        return None

    # Parse OpenAI format response (standard across all providers)
    choices = body.get("choices") or []
    if choices:
        message = choices[0].get("message") or {}
        content = (message.get("content") or "").strip()
        return content or None
    return None


def _openvino_chat_with_model(prompt: str, system_prompt: str, selected_model: str) -> Optional[str]:
    """
    Send a chat request to OpenVINO-optimized local LLM with latency hints.
    Supports GPU acceleration with performance tuning for low-latency inference.
    
    Configuration:
    - OPENVINO_MODEL_PATH: Path to quantized model (e.g., ./DeepSeek-R1-Distill-Qwen-7B-int4-ov)
    - OPENVINO_DEVICE: GPU, CPU, NPU (default: GPU)
    - OPENVINO_PERFORMANCE_HINT: LATENCY or THROUGHPUT (default: LATENCY)
    - OPENVINO_NUM_STREAMS: Number of streams for THROUGHPUT mode (default: 1)
    """
    try:
        pipeline = LLM_CONFIG.get("pipeline")
        if not pipeline:
            pipeline = _get_openvino_pipeline()
        
        # Format messages for OpenVINO chat format
        formatted_prompt = f"<|im_start|>system\n{system_prompt}<|im_end|>\n<|im_start|>user\n{prompt}<|im_end|>\n<|im_start|>assistant\n"
        
        # Generate response - cap max_new_tokens to limit reasoning chain length
        response = pipeline.generate(
            formatted_prompt,
            max_new_tokens=1200,
            temperature=0.2,
            top_p=0.9,
            do_sample=True
        )
        
        if response:
            # DeepSeek-R1 omits the opening <think> tag; split on </think> to get final answer
            if "</think>" in response:
                result = response.split("</think>", 1)[-1]
            else:
                result = response
            result = result.split("<|im_end|>")[0].strip()
            return result if result else None
        return None
        
    except Exception as e:
        print(f"[OpenVINO] Chat error: {e}")
        return None


def list_ollama_models() -> Dict:
    """
    List available models from the configured LLM provider.
    Supports: Nollama, OpenAI, Custom, and OpenVINO (optimized local).
    """
    provider = LLM_CONFIG["provider"]
    model = LLM_CONFIG["model"]
    
    # Handle OpenVINO provider (local optimized models)
    if provider == "openvino":
        return {
            "provider": "OpenVINO",
            "reachable": True,
            "default_model": model,
            "best_available": model,
            "recommended_models": [model],
            "models": [model],
            "model_info": {
                model: {
                    "recommended": True,
                    "note": "OpenVINO-optimized local model (GPU-accelerated, latency-optimized)",
                    "device": OPENVINO_DEVICE,
                    "performance_hint": OPENVINO_PERFORMANCE_HINT,
                    "model_path": OPENVINO_MODEL_PATH,
                }
            },
        }
    
    # Handle OpenAI provider
    if provider == "openai":
        return {
            "provider": "OpenAI",
            "reachable": True,
            "default_model": model,
            "best_available": model,
            "recommended_models": [model],
            "models": [model],
            "model_info": {model: {"recommended": True, "note": "Configured OpenAI model"}},
        }

    # Handle Azure OpenAI — return deployment name, no model list call needed
    if provider == "azure":
        return {
            "provider": "Azure OpenAI",
            "reachable": True,
            "default_model": model,
            "best_available": model,
            "recommended_models": [model],
            "models": [model],
            "model_info": {
                model: {
                    "recommended": True,
                    "note": f"Azure deployment: {model}, api-version: {LLM_CONFIG.get('api_version')}",
                }
            },
        }

    # Handle Anthropic — return configured model, no model list call needed
    if provider == "anthropic":
        return {
            "provider": "Anthropic",
            "reachable": True,
            "default_model": model,
            "best_available": model,
            "recommended_models": [model],
            "models": [model],
            "model_info": {model: {"recommended": True, "note": "Configured Anthropic model"}},
        }
    
    # Handle Nollama and Custom providers (use v1 API)
    base_url = LLM_CONFIG["base_url"]
    if provider == "custom":
        _MODEL_PRIORITY = [(model, "Custom LLM model")]
    else:  # Nollama (default)
        _MODEL_PRIORITY: List[Tuple[str, str]] = [
            ("qwen2@GPU", "Qwen2 - High performance reasoning model"),
        ]
    
    _RECOMMENDED_NAMES = {name for name, _ in _MODEL_PRIORITY}
    
    # Try to fetch models via v1 API
    headers = {"Content-Type": "application/json"}
    if LLM_CONFIG.get("api_key"):
        auth_hdr = LLM_CONFIG.get("auth_header", "Authorization")
        headers[auth_hdr] = f"Bearer {LLM_CONFIG['api_key']}" if auth_hdr == "Authorization" else LLM_CONFIG['api_key']
    if LLM_CONFIG.get("provider") == "anthropic":
        headers["anthropic-version"] = "2023-06-01"
    
    req = request.Request(
        f"{base_url}/v1/models",
        headers=headers,
        method="GET"
    )
    
    try:
        with request.urlopen(req, timeout=15) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return {
            "provider": provider.capitalize(),
            "reachable": False,
            "default_model": model,
            "best_available": model,
            "recommended_models": [name for name, _ in _MODEL_PRIORITY],
            "models": [],
            "model_info": {},
        }

    available: List[str] = []
    # Parse OpenAI v1 format response (standard for all v1 API providers)
    for model_data in body.get("data", []):
        model_id = (model_data.get("id") or "").strip()
        if model_id:
            available.append(model_id)

    available_set = set(available)

    # Pick the best model from the priority list that is actually available
    best_available = model
    for name, _ in _MODEL_PRIORITY:
        if name in available_set:
            best_available = name
            break

    # Build per-model metadata for the UI
    model_info: Dict[str, Dict] = {}
    for name in available:
        rec = next(((n, d) for n, d in _MODEL_PRIORITY if n == name), None)
        model_info[name] = {
            "recommended": name in _RECOMMENDED_NAMES,
            "note": rec[1] if rec else "",
        }

    return {
        "provider": provider.capitalize(),
        "reachable": True,
        "default_model": model,
        "best_available": best_available,
        "recommended_models": [name for name, _ in _MODEL_PRIORITY if name in available_set],
        "models": available,
        "model_info": model_info,
        }
    
    # For other providers (Nollama, custom), try to fetch models via v1 API
    headers = {"Content-Type": "application/json"}
    if LLM_CONFIG.get("api_key"):
        auth_hdr = LLM_CONFIG.get("auth_header", "Authorization")
        headers[auth_hdr] = f"Bearer {LLM_CONFIG['api_key']}" if auth_hdr == "Authorization" else LLM_CONFIG['api_key']
    if LLM_CONFIG.get("provider") == "anthropic":
        headers["anthropic-version"] = "2023-06-01"
    
    req = request.Request(
        f"{base_url}/v1/models",
        headers=headers,
        method="GET"
    )
    
    try:
        with request.urlopen(req, timeout=15) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return {
            "provider": provider.capitalize(),
            "reachable": False,
            "default_model": model,
            "best_available": model,
            "recommended_models": [name for name, _ in _MODEL_PRIORITY],
            "models": [],
            "model_info": {},
        }

    available: List[str] = []
    # Parse OpenAI v1 format response (standard for all v1 API providers)
    for model_data in body.get("data", []):
        model_id = (model_data.get("id") or "").strip()
        if model_id:
            available.append(model_id)

    available_set = set(available)

    # Pick the best model from the priority list that is actually available
    best_available = model
    for name, _ in _MODEL_PRIORITY:
        if name in available_set:
            best_available = name
            break

    # Build per-model metadata for the UI
    model_info: Dict[str, Dict] = {}
    for name in available:
        rec = next(((n, d) for n, d in _MODEL_PRIORITY if n == name), None)
        model_info[name] = {
            "recommended": name in _RECOMMENDED_NAMES,
            "note": rec[1] if rec else "",
        }

    return {
        "provider": provider.capitalize(),
        "reachable": True,
        "default_model": model,
        "best_available": best_available,
        "recommended_models": [name for name, _ in _MODEL_PRIORITY if name in available_set],
        "models": available,
        "model_info": model_info,
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

    selected_model = (llm_model or LLM_CONFIG["model"]).strip() or LLM_CONFIG["model"]
    answer = _ollama_chat_with_model("\n\n".join(prompt_parts), system_prompt, selected_model)
    if not answer:
        return None

    return {
        "Assistant Reply": answer,
        "Workflow": workflow,
        "Grounded Result": result,
        "LLM Provider": LLM_CONFIG["provider"].capitalize(),
        "LLM Model": selected_model,
    }


def run_validation(base_dir: Path, week_id: Optional[str], scenario_id: Optional[str], scope: Dict, focus_areas: List[str]) -> Dict:
    requested_focus = [str(area or "").strip().lower() for area in (focus_areas or []) if str(area or "").strip()]
    if "data_quality_input" in requested_focus:
        return run_input_data_quality(base_dir, _normalize_week_id(week_id), _normalize_scenario_id(scenario_id))
    if "bom_traversal" in requested_focus:
        return run_bom_traversal_check(base_dir, _normalize_week_id(week_id), _normalize_scenario_id(scenario_id), scope)
    if "production_route" in requested_focus:
        return run_production_route_check(base_dir, _normalize_week_id(week_id), _normalize_scenario_id(scenario_id), scope)

    context = _resolve_context(base_dir, week_id, scenario_id)
    week_id = context["week_id"]
    scenario_id = context["scenario_id"]
    input_dir = base_dir / INPUT_FOLDER
    output_dir = base_dir / OUTPUT_FOLDER

    valid_focus_order = ["master_data", "bom", "parameters", "output_sanity"]
    selected_focus = [area for area in valid_focus_order if area in requested_focus] or valid_focus_order
    selected_focus_set = set(selected_focus)

    required_input_by_focus = {
        "master_data": ["if_snop_items-", "if_snop_locations-", "if_snop_customer-", "if_snop_sku-"],
        "bom": ["if_snop_billofmaterials-", "if_snop_items-", "if_snop_locations-"],
        "parameters": ["if_snop_sourcing-", "if_snop_productionmethod-", "if_snop_items-", "if_snop_locations-"],
        "output_sanity": [],
    }
    required_output_by_focus = {
        "master_data": [],
        "bom": [],
        "parameters": [],
        "output_sanity": ["by_if_snop_out_planorder-", "by_if_snop_out_skuexception-", "by_if_snop_out_resloaddetail-"],
    }

    required_input_prefixes = sorted({p for area in selected_focus for p in required_input_by_focus.get(area, [])})
    required_output_prefixes = sorted({p for area in selected_focus for p in required_output_by_focus.get(area, [])})

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

    check_focus_map = {
        "bom_orphan_parent_item": "bom",
        "bom_orphan_component_item": "bom",
        "bom_orphan_location": "bom",
        "sku_missing_item": "master_data",
        "sku_missing_location": "master_data",
        "sku_missing_customer": "master_data",
        "sourcing_missing_source_location": "parameters",
        "sourcing_missing_dest_location": "parameters",
        "prod_method_missing_item": "parameters",
        "prod_method_missing_location": "parameters",
    }

    checks = {metric: value for metric, value in checks.items() if check_focus_map.get(metric) in selected_focus_set}

    planorder = _find_file_by_prefix(output_dir, "by_if_snop_out_planorder-")
    skuexception = _find_file_by_prefix(output_dir, "by_if_snop_out_skuexception-")
    resloaddetail = _find_file_by_prefix(output_dir, "by_if_snop_out_resloaddetail-")

    def _count_rows_in_scope(file_path: Optional[Path]) -> int:
        if not file_path:
            return 0
        total = 0
        for row in _safe_rows(file_path):
            row_week = (row.get("CAPTURE_WK") or "").strip()
            row_scenario = (row.get("SIMULATION_NAME") or "").strip()
            if week_id and row_week and row_week != week_id:
                continue
            if scenario_id and row_scenario and not _scenario_match(row_scenario, scenario_id):
                continue
            total += 1
        return total

    output_sanity_checks = {}
    if "output_sanity" in selected_focus_set:
        output_sanity_checks = {
            "planorder_rows_in_scope": _count_rows_in_scope(planorder),
            "skuexception_rows_in_scope": _count_rows_in_scope(skuexception),
            "resloaddetail_rows_in_scope": _count_rows_in_scope(resloaddetail),
        }
        checks.update(output_sanity_checks)

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

    if output_sanity_checks:
        if output_sanity_checks["planorder_rows_in_scope"] == 0:
            high.append("planorder_rows_in_scope: 0")
        if output_sanity_checks["resloaddetail_rows_in_scope"] == 0:
            medium.append("resloaddetail_rows_in_scope: 0")

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
        "focus_areas": selected_focus,
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
            "requested_focus_areas": requested_focus,
            "selected_focus_areas": selected_focus,
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


def run_bom_traversal_check(base_dir: Path, week_id: Optional[str], scenario_id: Optional[str], scope: Dict) -> Dict:
    input_dir = base_dir / INPUT_FOLDER
    context = _resolve_context(base_dir, week_id, scenario_id)

    bom_file = _find_latest_file_by_prefix(input_dir, "if_snop_billofmaterials-")
    item_file = _find_latest_file_by_prefix(input_dir, "if_snop_items-")
    item_char_file = _find_latest_file_by_prefix(input_dir, "if_snop_itemcharacteristic-")

    root_item_filter = (scope.get("product") or scope.get("node") or "").strip()
    site_filter = (scope.get("site") or "").strip()
    max_depth = 20

    if not bom_file:
        return {
            "Validation Scope": {
                "week_id": context.get("week_id"),
                "scenario_id": context.get("scenario_id"),
                "scope": scope,
                "focus_areas": ["bom_traversal"],
            },
            "Traversal Summary": {
                "total_bom_rows": 0,
                "roots_considered": 0,
                "traversal_rows": 0,
                "max_depth_reached": 0,
            },
            "Mind Map": {"nodes": [], "links": [], "levels": [], "root_items": []},
            "Traversal Rows": [],
            "Issues Found (Critical, High, Medium, Low)": {
                "Critical": ["Missing required dataset: if_snop_billofmaterials-*"],
                "High": [],
                "Medium": [],
                "Low": [],
            },
            "Readiness Verdict (Pass, Conditional Pass, Fail)": "Fail",
            "Recommended Fixes": [
                "Provide by_input BOM extract (if_snop_billofmaterials-*.csv).",
            ],
        }

    item_class_map: Dict[str, str] = {}
    item_die_code_map: Dict[str, str] = {}
    if item_file:
        for row in _safe_rows(item_file):
            item_id = (row.get("ITEM") or "").strip()
            if not item_id:
                continue
            item_class_map[item_id] = (row.get("ITEMCLASS") or row.get("ITEM_CLASS_NM") or "").strip()
            item_die_code_map[item_id] = (
                row.get("U_DIE_CODE_NM")
                or row.get("U_DIE_CODE_NAME")
                or row.get("U_DIE_CODE")
                or ""
            ).strip()

    item_order_point_map: Dict[str, str] = {}
    if item_char_file:
        for row in _safe_rows(item_char_file):
            item_id = (row.get("ITEM") or row.get("item_non_leading_zero_id") or "").strip()
            if not item_id:
                continue
            characteristic_nm = (row.get("CHARACTERISTIC_NM") or row.get("characteristic_nm") or "").strip().upper()
            if characteristic_nm != "ITEM_ORDER_POINT":
                continue
            val = (row.get("CHARACTERISTIC_VALUE_TXT") or row.get("characteristic_value_txt") or "").strip()
            if val:
                item_order_point_map[item_id] = val

    bom_rows = [row for row in _safe_rows(bom_file) if _row_matches_week_scenario(row, week_id, scenario_id)]
    if site_filter:
        bom_rows = [row for row in bom_rows if (row.get("LOC") or "").strip() == site_filter]

    adjacency: Dict[Tuple[str, str], List[Tuple[str, str, str]]] = {}
    parent_keys: set = set()
    component_item_ids: set = set()

    for row in bom_rows:
        parent = (row.get("ITEM") or "").strip()
        component = (row.get("SUBORD") or "").strip()
        loc = (row.get("LOC") or "").strip()
        bomnum = (row.get("BOMNUM") or "").strip()
        if not parent or not component or not loc:
            continue

        key = (parent, loc)
        adjacency.setdefault(key, []).append((component, loc, bomnum))
        parent_keys.add((parent, loc))
        component_item_ids.add(component)

    roots: List[Tuple[str, str]] = []
    if root_item_filter:
        roots = sorted([key for key in parent_keys if key[0] == root_item_filter])
    else:
        roots = sorted([key for key in parent_keys if key[0] not in component_item_ids])

    if not roots and root_item_filter:
        return {
            "Validation Scope": {
                "week_id": context.get("week_id"),
                "scenario_id": context.get("scenario_id"),
                "scope": scope,
                "focus_areas": ["bom_traversal"],
            },
            "Traversal Summary": {
                "total_bom_rows": len(bom_rows),
                "roots_considered": 0,
                "traversal_rows": 0,
                "max_depth_reached": 0,
            },
            "Mind Map": {"nodes": [], "links": [], "levels": [], "root_items": []},
            "Traversal Rows": [],
            "Issues Found (Critical, High, Medium, Low)": {
                "Critical": [],
                "High": [f"Requested root item '{root_item_filter}' not found as BOM parent in selected scope."],
                "Medium": [],
                "Low": [],
            },
            "Readiness Verdict (Pass, Conditional Pass, Fail)": "Conditional Pass",
            "Recommended Fixes": [
                "Provide a valid parent ITEM in BOM Traversal input.",
                "Remove item filter to traverse all BOM roots.",
            ],
        }

    traversal_rows: List[Dict] = []
    traversal_id = 0
    cycle_skips = 0
    max_depth_reached = 0
    links: List[Dict[str, str]] = []
    node_depth: Dict[str, int] = {}

    for root_item, root_loc in roots:
        traversal_id += 1
        stack: List[Tuple[str, str, int, Optional[str], Optional[str], str, str, set]] = [
            (root_item, root_loc, 1, None, None, root_item, root_loc, {(root_item, root_loc)})
        ]

        while stack:
            item_id, item_loc, depth, next_item, next_loc, initial_item, initial_loc, path = stack.pop()
            max_depth_reached = max(max_depth_reached, depth)
            children = adjacency.get((item_id, item_loc), [])

            for component_id, component_loc, bomnum in children:
                initial_die_code = item_die_code_map.get(initial_item, "")
                initial_item_label = f"{initial_item} ({initial_die_code})" if initial_die_code else initial_item
                row = {
                    "TRAVERSAL_ID": traversal_id,
                    "TRAVERSAL_DEPTH_NBR": depth,
                    "INITIAL_ITEM_ID": initial_item_label,
                    "ITEM_ORDER_POINT": item_order_point_map.get(initial_item),
                    "INITIAL_ITEM_KEY": initial_item,
                    "INITIAL_ITEM_PRODUCT_NAME": initial_die_code or None,
                    "INITIAL_ITEM_CLASS": item_class_map.get(initial_item, ""),
                    "INITIAL_PLANT_CD": initial_loc,
                    "ITEM_ID": item_id,
                    "ITEM_CLASS": item_class_map.get(item_id, ""),
                    "PREVIOUS_ITEM_ID": component_id,
                    "PREVIOUS_ITEM_CLASS": item_class_map.get(component_id, ""),
                    "PREVIOUS_PLANT_CD": component_loc,
                    "NEXT_ITEM_ID": next_item or initial_item,
                    "NEXT_ITEM_CLASS": item_class_map.get(next_item or initial_item, ""),
                    "NEXT_PLANT_CD": next_loc or "VF",
                    "LANE_ITEM": component_id,
                    "LANE_SOURCE": component_loc,
                    "LANE_DESTINATION": item_loc,
                    "BOMNUM": bomnum,
                }
                traversal_rows.append(row)

                parent_node = f"{item_id}|{item_loc}"
                child_node = f"{component_id}|{component_loc}"
                links.append({"from": parent_node, "to": child_node, "label": "BOM"})

                node_depth[parent_node] = min(depth - 1, node_depth.get(parent_node, depth - 1)) if parent_node in node_depth else depth - 1
                next_depth = depth
                node_depth[child_node] = min(next_depth, node_depth.get(child_node, next_depth)) if child_node in node_depth else next_depth

                child_key = (component_id, component_loc)
                if depth >= max_depth:
                    continue
                if child_key in path:
                    cycle_skips += 1
                    continue

                new_path = set(path)
                new_path.add(child_key)
                stack.append((component_id, component_loc, depth + 1, item_id, item_loc, initial_item, initial_loc, new_path))

    unique_links = []
    seen_link_keys = set()
    for link in links:
        key = (link["from"], link["to"], link["label"])
        if key in seen_link_keys:
            continue
        seen_link_keys.add(key)
        unique_links.append(link)

    nodes: List[Dict[str, object]] = []
    for node_key, depth in sorted(node_depth.items(), key=lambda kv: (kv[1], kv[0])):
        item_id, loc = node_key.split("|", 1)
        nodes.append(
            {
                "id": node_key,
                "item_id": item_id,
                "loc": loc,
                "item_class": item_class_map.get(item_id, ""),
                "depth": int(depth),
                "is_root": node_key in {f"{i}|{l}" for (i, l) in roots},
            }
        )

    levels_map: Dict[int, List[str]] = {}
    for node in nodes:
        levels_map.setdefault(int(node["depth"]), []).append(f"{node['item_id']}@{node['loc']}")
    levels = [
        {"depth": depth, "items": sorted(items)}
        for depth, items in sorted(levels_map.items(), key=lambda kv: kv[0])
    ]

    critical: List[str] = []
    high: List[str] = []
    medium: List[str] = []
    low: List[str] = []
    if not traversal_rows:
        high.append("No traversal edges found for selected filters.")
    if cycle_skips > 0:
        medium.append(f"Cycle protection skipped {cycle_skips} recursive expansions.")

    verdict = "Pass"
    if critical:
        verdict = "Fail"
    elif high:
        verdict = "Conditional Pass"

    return {
        "Validation Scope": {
            "week_id": context.get("week_id"),
            "scenario_id": context.get("scenario_id"),
            "scope": scope,
            "focus_areas": ["bom_traversal"],
            "item_filter": root_item_filter or None,
            "site_filter": site_filter or None,
            "max_depth": max_depth,
        },
        "Traversal Summary": {
            "total_bom_rows": len(bom_rows),
            "roots_considered": len(roots),
            "traversal_rows": len(traversal_rows),
            "unique_nodes": len(nodes),
            "unique_links": len(unique_links),
            "max_depth_reached": max_depth_reached,
            "cycle_skips": cycle_skips,
        },
        "Mind Map": {
            "nodes": nodes,
            "links": unique_links,
            "levels": levels,
            "root_items": [f"{item}@{loc}" for (item, loc) in roots],
        },
        "Traversal Rows": traversal_rows[:1500],
        "Issues Found (Critical, High, Medium, Low)": {
            "Critical": critical,
            "High": high,
            "Medium": medium,
            "Low": low,
        },
        "Readiness Verdict (Pass, Conditional Pass, Fail)": verdict,
        "Recommended Next Checks": [
            "Apply ITEM filter to inspect a specific root-to-component lineage path.",
            "Cross-check edges with production method and production step for route completeness.",
        ],
    }


def run_production_route_check(base_dir: Path, week_id: Optional[str], scenario_id: Optional[str], scope: Dict) -> Dict:
    input_dir = base_dir / INPUT_FOLDER
    context = _resolve_context(base_dir, week_id, scenario_id)

    bom_file = _find_latest_file_by_prefix(input_dir, "if_snop_billofmaterials-")
    prod_method_file = _find_latest_file_by_prefix(input_dir, "if_snop_productionmethod-")
    prod_step_file = _find_latest_file_by_prefix(input_dir, "if_snop_productionstep-")
    res_file = _find_latest_file_by_prefix(input_dir, "if_snop_res-")

    missing_required = []
    if not bom_file:
        missing_required.append("if_snop_billofmaterials-")
    if not prod_method_file:
        missing_required.append("if_snop_productionmethod-")
    if not prod_step_file:
        missing_required.append("if_snop_productionstep-")
    if not res_file:
        missing_required.append("if_snop_res-")

    def _load_rows(file_path: Optional[Path]) -> List[Dict]:
        if not file_path:
            return []
        return [row for row in _safe_rows(file_path) if _row_matches_week_scenario(row, week_id, scenario_id)]

    bom_rows = _load_rows(bom_file)
    prod_method_rows = _load_rows(prod_method_file)
    prod_step_rows = _load_rows(prod_step_file)
    res_rows = _load_rows(res_file)

    bom_keys = {
        ((row.get("ITEM") or "").strip(), (row.get("LOC") or "").strip(), (row.get("BOMNUM") or "").strip())
        for row in bom_rows
        if (row.get("ITEM") or "").strip() and (row.get("LOC") or "").strip() and (row.get("BOMNUM") or "").strip()
    }

    method_bom_keys = {
        ((row.get("ITEM") or "").strip(), (row.get("LOC") or "").strip(), (row.get("BOMNUM") or "").strip())
        for row in prod_method_rows
        if (row.get("ITEM") or "").strip() and (row.get("LOC") or "").strip() and (row.get("BOMNUM") or "").strip()
    }

    method_keys = {
        ((row.get("ITEM") or "").strip(), (row.get("LOC") or "").strip(), (row.get("PRODUCTIONMETHOD") or "").strip())
        for row in prod_method_rows
        if (row.get("ITEM") or "").strip() and (row.get("LOC") or "").strip() and (row.get("PRODUCTIONMETHOD") or "").strip()
    }

    step_method_keys = {
        ((row.get("ITEM") or "").strip(), (row.get("LOC") or "").strip(), (row.get("PRODUCTIONMETHOD") or "").strip())
        for row in prod_step_rows
        if (row.get("ITEM") or "").strip() and (row.get("LOC") or "").strip() and (row.get("PRODUCTIONMETHOD") or "").strip()
    }

    missing_method_for_bom = sorted(list(bom_keys - method_bom_keys))
    missing_step_for_method = sorted(list(method_keys - step_method_keys))

    step_count_by_method: Dict[Tuple[str, str, str], set] = {}
    for row in prod_step_rows:
        item = (row.get("ITEM") or "").strip()
        loc = (row.get("LOC") or "").strip()
        method = (row.get("PRODUCTIONMETHOD") or "").strip()
        stepnum = (row.get("STEPNUM") or "").strip()
        if not item or not loc or not method:
            continue
        key = (item, loc, method)
        if key not in step_count_by_method:
            step_count_by_method[key] = set()
        if stepnum:
            step_count_by_method[key].add(stepnum)

    step_count_rows = [
        {
            "ITEM": key[0],
            "LOC": key[1],
            "PRODUCTIONMETHOD": key[2],
            "STEP_COUNT": len(stepnums),
        }
        for key, stepnums in step_count_by_method.items()
    ]
    step_count_rows = sorted(step_count_rows, key=lambda r: (r["ITEM"], r["LOC"], r["PRODUCTIONMETHOD"]))
    step_counts = [row["STEP_COUNT"] for row in step_count_rows]

    res_keys = {
        ((row.get("RES") or "").strip(), (row.get("LOC") or "").strip())
        for row in res_rows
        if (row.get("RES") or "").strip() and (row.get("LOC") or "").strip()
    }
    res_names = {(row.get("RES") or "").strip() for row in res_rows if (row.get("RES") or "").strip()}

    invalid_step_res_loc = []
    invalid_step_res_only = []
    for row in prod_step_rows:
        item = (row.get("ITEM") or "").strip()
        loc = (row.get("LOC") or "").strip()
        method = (row.get("PRODUCTIONMETHOD") or "").strip()
        step = (row.get("STEPNUM") or "").strip()
        res = (row.get("RES") or "").strip()
        if not res:
            continue
        if (res, loc) not in res_keys:
            invalid_step_res_loc.append({"ITEM": item, "LOC": loc, "PRODUCTIONMETHOD": method, "STEPNUM": step, "RES": res})
        if res not in res_names:
            invalid_step_res_only.append({"ITEM": item, "LOC": loc, "PRODUCTIONMETHOD": method, "STEPNUM": step, "RES": res})

    checks = {
        "bom_triplets_total": len(bom_keys),
        "method_bom_triplets_total": len(method_bom_keys),
        "method_records_total": len(method_keys),
        "method_with_steps_total": len(step_method_keys),
        "bom_without_production_method_count": len(missing_method_for_bom),
        "production_method_without_steps_count": len(missing_step_for_method),
        "invalid_step_res_loc_links_count": len(invalid_step_res_loc),
        "invalid_step_res_name_count": len(invalid_step_res_only),
        "step_count_methods_total": len(step_count_rows),
        "step_count_min": min(step_counts) if step_counts else 0,
        "step_count_max": max(step_counts) if step_counts else 0,
        "step_count_avg": round((sum(step_counts) / len(step_counts)), 2) if step_counts else 0,
    }

    critical = []
    high = []
    medium = []
    low = []

    if missing_required:
        critical.append(f"Missing required route datasets: {', '.join(missing_required)}")
    if checks["bom_without_production_method_count"] > 0:
        high.append(f"bom_without_production_method_count: {checks['bom_without_production_method_count']}")
    if checks["production_method_without_steps_count"] > 0:
        high.append(f"production_method_without_steps_count: {checks['production_method_without_steps_count']}")
    if checks["invalid_step_res_loc_links_count"] > 0:
        high.append(f"invalid_step_res_loc_links_count: {checks['invalid_step_res_loc_links_count']}")
    if checks["invalid_step_res_name_count"] > 0:
        medium.append(f"invalid_step_res_name_count: {checks['invalid_step_res_name_count']}")
    if checks["step_count_methods_total"] == 0 and not critical:
        medium.append("No production methods with step counts were found.")

    verdict = "Pass"
    if critical:
        verdict = "Fail"
    elif high:
        verdict = "Conditional Pass"

    return {
        "Validation Scope": {
            "week_id": context.get("week_id"),
            "scenario_id": context.get("scenario_id"),
            "scope": scope,
            "focus_areas": ["production_route"],
            "source": "by_input",
        },
        "Datasets and Evidence Used": {
            "source_priority": ["by_input", "Snowflake fallback"],
            "files": {
                "if_snop_billofmaterials": bom_file.name if bom_file else None,
                "if_snop_productionmethod": prod_method_file.name if prod_method_file else None,
                "if_snop_productionstep": prod_step_file.name if prod_step_file else None,
                "if_snop_res": res_file.name if res_file else None,
            },
            "missing_required_prefixes": missing_required,
            "context_resolution": context,
        },
        "Checks Executed": checks,
        "Issues Found (Critical, High, Medium, Low)": {
            "Critical": critical,
            "High": high,
            "Medium": medium,
            "Low": low,
        },
        "Route Coverage Details": {
            "sample_bom_without_production_method": [
                {"ITEM": item, "LOC": loc, "BOMNUM": bomnum} for (item, loc, bomnum) in missing_method_for_bom[:50]
            ],
            "sample_production_method_without_steps": [
                {"ITEM": item, "LOC": loc, "PRODUCTIONMETHOD": method} for (item, loc, method) in missing_step_for_method[:50]
            ],
            "sample_invalid_step_res_loc_links": invalid_step_res_loc[:50],
            "sample_invalid_step_res_name": invalid_step_res_only[:50],
            "step_count_by_method_sample": step_count_rows[:200],
        },
        "Readiness Verdict (Pass, Conditional Pass, Fail)": verdict,
        "Recommended Fixes (ordered by impact)": [
            "Create production methods for all BOM triplets (ITEM, LOC, BOMNUM) missing routing definitions.",
            "Create production steps for each production method where step coverage is missing.",
            "Fix production step RES assignments so RES and LOC align with if_snop_res.",
            "Re-run Production Route Check after route master updates.",
        ],
        "Confidence and Data Gaps": {
            "confidence": "High" if not critical else "Medium",
            "data_gaps": [
                "Week/Scenario filters apply only when these columns exist in by_input tables.",
                "Snowflake parity checks can be enabled later using identical output schema.",
            ],
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


def run_root_cause(
    base_dir: Path,
    week_id: Optional[str],
    scenario_id: Optional[str],
    demand_id: Optional[str],
    scope: Dict,
    demand_entity: Optional[Dict] = None,
) -> Dict:
    context = _resolve_context(base_dir, week_id, scenario_id)
    week_id = context["week_id"]
    scenario_id = context["scenario_id"]
    domain_entity = _parse_demand_entity(demand_id, demand_entity)

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
    resexception_file = _find_file_by_prefix(output_dir, "by_if_snop_out_resexception-")
    resloaddetail_file = _find_file_by_prefix(output_dir, "by_if_snop_out_resloaddetail-")

    items_file = _find_file_by_prefix(input_dir, "if_snop_items-")
    sku_file = _find_file_by_prefix(input_dir, "if_snop_sku-")
    bom_file = _find_file_by_prefix(input_dir, "if_snop_billofmaterials-")
    alt_bom_file = _find_file_by_prefix(input_dir, "if_snop_altbillofmaterials-")
    sourcing_file = _find_file_by_prefix(input_dir, "if_snop_sourcing-")
    productionmethod_file = _find_file_by_prefix(input_dir, "if_snop_productionmethod-")

    dfu_fcst_file = _find_file_by_prefix(input_dir, "if_snop_dfutoskufcst-")
    site = (scope.get("site") or "").strip()
    domain_entity = _resolve_entity_to_item(inddmdview_file, domain_entity, week_id, scenario_id, site)
    demand_item = (domain_entity.resolved_item or "").strip()

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

    item_profile: Dict[str, Optional[str]] = {}
    sku_rows = []
    bom_parent_rows = []
    bom_component_rows = []
    alt_bom_rows = []
    sourcing_out_rows = []
    sourcing_in_rows = []
    production_rows = []
    resload_rows = []
    resexception_rows = []

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

    if items_file and demand_item:
        for row in _safe_rows(items_file):
            if (row.get("ITEM") or "").strip() == demand_item:
                item_profile = {
                    "descr": (row.get("DESCR") or "").strip() or None,
                    "itemclass": (row.get("ITEMCLASS") or "").strip() or None,
                    "uom": (row.get("U_UOM") or "").strip() or None,
                    "status": (row.get("U_STATUS") or "").strip() or None,
                    "material_type": (row.get("U_MAT_TYPE_CD") or "").strip() or None,
                    "capacity_group": (row.get("U_CAPACITY_GROUP") or "").strip() or None,
                    "capacity_corridor": (row.get("U_CAPACITY_CORRIDOR") or "").strip() or None,
                    "process_node": (row.get("U_PROCESSNODEUPPERCASE_TXT") or "").strip() or None,
                    "mfg_stage": (row.get("U_MFG_STAGE") or "").strip() or None,
                }
                break

    if sku_file and demand_item:
        for row in _safe_rows(sku_file):
            if (row.get("ITEM") or "").strip() != demand_item:
                continue
            if site and (row.get("LOC") or "").strip() != site:
                continue
            sku_rows.append(row)

    if bom_file and demand_item:
        for row in _safe_rows(bom_file):
            item = (row.get("ITEM") or "").strip()
            subord = (row.get("SUBORD") or "").strip()
            loc = (row.get("LOC") or "").strip()
            if site and loc != site:
                continue
            if item == demand_item:
                bom_parent_rows.append(row)
            if subord == demand_item:
                bom_component_rows.append(row)

    if alt_bom_file and demand_item:
        for row in _safe_rows(alt_bom_file):
            item = (row.get("ITEM") or "").strip()
            subord = (row.get("SUBORD") or "").strip()
            loc = (row.get("LOC") or "").strip()
            if site and loc != site:
                continue
            if item == demand_item or subord == demand_item:
                alt_bom_rows.append(row)

    if sourcing_file and demand_item:
        for row in _safe_rows(sourcing_file):
            if (row.get("ITEM") or "").strip() != demand_item:
                continue
            source = (row.get("SOURCE") or "").strip()
            dest = (row.get("DEST") or "").strip()
            if site and site not in {source, dest}:
                continue
            if not site or source == site:
                sourcing_out_rows.append(row)
            if not site or dest == site:
                sourcing_in_rows.append(row)

    if productionmethod_file and demand_item:
        for row in _safe_rows(productionmethod_file):
            if (row.get("ITEM") or "").strip() != demand_item:
                continue
            loc = (row.get("LOC") or "").strip()
            if site and loc != site:
                continue
            production_rows.append(row)

    if resloaddetail_file and demand_item:
        for row in _safe_rows(resloaddetail_file):
            if (row.get("ITEM") or "").strip() != demand_item:
                continue
            if site and (row.get("LOC") or "").strip() != site:
                continue
            if not _matches_context(row, week_id, scenario_id):
                continue
            resload_rows.append(row)

    if resexception_file and demand_item:
        for row in _safe_rows(resexception_file):
            row_item = (row.get("ITEM") or "").strip()
            row_loc = (row.get("LOC") or "").strip()
            row_method = (row.get("PRODUCTIONMETHOD") or "").strip()
            if row_item != demand_item and not row_method.startswith(f"{demand_item}_"):
                continue
            if site and row_loc and row_loc != site:
                continue
            if not _matches_context(row, week_id, scenario_id):
                continue
            resexception_rows.append(row)

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

    lateness_days: List[float] = []
    for row in demand_rows:
        need_date = _parse_date(row.get("NEEDDATE"))
        sched_date = _parse_date(row.get("SCHEDDATE"))
        if need_date and sched_date and sched_date > need_date:
            lateness_days.append(float((sched_date - need_date).days))

    pegged_demand_qty = sum(_safe_float(row.get("DMDPEGQTY")) for row in link_rows)
    pegged_supply_qty = sum(_safe_float(row.get("SUPPLYPEGQTY")) for row in link_rows)
    supply_avail_dates = [_parse_date(row.get("SUPPLYAVAILDATE")) for row in link_rows]
    supply_avail_dates = [d for d in supply_avail_dates if d]

    supply_lead_deltas: List[float] = []
    for row in link_rows:
        dmd_need = _parse_date(row.get("DMDNEEDDATE"))
        supply_avail = _parse_date(row.get("SUPPLYAVAILDATE"))
        if dmd_need and supply_avail:
            supply_lead_deltas.append(float((supply_avail - dmd_need).days))

    supply_methods = sorted({(row.get("SUPPLYMETHOD") or "").strip() for row in link_rows if (row.get("SUPPLYMETHOD") or "").strip()})
    supply_types = sorted({(row.get("SUPPLYTYPE") or "").strip() for row in link_rows if (row.get("SUPPLYTYPE") or "").strip()})
    demand_types = sorted({(row.get("DMDTYPE") or "").strip() for row in demand_rows if (row.get("DMDTYPE") or "").strip()})

    demand_locs = sorted({(row.get("LOC") or "").strip() for row in demand_rows if (row.get("LOC") or "").strip()})
    demand_customers = sorted({(row.get("CUST") or "").strip() for row in demand_rows if (row.get("CUST") or "").strip()})
    demand_order_ids = sorted({(row.get("EXTORDERID") or "").strip() for row in demand_rows if (row.get("EXTORDERID") or "").strip()})
    demand_priorities = sorted({p for p in [_safe_int(row.get("PRIORITY")) for row in demand_rows] if p is not None})

    pegged_supply_by_item: Dict[Tuple[str, str], float] = {}
    genealogy_links = []
    for row in link_rows:
        s_item = (row.get("SUPPLYITEM") or "").strip()
        s_loc = (row.get("SUPPLYLOC") or "").strip()
        qty = _safe_float(row.get("SUPPLYPEGQTY"))
        if s_item:
            pegged_supply_by_item[(s_item, s_loc)] = pegged_supply_by_item.get((s_item, s_loc), 0.0) + qty
        parent_item = (row.get("PARENTITEM") or "").strip()
        parent_loc = (row.get("PARENTLOC") or "").strip()
        if parent_item:
            genealogy_links.append({
                "demand_item": (row.get("DMDITEM") or "").strip() or demand_item,
                "supply_item": s_item or None,
                "supply_loc": s_loc or None,
                "parent_item": parent_item,
                "parent_loc": parent_loc or None,
                "supply_method": (row.get("SUPPLYMETHOD") or "").strip() or None,
                "parent_supply_method": (row.get("PARENTSUPPLYMETHOD") or "").strip() or None,
                "pegged_supply_qty": round(qty, 3),
                "demand_need_date": _fmt_date(_parse_date(row.get("DMDNEEDDATE"))),
                "supply_avail_date": _fmt_date(_parse_date(row.get("SUPPLYAVAILDATE"))),
            })

    top_pegged_supply_items = sorted(
        [
            {
                "supply_item": k[0],
                "supply_loc": k[1] or None,
                "pegged_qty": round(v, 3),
            }
            for k, v in pegged_supply_by_item.items()
        ],
        key=lambda row: row["pegged_qty"],
        reverse=True,
    )[:10]

    capacity_exception_rows = []
    for row in resexception_rows:
        descr = (row.get("DESCR") or "").strip().lower()
        category = (row.get("CATEGORY") or "").strip()
        exception_code = (row.get("EXCEPTION") or "").strip()
        if "capacity" in descr or category == "602" or exception_code == "6801":
            capacity_exception_rows.append(row)

    capacity_exception_count = len(capacity_exception_rows)
    capacity_overutil_qty = sum(_safe_float(row.get("OVERUTILQTY")) for row in capacity_exception_rows)

    total_resload_qty = sum(_safe_float(row.get("LOADQTY")) for row in resload_rows)
    total_fcst_load_qty = sum(_safe_float(row.get("FCSTORDLOADQTY")) for row in resload_rows)
    total_cust_load_qty = sum(_safe_float(row.get("CUSTORDLOADQTY")) for row in resload_rows)
    unique_resources = sorted({(row.get("RES") or "").strip() for row in resload_rows if (row.get("RES") or "").strip()})

    competing_higher_priority_qty = 0.0
    competing_higher_priority_count = 0
    if inddmdview_file and demand_locs and demand_priorities:
        min_priority = min(demand_priorities)
        for row in _safe_rows(inddmdview_file):
            if (row.get("ITEM") or "").strip() == demand_item:
                continue
            if (row.get("LOC") or "").strip() not in demand_locs:
                continue
            if not _matches_context(row, week_id, scenario_id):
                continue
            p = _safe_int(row.get("PRIORITY"))
            if p is None or p >= min_priority:
                continue
            competing_higher_priority_count += 1
            competing_higher_priority_qty += _safe_float(row.get("QTY"))

    setup_flags = {
        "item_exists_in_master": bool(item_profile),
        "sku_coverage_exists": len(sku_rows) > 0,
        "production_method_exists": len(production_rows) > 0,
        "sourcing_path_exists": len(sourcing_out_rows) + len(sourcing_in_rows) > 0,
        "bom_parent_path_exists": len(bom_parent_rows) > 0,
        "bom_component_usage_exists": len(bom_component_rows) > 0,
    }

    fully_met = demand_qty_total > 0 and scheduled_qty_total + 1e-6 >= demand_qty_total
    if fully_met and late_sched_qty > 0:
        fulfillment_status = FulfillmentStatus.MET_LATE
    elif fully_met:
        fulfillment_status = FulfillmentStatus.MET
    elif scheduled_qty_total > 0:
        fulfillment_status = FulfillmentStatus.PARTIALLY_MET
    else:
        fulfillment_status = FulfillmentStatus.NOT_MET
    met_status = fulfillment_status.value
    met_date = max(sched_dates) if fully_met and sched_dates else None

    gaps = []
    if not week_id:
        gaps.append("no CAPTURE_WK found in available output datasets")
    if not scenario_id:
        gaps.append("no SIMULATION_NAME found in available output datasets")
    if not demand_item:
        gaps.append("demand entity could not be resolved to ITEM for lineage trace")
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
    if capacity_exception_count > 0:
        root_causes.append(f"Capacity exceptions found: {capacity_exception_count} row(s) with total overutilized quantity {capacity_overutil_qty:.3f}.")
    if not setup_flags["production_method_exists"] and not setup_flags["sourcing_path_exists"]:
        root_causes.append("No production method or sourcing path found for the demand item in the selected scope; master data setup may block supply creation.")
    if competing_higher_priority_count > 0:
        root_causes.append(
            f"Higher-priority competing demand detected in the same location context: {competing_higher_priority_count} row(s), quantity {competing_higher_priority_qty:.3f}."
        )
    if not root_causes:
        root_causes.append("Demand appears covered by scheduled and pegged supply in the current dataset scope.")

    attribution_signals = ConstraintAttributionPolicy.evaluate(
        unmet_qty,
        late_sched_qty,
        pegged_demand_qty,
        pegged_supply_qty,
        setup_flags,
        capacity_exception_count,
        resource_link_rows,
        competing_higher_priority_count,
        demand_qty_total,
        scheduled_qty_total,
    )

    ranked_attribution = sorted(attribution_signals.items(), key=lambda kv: kv[1], reverse=True)
    primary_causes = [name for name, score in ranked_attribution if score > 0]
    if not primary_causes:
        primary_causes = ["no_material_constraint_detected_in_current_scope"]

    by_esp_reasoning = []
    if attribution_signals["master_data_setup_risk"] > 0:
        by_esp_reasoning.append("Input setup risk: missing SKU/production/sourcing paths can prevent BY ESP from creating feasible supply.")
    if attribution_signals["capacity_constraint_risk"] > 0:
        by_esp_reasoning.append("Capacity risk: resource-load linkage and capacity exceptions indicate finite-capacity bottlenecks.")
    if attribution_signals["priority_allocation_risk"] > 0:
        by_esp_reasoning.append("Priority risk: higher-priority competing demand in the same location can consume constrained supply first.")
    if attribution_signals["supply_shortage_risk"] > 0:
        by_esp_reasoning.append("Supply shortage risk: scheduled and planned supply quantities remain below demand requirement.")
    if attribution_signals["pegging_mismatch_risk"] > 0:
        by_esp_reasoning.append("Pegging mismatch risk: demand pegging exceeds pegged supply, indicating unresolved linkage.")

    evidence_grade = _grade_evidence(demand_qty_total, len(link_rows), gaps)
    domain_focus_assessment = _build_domain_focus_assessment(
        demand_qty_total,
        scheduled_qty_total,
        unmet_qty,
        on_time_sched_qty,
        late_sched_qty,
        lateness_days,
        _stddev(supply_lead_deltas),
        capacity_exception_count,
        capacity_overutil_qty,
        competing_higher_priority_count,
        setup_flags,
        bom_parent_rows,
        bom_component_rows,
        production_rows,
        sourcing_out_rows,
        sourcing_in_rows,
        evidence_grade,
    )

    return {
        "Explainability Scope": {
            "week_id": week_id,
            "scenario_id": scenario_id,
            "week_column": "CAPTURE_WK",
            "scenario_column": "SIMULATION_NAME",
            "demand_entity": domain_entity.to_dict(),
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
        "Item Master and Planning Setup": {
            "item_profile": item_profile,
            "demand_locations": demand_locs,
            "demand_customers": demand_customers[:20],
            "demand_types_seen": demand_types,
            "demand_priorities_seen": demand_priorities,
            "sku_rows_for_item": len(sku_rows),
            "sku_locations": sorted({(row.get("LOC") or "").strip() for row in sku_rows if (row.get("LOC") or "").strip()})[:20],
            "sourcing_out_paths": len(sourcing_out_rows),
            "sourcing_in_paths": len(sourcing_in_rows),
            "production_method_rows": len(production_rows),
            "production_methods": sorted({(row.get("PRODUCTIONMETHOD") or "").strip() for row in production_rows if (row.get("PRODUCTIONMETHOD") or "").strip()})[:20],
            "bom_parent_rows": len(bom_parent_rows),
            "bom_component_rows": len(bom_component_rows),
            "alt_bom_rows": len(alt_bom_rows),
            "setup_flags": setup_flags,
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
            "fulfillment_status": fulfillment_status.value,
            "fully_met_date": _fmt_date(met_date),
        },
        "Lineage and Linkage Findings": {
            "inddmdlink_rows": len(link_rows),
            "resource_link_rows": resource_link_rows,
            "pegged_demand_qty": round(pegged_demand_qty, 3),
            "pegged_supply_qty": round(pegged_supply_qty, 3),
            "first_supply_avail_date": _fmt_date(min(supply_avail_dates) if supply_avail_dates else None),
            "last_supply_avail_date": _fmt_date(max(supply_avail_dates) if supply_avail_dates else None),
            "demand_order_count": len(demand_order_ids),
            "demand_orders_sample": demand_order_ids[:20],
            "supply_types_seen": supply_types,
            "supply_methods_seen": supply_methods[:10],
            "top_pegged_supply_items": top_pegged_supply_items,
            "genealogy_paths_sample": genealogy_links[:25],
        },
        "Planned Supply Evidence": {
            "plan_arrival_qty": round(plan_arriv_qty, 3),
            "plan_order_qty": round(plan_order_qty, 3),
            "plan_purchase_qty": round(plan_purch_qty, 3),
            "plan_arrival_first_date": _fmt_date(min(plan_arriv_dates) if plan_arriv_dates else None),
            "plan_order_first_date": _fmt_date(min(plan_order_dates) if plan_order_dates else None),
            "plan_purchase_first_date": _fmt_date(min(plan_purch_dates) if plan_purch_dates else None),
        },
        "Constraint and Exception Analysis": {
            "sku_exception_rows_for_item": exception_item_rows,
            "resource_load_rows_for_item": len(resload_rows),
            "resource_count": len(unique_resources),
            "resources_sample": unique_resources[:20],
            "total_resource_load_qty": round(total_resload_qty, 3),
            "customer_order_load_qty": round(total_cust_load_qty, 3),
            "forecast_order_load_qty": round(total_fcst_load_qty, 3),
            "capacity_exception_rows": capacity_exception_count,
            "capacity_overutil_qty": round(capacity_overutil_qty, 3),
            "higher_priority_competing_rows": competing_higher_priority_count,
            "higher_priority_competing_qty": round(competing_higher_priority_qty, 3),
        },
        "Domain Focus Assessment": domain_focus_assessment,
        "Confirmed Findings": confirmed_findings,
        "Root Causes": root_causes,
        "Cause Attribution (BY ESP Expert View)": {
            "primary_cause_tags": primary_causes,
            "attribution_signals": attribution_signals,
            "policy": "ConstraintAttributionPolicy.v1",
            "by_esp_reasoning": by_esp_reasoning,
            "semiconductor_planning_notes": [
                "In semiconductor planning, constrained resources and long-cycle production routes can shift fulfillment across weeks.",
                "Item setup quality (SKU, BOM, sourcing, production method) directly impacts BY ESP solvability and pegging quality.",
            ],
        },
        "Hypotheses and Missing Evidence": {
            "hypotheses": [
                "Unmet demand likely links to capacity, sourcing, or BOM constraints where exception density is high.",
            ],
            "missing_evidence": gaps,
        },
        "Confidence Level": evidence_grade.value,
        "Recommended Next Checks": [
            "Provide demand ITEM and scope for targeted lineage trace.",
            "Compare demand need dates with supply available and scheduled dates for lateness diagnosis.",
            "Join exception, demand-link, and resource-link outputs with capacity and sourcing inputs for final constraint attribution.",
        ],
    }


# ---------------------------------------------------------------------------
# Root Cause — LLM-enhanced explained analysis
# ---------------------------------------------------------------------------

RC_QUESTION_FOCUS: Dict[str, str] = {
    "full_diagnosis": (
        "Provide a comprehensive demand-supply diagnosis: fulfillment status, quantity analysis, "
        "lateness, root causes, constraint attribution, and planning setup quality."
    ),
    "why_unmet": (
        "Explain specifically WHY demand was not fully met. Focus on: unmet quantity, "
        "supply shortage signals, missing BOM/sourcing/production setup, capacity exceptions, "
        "pegging gaps, and competing demand."
    ),
    "why_late": (
        "Explain WHY demand fulfillment was late. Focus on: late scheduled quantity, "
        "supply availability vs need dates, lead time issues, resource constraints delaying supply."
    ),
    "why_short": (
        "Explain WHY demand quantity was short (scheduled < demanded). Focus on: the quantity gap, "
        "supply pegging shortfall, capacity overutilization, competing higher-priority demand."
    ),
    "why_early": (
        "Explain WHY demand was fulfilled earlier than need date. Analyze: on-time vs early qty, "
        "supply availability dates vs need dates, and inventory build-up implications."
    ),
    "capacity_constraints": (
        "Detail the resource and capacity constraints. Focus on: capacity exceptions, overutilized "
        "quantities, resources affected, resource load by order type (forecast vs customer)."
    ),
    "bom_sourcing_gaps": (
        "Analyze BOM and sourcing master data quality. Focus on: production methods, BOM paths, "
        "sourcing routes, SKU setup; gaps that block BY ESP from creating feasible supply."
    ),
    "priority_conflict": (
        "Analyze priority conflicts. Focus on: higher-priority competing demand in the same "
        "location, quantity they consume, and impact on this item's fulfillment."
    ),
    "supply_pegging": (
        "Trace the full supply pegging and lineage chain. Focus on: pegged supply items, "
        "supply methods, genealogy paths, planned arrivals/orders/purchases, supply timeline."
    ),
    "eoh": (
        "Analyze end-of-horizon (EOH) inventory position. Focus on: planned arrival, "
        "planned orders, planned purchases, supply timeline, and projected closing stock."
    ),
}

_RC_QUESTION_LABELS: Dict[str, str] = {
    "full_diagnosis":       "Full Demand-Supply Diagnosis",
    "why_unmet":            "Why is demand unmet?",
    "why_late":             "Why did demand get late?",
    "why_short":            "Why did demand get short?",
    "why_early":            "Why was demand met early?",
    "capacity_constraints": "Resource / Capacity Constraints",
    "bom_sourcing_gaps":    "BOM and Sourcing Gaps",
    "priority_conflict":    "Priority Conflict Impact",
    "supply_pegging":       "Supply Pegging & Lineage",
    "eoh":                  "End-of-Horizon Inventory",
}


def _build_fallback_rc_narrative(stats: Dict, root_causes: List[str], findings: List[str]) -> str:
    item = stats.get("item") or "N/A"
    lines = [
        "### Executive Summary",
        f"Item **{item}** | Week **{stats.get('week', 'N/A')}** | Scenario **{stats.get('scenario', 'N/A')}**  ",
        f"Fulfillment status: **{stats.get('meet_status', 'unknown')}** | Fill rate: **{stats.get('fill_rate_pct', 0.0):.1f}%**",
        "",
        "### Key Statistics",
        f"- Demand Qty: **{stats.get('demand_qty', 0):.3f}**",
        f"- Scheduled Qty: **{stats.get('scheduled_qty', 0):.3f}**",
        f"- Unmet Qty: **{stats.get('unmet_qty', 0):.3f}**",
        f"- On-Time Qty: **{stats.get('on_time_qty', 0):.3f}**",
        f"- Late Qty: **{stats.get('late_qty', 0):.3f}**",
        f"- Capacity Exceptions: **{stats.get('capacity_exceptions', 0)}**",
        f"- Resources Affected: **{stats.get('resources_affected', 0)}**",
        "",
        "### Confirmed Root Causes",
    ]
    for i, cause in enumerate(root_causes or ["No explicit root causes identified."], 1):
        lines.append(f"{i}. {cause}")
    lines += ["", "### Confirmed Findings"]
    for finding in findings or []:
        lines.append(f"- {finding}")
    lines += ["", "### Note", "LLM narrative unavailable — showing structured evidence summary."]
    return "\n".join(lines)


def _compute_rc_deep_evidence(
    base_dir: Path,
    demand_item: str,
    week_id: Optional[str],
    scenario_id: Optional[str],
    site: Optional[str],
) -> Dict:
    """
    Data-computation layer — queries CSV files directly and computes all the
    specific facts (lateness distribution, period gaps, supply parameters,
    resource bottlenecks, EOH, fence dates, lot-size impact) that the LLM
    needs to produce a grounded narrative rather than generic descriptions.
    """
    from collections import defaultdict

    input_dir  = base_dir / INPUT_FOLDER
    output_dir = base_dir / OUTPUT_FOLDER

    evidence: Dict = {}

    # ── 1. DEMAND: per-row lateness & period demand bucket ────────────────
    dmd_file = _find_file_by_prefix(output_dir, "by_if_snop_out_inddmdview-")
    late_days_list: List[float] = []
    early_days_list: List[float] = []
    period_demand: Dict[str, float]  = defaultdict(float)   # "YYYY-MM" → demand qty
    period_sched: Dict[str, float]   = defaultdict(float)   # "YYYY-MM" → sched qty
    unmet_orders: List[Dict] = []
    if dmd_file:
        for row in _safe_rows(dmd_file):
            if (row.get("ITEM") or "").strip() != demand_item:
                continue
            if site and (row.get("LOC") or "").strip() != site:
                continue
            if not _matches_context(row, week_id, scenario_id):
                continue
            nd = _parse_date(row.get("NEEDDATE"))
            sd = _parse_date(row.get("SCHEDDATE"))
            dq = _safe_float(row.get("QTY"))
            sq = _safe_float(row.get("SCHEDQTY"))
            if nd:
                period_demand[nd.strftime("%Y-%m")] += dq
            if nd and sd and sq > 0:
                delta = (sd - nd).days
                if delta > 0:
                    late_days_list.append(delta)
                elif delta < 0:
                    early_days_list.append(-delta)
            if nd:
                period_sched[nd.strftime("%Y-%m")] += sq
            # flag unmet orders (non-zero demand, zero sched)
            if dq > 0 and sq == 0:
                unmet_orders.append({
                    "order": (row.get("EXTORDERID") or "").strip() or None,
                    "need_date": _fmt_date(nd),
                    "qty": dq,
                    "loc": (row.get("LOC") or "").strip(),
                })

    # Period balance table (sorted by month)
    period_balance = []
    all_periods = sorted(set(list(period_demand.keys()) + list(period_sched.keys())))
    for p in all_periods:
        dq = period_demand.get(p, 0.0)
        sq = period_sched.get(p, 0.0)
        period_balance.append({
            "period": p,
            "demand_qty": round(dq, 1),
            "sched_qty":  round(sq, 1),
            "gap":        round(dq - sq, 1),
            "fill_pct":   round(sq / dq * 100, 1) if dq > 0 else None,
        })

    lateness = {}
    if late_days_list:
        late_days_list.sort()
        lateness = {
            "late_rows": len(late_days_list),
            "avg_days": round(sum(late_days_list) / len(late_days_list), 1),
            "max_days": int(max(late_days_list)),
            "median_days": int(late_days_list[len(late_days_list) // 2]),
            "gt_30_days": sum(1 for d in late_days_list if d > 30),
            "gt_60_days": sum(1 for d in late_days_list if d > 60),
        }
    early = {}
    if early_days_list:
        early = {
            "early_rows": len(early_days_list),
            "avg_days": round(sum(early_days_list) / len(early_days_list), 1),
            "max_days": int(max(early_days_list)),
        }

    evidence["lateness_analysis"]  = lateness
    evidence["early_analysis"]     = early
    evidence["period_balance"]     = period_balance[:24]  # cap at 24 months
    evidence["unmet_orders_sample"] = sorted(unmet_orders, key=lambda x: x.get("need_date") or "")[:10]

    # ── 2. SUPPLY PARAMETERS from input master data ───────────────────────
    prod_params: List[Dict] = []
    prod_file = _find_file_by_prefix(input_dir, "if_snop_productionmethod-")
    if prod_file:
        for row in _safe_rows(prod_file):
            if (row.get("ITEM") or "").strip() != demand_item:
                continue
            if site and (row.get("LOC") or "").strip() != site:
                continue
            lead_min = _safe_float(row.get("LEADTIME"))
            lead_days = round(lead_min / 1440, 1) if lead_min > 0 else None  # 1440 min/day
            prod_params.append({
                "loc":            (row.get("LOC") or "").strip(),
                "method":         (row.get("PRODUCTIONMETHOD") or "").strip(),
                "leadtime_min":   int(lead_min) if lead_min else None,
                "leadtime_days":  lead_days,
                "incqty":         _safe_float(row.get("INCQTY")),
                "nonewsupply_date": (row.get("NONEWSUPPLYDATE") or "").strip() or None,
                "priority":       (row.get("PRIORITY") or "").strip() or None,
            })

    sku_params: List[Dict] = []
    sku_file = _find_file_by_prefix(input_dir, "if_snop_sku-")
    if sku_file:
        for row in _safe_rows(sku_file):
            if (row.get("ITEM") or "").strip() != demand_item:
                continue
            if site and (row.get("LOC") or "").strip() != site:
                continue
            sku_params.append({
                "loc":                (row.get("LOC") or "").strip(),
                "order_leadtime_days": _safe_float(row.get("U_ORDER_LEADTIME")) or None,
                "allocation_horizon_days": _safe_float(row.get("U_ALLOCATION_HORIZON")) or None,
                "rsp_horizon_days":   _safe_float(row.get("U_RSP_HORIZON")) or None,
                "infinite_supply":    (row.get("INFINITESUPPLYSW") or "").strip(),
                "enable_opt":         (row.get("ENABLEOPT") or "").strip(),
                "ss_rule":            (row.get("SSRULE") or "").strip() or None,
            })

    evidence["production_parameters"] = prod_params
    evidence["sku_parameters"]         = sku_params

    # Interpret fence dates and lot-size impact
    fence_signals: List[str] = []
    for p in prod_params:
        fence = p.get("nonewsupply_date")
        if fence:
            fence_signals.append(
                f"Production method {p['method']} at loc {p['loc']} has NONEWSUPPLYDATE={fence} "
                f"(no new supply orders before this date). "
                f"Lead time: {p['leadtime_days']} days, lot size: {p['incqty']}."
            )
    for s in sku_params:
        lt = s.get("order_leadtime_days")
        if lt and lt > 30:
            fence_signals.append(
                f"SKU at loc {s['loc']} has ORDER_LEADTIME={lt} days — "
                f"orders placed today arrive in ~{int(lt)} days."
            )
    evidence["supply_constraint_signals"] = fence_signals

    # ── 3. SKUPROJSTATIC: EOH and coverage by period ──────────────────────
    eoh_data: List[Dict] = []
    proj_file = _find_file_by_prefix(output_dir, "by_if_snop_out_skuprojstatic-")
    if proj_file:
        for row in _safe_rows(proj_file):
            if (row.get("ITEM") or "").strip() != demand_item:
                continue
            if site and (row.get("LOC") or "").strip() != site:
                continue
            if not _matches_context(row, week_id, scenario_id):
                continue
            eoh_data.append({
                "loc":       (row.get("LOC") or "").strip(),
                "date":      (row.get("STARTDATE") or "").strip(),
                "covdur":    (row.get("COVDUR") or "").strip() or None,
                "all_dmd":   (row.get("ALLDMD") or "").strip() or None,
                "eoh_qty":   (row.get("EOHPROJQTY") or row.get("EOHAVAIL") or "").strip() or None,
                "planonhand":(row.get("PLANONHAND") or "").strip() or None,
                "met_dmd":   (row.get("METDMDQTY") or "").strip() or None,
                "unmet_dmd": (row.get("UNMETDMDQTY") or "").strip() or None,
            })
    evidence["eoh_projection"] = eoh_data[:20]

    # ── 4. RESOURCE BOTTLENECK: top resources by load qty for this item ───
    res_load: Dict[str, float] = defaultdict(float)
    res_cust: Dict[str, float] = defaultdict(float)
    res_fcst: Dict[str, float] = defaultdict(float)
    res_file = _find_file_by_prefix(output_dir, "by_if_snop_out_resloaddetail-")
    if res_file:
        for row in _safe_rows(res_file):
            if (row.get("ITEM") or "").strip() != demand_item:
                continue
            if not _matches_context(row, week_id, scenario_id):
                continue
            res = (row.get("RES") or "").strip()
            if res:
                res_load[res] += _safe_float(row.get("LOADQTY"))
                res_cust[res] += _safe_float(row.get("CUSTORDLOADQTY"))
                res_fcst[res] += _safe_float(row.get("FCSTORDLOADQTY"))

    top_resources = sorted(
        [{"resource": r, "total_load": round(res_load[r], 1),
          "customer_load": round(res_cust[r], 1),
          "forecast_load": round(res_fcst[r], 1)}
         for r in res_load],
        key=lambda x: x["total_load"], reverse=True
    )[:10]
    evidence["top_resource_loads"] = top_resources

    # ── 5. COMPETING DEMAND: top competing items by priority ──────────────
    competing: Dict[str, Dict] = {}
    if dmd_file and period_demand:
        # only look at locs where our item has demand
        demand_locs_set = set()
        for row in _safe_rows(dmd_file):
            if (row.get("ITEM") or "").strip() == demand_item and _matches_context(row, week_id, scenario_id):
                demand_locs_set.add((row.get("LOC") or "").strip())

        # collect items with higher priority (lower number) in same locs
        our_priorities: List[int] = []
        for row in _safe_rows(dmd_file):
            if (row.get("ITEM") or "").strip() == demand_item and _matches_context(row, week_id, scenario_id):
                p = _safe_int(row.get("CALCPRIORITY") or row.get("PRIORITY"))
                if p is not None:
                    our_priorities.append(p)
        min_our_priority = min(our_priorities) if our_priorities else 9999

        for row in _safe_rows(dmd_file):
            if (row.get("ITEM") or "").strip() == demand_item:
                continue
            loc = (row.get("LOC") or "").strip()
            if loc not in demand_locs_set:
                continue
            if not _matches_context(row, week_id, scenario_id):
                continue
            p = _safe_int(row.get("CALCPRIORITY") or row.get("PRIORITY"))
            if p is None or p >= min_our_priority:
                continue
            comp_item = (row.get("ITEM") or "").strip()
            if comp_item not in competing:
                competing[comp_item] = {"item": comp_item, "priority": p, "qty": 0.0, "rows": 0}
            competing[comp_item]["qty"] += _safe_float(row.get("QTY"))
            competing[comp_item]["rows"] += 1

    top_competing = sorted(competing.values(), key=lambda x: x["qty"], reverse=True)[:8]
    for c in top_competing:
        c["qty"] = round(c["qty"], 1)
    evidence["competing_demand_detail"] = top_competing

    # ── 6. EXCEPTION DETAIL ───────────────────────────────────────────────
    exc_detail: List[Dict] = []
    exc_file = _find_file_by_prefix(output_dir, "by_if_snop_out_skuexception-")
    if exc_file:
        for row in _safe_rows(exc_file):
            if (row.get("ITEM") or "").strip() != demand_item:
                continue
            if not _matches_context(row, week_id, scenario_id):
                continue
            exc_detail.append({
                "exception": (row.get("EXCEPTION") or "").strip(),
                "descr":     (row.get("DESCR") or "").strip(),
                "loc":       (row.get("LOC") or "").strip(),
                "when":      (row.get("WHEN") or "").strip() or None,
                "demand_qty":(row.get("DEMANDQTY") or "").strip() or None,
            })
    evidence["exception_detail"] = exc_detail

    return evidence


def run_root_cause_explained(
    base_dir: Path,
    week_id: Optional[str],
    scenario_id: Optional[str],
    demand_id: Optional[str],
    scope: Dict,
    question_type: str = "full_diagnosis",
    llm_model: Optional[str] = None,
    demand_entity: Optional[Dict] = None,
) -> Dict:
    """
    Enhanced root cause analysis with a data-computation layer.

    Flow:
      1. run_root_cause()         — structural demand/supply/lineage evidence
      2. _compute_rc_deep_evidence() — data-analyst layer: period gaps,
                                       lateness stats, lead-time fences,
                                       lot-size impact, resource bottlenecks,
                                       EOH, competing demand details
      3. LLM narrative             — told to cite ONLY the pre-computed facts
    """
    raw = run_root_cause(base_dir, week_id, scenario_id, demand_id, scope, demand_entity=demand_entity)

    scope_info  = raw.get("Explainability Scope", {})
    ds          = raw.get("Demand and Supply Summary", {})
    constraint  = raw.get("Constraint and Exception Analysis", {})
    lineage     = raw.get("Lineage and Linkage Findings", {})
    planned     = raw.get("Planned Supply Evidence", {})
    item_setup  = raw.get("Item Master and Planning Setup", {})

    demand_item  = scope_info.get("demand_item") or ""
    resolved_week = scope_info.get("week_id")
    resolved_scen = scope_info.get("scenario_id")
    site          = (scope or {}).get("node") or (scope or {}).get("site") or ""

    demand_qty = float(ds.get("demand_qty_total") or 0)
    sched_qty  = float(ds.get("scheduled_qty_total") or 0)
    fill_rate  = round(sched_qty / demand_qty * 100, 1) if demand_qty > 0 else 0.0

    stats: Dict = {
        "item":             demand_item or None,
        "week":             resolved_week,
        "scenario":         resolved_scen,
        "meet_status":      ds.get("meet_status", "unknown"),
        "demand_qty":       demand_qty,
        "scheduled_qty":    sched_qty,
        "unmet_qty":        float(ds.get("unmet_qty") or 0),
        "fill_rate_pct":    fill_rate,
        "on_time_qty":      float(ds.get("on_time_scheduled_qty") or 0),
        "late_qty":         float(ds.get("late_scheduled_qty") or 0),
        "first_need_date":  ds.get("first_need_date"),
        "last_need_date":   ds.get("last_need_date"),
        "first_sched_date": ds.get("first_sched_date"),
        "last_sched_date":  ds.get("last_sched_date"),
        "plan_arrival_qty": float(planned.get("plan_arrival_qty") or 0),
        "plan_order_qty":   float(planned.get("plan_order_qty") or 0),
        "plan_purchase_qty":float(planned.get("plan_purchase_qty") or 0),
        "pegged_supply_qty":float(lineage.get("pegged_supply_qty") or 0),
        "capacity_exceptions":   int(constraint.get("capacity_exception_rows") or 0),
        "resources_affected":    int(constraint.get("resource_count") or 0),
        "sku_exceptions":        int(constraint.get("sku_exception_rows_for_item") or 0),
        "competing_demand_rows": int(constraint.get("higher_priority_competing_rows") or 0),
        "competing_demand_qty":  float(constraint.get("higher_priority_competing_qty") or 0),
    }

    # ── Data analyst layer: compute specific facts from CSV data ──────────
    deep: Dict = {}
    if demand_item:
        try:
            deep = _compute_rc_deep_evidence(
                base_dir, demand_item, resolved_week, resolved_scen,
                site or None,
            )
            # Backfill lateness stats into the stats card
            lat = deep.get("lateness_analysis") or {}
            if lat:
                stats["avg_lateness_days"] = lat.get("avg_days")
                stats["max_lateness_days"] = lat.get("max_days")
        except Exception:
            pass

    focus = RC_QUESTION_FOCUS.get(question_type, RC_QUESTION_FOCUS["full_diagnosis"])

    # ── Build a compact, pre-formatted evidence brief for the LLM ────────
    # Converting to readable text (not raw JSON) stays well within the model's
    # context window and gives the LLM much clearer signals to cite.

    def _fmt(v, decimals=1):
        if v is None: return "N/A"
        if isinstance(v, float): return f"{v:.{decimals}f}"
        return str(v)

    # Period balance as a mini markdown table (worst 8 periods only)
    pb = deep.get("period_balance", [])
    worst = sorted(pb, key=lambda r: r.get("gap", 0), reverse=True)[:8]
    period_table_lines = ["| Period | Demand | Scheduled | Gap | Fill% |",
                          "|--------|--------|-----------|-----|-------|"]
    for r in worst:
        period_table_lines.append(
            f"| {r['period']} | {_fmt(r.get('demand_qty'))} | "
            f"{_fmt(r.get('sched_qty'))} | {_fmt(r.get('gap'))} | "
            f"{_fmt(r.get('fill_pct'))}% |"
        )
    period_table = "\n".join(period_table_lines)

    # Lateness summary
    lat = deep.get("lateness_analysis") or {}
    lateness_text = (
        f"Late rows: {lat.get('late_rows',0)}, Avg: {lat.get('avg_days','N/A')} days, "
        f"Max: {lat.get('max_days','N/A')} days, Median: {lat.get('median_days','N/A')} days, "
        f">30d: {lat.get('gt_30_days',0)}, >60d: {lat.get('gt_60_days',0)}"
        if lat else "No lateness data."
    )

    # Supply constraint signals (key sentences)
    signals = "\n".join(f"- {s}" for s in deep.get("supply_constraint_signals", []))

    # Top 5 resources
    res_lines = []
    for r in deep.get("top_resource_loads", [])[:5]:
        res_lines.append(
            f"- {r['resource']}: total={_fmt(r.get('total_load'),0)}, "
            f"cust={_fmt(r.get('customer_load'),0)}, fcst={_fmt(r.get('forecast_load'),0)}"
        )
    resources_text = "\n".join(res_lines) if res_lines else "No resource load data."

    # Top 5 competing demand items
    comp_lines = []
    for c in deep.get("competing_demand_detail", [])[:5]:
        comp_lines.append(f"- Item {c['item']}: priority={c['priority']}, qty={_fmt(c.get('qty'),0)}, rows={c['rows']}")
    competing_text = "\n".join(comp_lines) if comp_lines else "No competing demand with higher priority found."

    # Exception detail
    exc_lines = []
    for e in deep.get("exception_detail", [])[:5]:
        exc_lines.append(
            f"- Exception {e['exception']} ({e['descr']}) at {e['loc']}, "
            f"when={e.get('when','N/A')}, demand_qty={e.get('demand_qty','N/A')}"
        )
    exceptions_text = "\n".join(exc_lines) if exc_lines else "No SKU exceptions found."

    # Root causes and attribution
    root_causes_text = "\n".join(f"{i+1}. {c}" for i, c in enumerate(raw.get("Root Causes", [])))
    attribution_tags = ", ".join((raw.get("Cause Attribution (BY ESP Expert View)") or {}).get("primary_cause_tags", []))
    by_esp_reasoning = "\n".join(
        f"- {r}" for r in (raw.get("Cause Attribution (BY ESP Expert View)") or {}).get("by_esp_reasoning", [])
    )

    # Supply methods
    supply_methods = ", ".join(lineage.get("supply_methods_seen", [])[:5])
    top_supply_items = "; ".join(
        f"{s['supply_item']}@{s['supply_loc']} ({_fmt(s['pegged_qty'])})"
        for s in lineage.get("top_pegged_supply_items", [])[:4]
    )

    evidence_brief = f"""ITEM: {demand_item} | WEEK: {resolved_week} | SCENARIO: {resolved_scen}
MEET STATUS: {ds.get('meet_status','unknown')} | FILL RATE: {_fmt(fill_rate)}%

## Demand vs Supply Summary
- Demand Qty: {_fmt(demand_qty,3)} | Scheduled: {_fmt(sched_qty,3)} | Unmet: {_fmt(stats.get('unmet_qty',0),3)}
- On-Time Qty: {_fmt(stats.get('on_time_qty',0),3)} | Late Qty: {_fmt(stats.get('late_qty',0),3)}
- First need date: {ds.get('first_need_date','N/A')} | Last need date: {ds.get('last_need_date','N/A')}
- First sched date: {ds.get('first_sched_date','N/A')} | Last sched date: {ds.get('last_sched_date','N/A')}
- Planned arrival: {_fmt(planned.get('plan_arrival_qty',0),0)} (first: {planned.get('plan_arrival_first_date','N/A')})
- Planned orders: {_fmt(planned.get('plan_order_qty',0),0)} (first: {planned.get('plan_order_first_date','N/A')})
- Pegged supply qty: {_fmt(lineage.get('pegged_supply_qty',0),0)} vs pegged demand qty: {_fmt(lineage.get('pegged_demand_qty',0),0)}

## Period-by-Period Demand-Supply Balance (worst periods first)
{period_table}

## Lateness Analysis
{lateness_text}

## Supply Constraint Signals (NONEWSUPPLYDATE fences, lead times, lot sizes)
{signals if signals else "No supply constraint signals detected."}

## Top Resources by Load (for this item)
{resources_text}

## Competing Higher-Priority Demand
{competing_text}

## Planning Exceptions
{exceptions_text}

## Item Setup Flags
{json.dumps(item_setup.get("setup_flags", {}), ensure_ascii=True)}

## Item Profile
{json.dumps(item_setup.get("item_profile", {}), ensure_ascii=True)}

## Supply Chain
- Supply types: {", ".join(lineage.get("supply_types_seen", []))}
- Supply methods: {supply_methods}
- Top pegged supply items: {top_supply_items or "None found"}

## Root Causes (pre-computed)
{root_causes_text or "None identified."}

## Attribution Tags
{attribution_tags or "None."}
{by_esp_reasoning}

## Constraint Exceptions
- Capacity exceptions: {constraint.get('capacity_exception_rows',0)}, overutil qty: {_fmt(constraint.get('capacity_overutil_qty',0),0)}
- SKU exceptions for item: {constraint.get('sku_exception_rows_for_item',0)}
- Competing demand rows: {constraint.get('higher_priority_competing_rows',0)}, qty: {_fmt(constraint.get('higher_priority_competing_qty',0),0)}
- Resources loaded: {constraint.get('resource_count',0)}
"""

    system_prompt = (
        "You are IFSP Planning Copilot, a senior Blue Yonder Enterprise Supply Planning expert for Intel Foundry. "
        "You have been given PRE-VERIFIED facts from BY ESP planning data. "
        "Write a concise, fact-grounded root cause narrative — maximum 500 words total. "
        "RULES: Only cite numbers present in the evidence. Use **bold** for key quantities. "
        "Use ### for section headers. Use - for bullet lists. "
        "Be direct, specific, and actionable. No generic filler. No repetition."
    )

    prompt = (
        f"ANALYSIS FOCUS: {focus}\n\n"
        f"PLANNING EVIDENCE:\n{evidence_brief}\n\n"
        "Write a concise analysis using these sections (2-4 bullets each, no padding):\n"
        "### Executive Summary\n"
        "### Demand-Supply Gap Analysis\n"
        "(name the worst months from the period table with exact fill%)\n"
        "### Confirmed Root Causes\n"
        "(numbered, each citing a specific number)\n"
        "### Supply Constraint Details\n"
        "(NONEWSUPPLYDATE fences, lead times, lot sizes, lateness stats)\n"
        "### Resource Findings\n"
        "### Recommended Next Steps\n"
        "(3 specific actions)\n"
    )

    narrative = _ollama_chat_with_model(prompt, system_prompt, llm_model or LLM_CONFIG["model"])

    return {
        "narrative": narrative or _build_fallback_rc_narrative(
            stats, raw.get("Root Causes", []), raw.get("Confirmed Findings", [])
        ),
        "stats":          stats,
        "question_type":  question_type,
        "question_label": _RC_QUESTION_LABELS.get(question_type, question_type),
        "llm_model":      (llm_model or LLM_CONFIG["model"]),
        "llm_used":       bool(narrative),
        "raw_data":       raw,
        "deep_evidence":  deep,
    }


# ---------------------------------------------------------------------------
# Log Reader — parse and summarize planning logs via Ollama
# ---------------------------------------------------------------------------

def run_log_reader(
    base_dir: Path,
    question: str,
    log_content: Optional[str] = None,
    week_id: Optional[str] = None,
    scenario_id: Optional[str] = None,
    scope: Optional[Dict] = None,
) -> Dict:
    """
    Parse and summarize a planning log, solver output, or exception report.
    Uses Ollama with a BY ESP-aware system prompt.
    log_content defaults to question when not provided separately.
    """
    content = (log_content or question or "").strip()
    context = _resolve_context(base_dir, week_id, scenario_id)

    system_prompt = (
        "You are an Intel Foundry Supply Planning log analyst specializing in "
        "Blue Yonder Enterprise Supply Planning (BY ESP) solver outputs and exception logs. "
        "Analyze the provided planning log excerpt and extract:\n"
        "1. Log Type (solver log / exception log / data error / planning output / other)\n"
        "2. Key Events (errors, warnings, exceptions found in order of severity)\n"
        "3. Planning Domain (Fulfillment / Generation / Data Hygiene / Unknown)\n"
        "4. Root Cause Indicators (what the log suggests is wrong)\n"
        "5. Recommended Actions (what a planner should investigate next)\n"
        "Be concise and planner-friendly. Use BY ESP terminology where applicable. "
        "If the input is not a log, say so clearly and ask the planner to paste the log content."
    )
    prompt = f"Planning context: week={context.get('week_id')}, scenario={context.get('scenario_id')}\n\nLog content:\n{content}"

    reply = _ollama_chat_with_model(prompt, system_prompt, LLM_CONFIG["model"])

    return {
        "Workflow": "Log Reader",
        "Context Resolution": context,
        "Log Content Length": len(content),
        "Assistant Reply": reply or f"Log analysis could not be completed — {LLM_CONFIG['provider']} unavailable.",
        "LLM Provider": LLM_CONFIG["provider"].capitalize(),
        "LLM Model": LLM_CONFIG["model"],
        "Note": "Paste the full log text as your question or in the log_text field for best results.",
    }


# ---------------------------------------------------------------------------
# Vision Query — analyze planning images via Nollama vision model
# ---------------------------------------------------------------------------

def _call_vision_ollama(question: str, image_base64: str) -> Optional[str]:
    """Call the vision model with a base64-encoded image using configured LLM provider."""
    # Strip data URI prefix if present (data:image/...;base64,...)
    b64 = re.sub(r"^data:image/[^;]+;base64,", "", image_base64.strip())

    payload = {
        "model": LLM_CONFIG["vision_model"],
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are an Intel Foundry Supply Planning visual analyst. "
                    "Analyze the planning image and extract: "
                    "chart/table type, key planning metrics, anomalies or concerns, "
                    "planning context (demand/supply/capacity/BOM/inventory), "
                    "and recommended follow-up analysis. "
                    "Be concise and use BY ESP terminology."
                ),
            },
            {
                "role": "user",
                "content": question or "Analyze this planning image.",
                "images": [b64],
            },
        ],
        "temperature": 0.1,
    }
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    
    api_key = LLM_CONFIG.get("api_key")
    if api_key:
        auth_hdr = LLM_CONFIG.get("auth_header", "Authorization")
        headers[auth_hdr] = f"Bearer {api_key}" if auth_hdr == "Authorization" else api_key
    if LLM_CONFIG.get("provider") == "anthropic":
        headers["anthropic-version"] = "2023-06-01"
    
    if LLM_CONFIG.get("provider") == "azure":
        vision_endpoint = f"{LLM_CONFIG['base_url']}/chat/completions?api-version={LLM_CONFIG.get('api_version', '2024-02-01')}"
    else:
        vision_endpoint = f"{LLM_CONFIG['base_url']}/v1/chat/completions"
    
    req = request.Request(
        vision_endpoint,
        data=data,
        headers=headers,
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except (error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    # Parse OpenAI format response
    choices = body.get("choices") or []
    if choices:
        message = choices[0].get("message") or {}
        content = (message.get("content") or "").strip()
        return content or None
    return None


def run_vision_query(
    base_dir: Path,
    question: str,
    image_base64: str,
    week_id: Optional[str] = None,
    scenario_id: Optional[str] = None,
    scope: Optional[Dict] = None,
) -> Dict:
    """
    Analyze a planning screenshot, chart, or visual report using the configured vision model.
    image_base64: base64-encoded image string (with or without data URI prefix).
    Requires a vision-capable model configured via LLM_PROVIDER environment variable.
    """
    context = _resolve_context(base_dir, week_id, scenario_id)

    if not image_base64:
        return {
            "Workflow": "Vision Query",
            "Error": "No image provided. Send a base64-encoded image in the image_base64 field.",
        }

    reply = _call_vision_ollama(question, image_base64)

    return {
        "Workflow": "Vision Query",
        "Context Resolution": context,
        "Question": question,
        "Assistant Reply": reply or (
            f"Vision analysis could not be completed. "
            f"Ensure a vision-capable model is available: "
            f"Vision Model={LLM_CONFIG['vision_model']} at {LLM_CONFIG['base_url']}. "
            f"Contact your {LLM_CONFIG['provider']} administrator."
        ),
        "LLM Provider": LLM_CONFIG["provider"].capitalize(),
        "Vision Model": LLM_CONFIG["vision_model"],
        "Note": (
            f"Uses {LLM_CONFIG['vision_model']} via {LLM_CONFIG['provider']}. "
        ),
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
            "description": "Start with ITEM. Add week, scenario, and plant when available for a cleaner lineage graph.",
        },
        "nodes": nodes,
        "edges": edges,
    }


def run_insights(
    base_dir: Path,
    week_id: Optional[str],
    scenario_id: Optional[str],
    base_scenario_id: Optional[str],
    compare_scenario_id: Optional[str],
    scope: Dict,
) -> Dict:
    site = (scope.get("site") or "").strip()
    input_dir = base_dir / INPUT_FOLDER
    output_dir = base_dir / OUTPUT_FOLDER

    skuproj_file = _find_file_by_prefix(output_dir, "by_if_snop_out_skuprojstatic-")
    resproj_file = _find_file_by_prefix(output_dir, "by_if_snop_out_resprojstatic-")
    inddmdview_file = _find_file_by_prefix(output_dir, "by_if_snop_out_inddmdview-")
    calpattern_file = _find_file_by_prefix(input_dir, "if_snop_calpattern-")

    calendar_windows: List[Tuple[datetime, datetime, str]] = []
    seen_windows = set()
    if calpattern_file:
        for row in _safe_rows(calpattern_file):
            start = _parse_date(row.get("STARTDATE"))
            end = _parse_date(row.get("ENDDATE"))
            seq = (row.get("PATTERNSEQNUM") or "").strip()
            if not start or not end:
                continue
            key = (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"), seq)
            if key in seen_windows:
                continue
            seen_windows.add(key)
            calendar_windows.append((start, end, seq))
    calendar_windows.sort(key=lambda item: item[0])

    grains = ["workweek", "month", "quarter"]

    def _bucket_labels(dt: Optional[datetime]) -> Dict[str, str]:
        if not dt:
            return {
                "workweek": "Unknown",
                "month": "Unknown",
                "quarter": "Unknown",
            }

        ww_label = None
        for start, end, seq in calendar_windows:
            if start <= dt <= end:
                ww_label = seq or None
                break
        if not ww_label:
            ww_label = f"{dt.year}{int(dt.strftime('%W')):02d}"

        month_label = f"{dt.year}-{dt.month:02d}"
        quarter_label = f"{dt.year}-Q{((dt.month - 1) // 3) + 1}"
        return {
            "workweek": ww_label,
            "month": month_label,
            "quarter": quarter_label,
        }

    def _sort_bucket_keys(grain: str, keys: List[str]) -> List[str]:
        if grain == "workweek":
            return sorted(keys, key=lambda value: (0, int(value)) if str(value).isdigit() else (1, str(value)))
        return sorted(keys)

    def _collect_for_context(resolved_week: Optional[str], resolved_scenario: Optional[str]) -> Dict:
        demand_supply_by_grain: Dict[str, Dict[str, Dict[str, float]]] = {grain: {} for grain in grains}
        fill_rate_by_grain: Dict[str, Dict[str, Dict[str, float]]] = {grain: {} for grain in grains}
        fill_rate_sched_by_grain: Dict[str, Dict[str, Dict[str, float]]] = {grain: {} for grain in grains}
        capacity_by_grain: Dict[str, Dict[str, Dict[str, float]]] = {grain: {} for grain in grains}
        demand_split_by_grain: Dict[str, Dict[str, Dict[str, float]]] = {grain: {} for grain in grains}
        overall_counts = {"Met": 0, "Partially Met": 0, "UnMet": 0}
        overall_qty = {"Met": 0.0, "Partially Met": 0.0, "UnMet": 0.0}

        if skuproj_file:
            for row in _safe_rows(skuproj_file):
                if not _matches_context(row, resolved_week, resolved_scenario):
                    continue
                if site and (row.get("LOC") or "").strip() != site:
                    continue

                labels = _bucket_labels(_parse_date(row.get("STARTDATE")))
                demand_qty = _safe_float(row.get("TOTDMD"))
                supply_qty = _safe_float(row.get("TOTSUPPLY"))
                met_qty = _safe_float(row.get("METINDDMD"))

                for grain in grains:
                    label = labels[grain]
                    ds_bucket = demand_supply_by_grain[grain].setdefault(label, {"demand_qty": 0.0, "supply_qty": 0.0})
                    ds_bucket["demand_qty"] += demand_qty
                    ds_bucket["supply_qty"] += supply_qty

                    fr_bucket = fill_rate_by_grain[grain].setdefault(label, {"demand_qty": 0.0, "met_qty": 0.0})
                    fr_bucket["demand_qty"] += demand_qty
                    fr_bucket["met_qty"] += met_qty

        if resproj_file:
            for row in _safe_rows(resproj_file):
                if not _matches_context(row, resolved_week, resolved_scenario):
                    continue
                if site and (row.get("LOC") or "").strip() != site:
                    continue

                labels = _bucket_labels(_parse_date(row.get("STARTDATE")))
                pct_used = _safe_float(row.get("PCTUSED"))
                avail_cap = _safe_float(row.get("AVAILCAP"))
                total_load = _safe_float(row.get("MPTOTLOAD"))

                for grain in grains:
                    label = labels[grain]
                    cap_bucket = capacity_by_grain[grain].setdefault(
                        label,
                        {
                            "pct_used_sum": 0.0,
                            "pct_used_count": 0.0,
                            "avail_cap": 0.0,
                            "total_load": 0.0,
                        },
                    )
                    cap_bucket["pct_used_sum"] += pct_used
                    cap_bucket["pct_used_count"] += 1.0
                    cap_bucket["avail_cap"] += avail_cap
                    cap_bucket["total_load"] += total_load

        if inddmdview_file:
            for row in _safe_rows(inddmdview_file):
                if not _matches_context(row, resolved_week, resolved_scenario):
                    continue
                if site and (row.get("LOC") or "").strip() != site:
                    continue

                labels = _bucket_labels(_parse_date(row.get("NEEDDATE")))
                demand_qty = _safe_float(row.get("QTY"))
                sched_qty = _safe_float(row.get("SCHEDQTY"))

                if sched_qty <= 0:
                    bucket = "UnMet"
                elif sched_qty + 1e-9 >= demand_qty:
                    bucket = "Met"
                else:
                    bucket = "Partially Met"

                overall_counts[bucket] += 1
                overall_qty[bucket] += demand_qty

                for grain in grains:
                    label = labels[grain]
                    split_bucket = demand_split_by_grain[grain].setdefault(
                        label,
                        {
                            "met_count": 0,
                            "partial_count": 0,
                            "unmet_count": 0,
                            "demand_qty": 0.0,
                            "scheduled_qty": 0.0,
                        },
                    )
                    if bucket == "Met":
                        split_bucket["met_count"] += 1
                    elif bucket == "Partially Met":
                        split_bucket["partial_count"] += 1
                    else:
                        split_bucket["unmet_count"] += 1
                    split_bucket["demand_qty"] += demand_qty
                    split_bucket["scheduled_qty"] += sched_qty

                    fr_sched_bucket = fill_rate_sched_by_grain[grain].setdefault(label, {"demand_qty": 0.0, "met_qty": 0.0})
                    fr_sched_bucket["demand_qty"] += demand_qty
                    fr_sched_bucket["met_qty"] += min(sched_qty, demand_qty)

        met_qty_from_sku = sum(item["met_qty"] for item in fill_rate_by_grain["workweek"].values())
        demand_qty_from_sched = sum(item["demand_qty"] for item in fill_rate_sched_by_grain["workweek"].values())
        fill_rate_source = fill_rate_by_grain
        fill_rate_source_name = "METINDDMD"
        if met_qty_from_sku <= 0 and demand_qty_from_sched > 0:
            fill_rate_source = fill_rate_sched_by_grain
            fill_rate_source_name = "SCHEDQTY/QTY fallback"

        demand_supply_trend = {grain: [] for grain in grains}
        for grain in grains:
            for key in _sort_bucket_keys(grain, list(demand_supply_by_grain[grain].keys())):
                demand_qty = demand_supply_by_grain[grain][key]["demand_qty"]
                supply_qty = demand_supply_by_grain[grain][key]["supply_qty"]
                demand_supply_trend[grain].append(
                    {
                        "bucket": key,
                        "demand_qty": round(demand_qty, 3),
                        "supply_qty": round(supply_qty, 3),
                        "gap_qty": round(supply_qty - demand_qty, 3),
                    }
                )

        fill_rate_trend = {grain: [] for grain in grains}
        for grain in grains:
            for key in _sort_bucket_keys(grain, list(fill_rate_source[grain].keys())):
                demand_qty = fill_rate_source[grain][key]["demand_qty"]
                met_qty = fill_rate_source[grain][key]["met_qty"]
                fill_rate_pct = (met_qty / demand_qty * 100.0) if demand_qty > 0 else 0.0
                fill_rate_trend[grain].append(
                    {
                        "bucket": key,
                        "demand_qty": round(demand_qty, 3),
                        "met_qty": round(met_qty, 3),
                        "fill_rate_pct": round(fill_rate_pct, 2),
                    }
                )

        capacity_utilization_trend = {grain: [] for grain in grains}
        for grain in grains:
            for key in _sort_bucket_keys(grain, list(capacity_by_grain[grain].keys())):
                bucket = capacity_by_grain[grain][key]
                avg_pct = (bucket["pct_used_sum"] / bucket["pct_used_count"]) if bucket["pct_used_count"] > 0 else 0.0
                derived_pct = (bucket["total_load"] / bucket["avail_cap"] * 100.0) if bucket["avail_cap"] > 0 else 0.0
                capacity_utilization_trend[grain].append(
                    {
                        "bucket": key,
                        "avg_pct_used": round(avg_pct, 2),
                        "derived_utilization_pct": round(derived_pct, 2),
                        "available_capacity": round(bucket["avail_cap"], 3),
                        "total_load": round(bucket["total_load"], 3),
                    }
                )

        demand_status_split = {grain: [] for grain in grains}
        for grain in grains:
            for key in _sort_bucket_keys(grain, list(demand_split_by_grain[grain].keys())):
                split = demand_split_by_grain[grain][key]
                demand_status_split[grain].append(
                    {
                        "bucket": key,
                        "met_count": int(split["met_count"]),
                        "partial_count": int(split["partial_count"]),
                        "unmet_count": int(split["unmet_count"]),
                        "total_count": int(split["met_count"] + split["partial_count"] + split["unmet_count"]),
                        "demand_qty": round(split["demand_qty"], 3),
                        "scheduled_qty": round(split["scheduled_qty"], 3),
                    }
                )

        total_demand = sum(item["demand_qty"] for item in fill_rate_source["workweek"].values())
        total_met = sum(item["met_qty"] for item in fill_rate_source["workweek"].values())
        overall_fill_rate = (total_met / total_demand * 100.0) if total_demand > 0 else 0.0

        return {
            "Trend Analysis": {
                "Demand vs Supply": demand_supply_trend,
                "Fill Rate": fill_rate_trend,
                "Capacity Utilization": capacity_utilization_trend,
                "Demand Met vs UnMet vs Partially Met": {
                    "by_grain": demand_status_split,
                    "counts": overall_counts,
                    "demand_qty": {k: round(v, 3) for k, v in overall_qty.items()},
                },
            },
            "KPI Summary": {
                "overall_fill_rate_pct": round(overall_fill_rate, 2),
                "total_demand_qty": round(total_demand, 3),
                "total_met_qty": round(total_met, 3),
                "total_records_in_met_status_split": int(sum(overall_counts.values())),
                "fill_rate_source": fill_rate_source_name,
            },
        }

    data_gaps = []
    if not skuproj_file:
        data_gaps.append("Missing by_if_snop_out_skuprojstatic file for demand/supply and fill-rate trends.")
    if not resproj_file:
        data_gaps.append("Missing by_if_snop_out_resprojstatic file for capacity utilization trend.")
    if not inddmdview_file:
        data_gaps.append("Missing by_if_snop_out_inddmdview file for demand met/unmet split.")
    if not calpattern_file:
        data_gaps.append("Missing if_snop_calpattern file for Workweek calendar mapping. Fallback buckets are used.")

    compare_requested = bool((base_scenario_id or "").strip() or (compare_scenario_id or "").strip())

    if compare_requested:
        cmp_context = _resolve_compare_context(base_dir, week_id, base_scenario_id, compare_scenario_id)
        resolved_week = cmp_context["week_id"]
        base_sc = cmp_context["base_scenario_id"]
        cmp_sc = cmp_context["compare_scenario_id"]
        if not base_sc or not cmp_sc:
            data_gaps.append("Scenario compare mode requires at least one resolvable SIMULATION_NAME.")

        base_metrics = _collect_for_context(resolved_week, base_sc)
        cmp_metrics = _collect_for_context(resolved_week, cmp_sc)

        base_kpi = base_metrics["KPI Summary"]
        cmp_kpi = cmp_metrics["KPI Summary"]

        split_order = ["Met", "Partially Met", "UnMet"]
        base_split = base_metrics["Trend Analysis"]["Demand Met vs UnMet vs Partially Met"]["counts"]
        cmp_split = cmp_metrics["Trend Analysis"]["Demand Met vs UnMet vs Partially Met"]["counts"]

        demand_delta = {grain: [] for grain in grains}
        for grain in grains:
            base_rows = {row["bucket"]: row for row in base_metrics["Trend Analysis"]["Demand vs Supply"].get(grain, [])}
            cmp_rows = {row["bucket"]: row for row in cmp_metrics["Trend Analysis"]["Demand vs Supply"].get(grain, [])}
            keys = _sort_bucket_keys(grain, list(set(base_rows.keys()) | set(cmp_rows.keys())))
            for key in keys:
                b = base_rows.get(key, {"demand_qty": 0.0, "supply_qty": 0.0})
                c = cmp_rows.get(key, {"demand_qty": 0.0, "supply_qty": 0.0})
                demand_delta[grain].append(
                    {
                        "bucket": key,
                        "demand_qty_delta": round(c["demand_qty"] - b["demand_qty"], 3),
                        "supply_qty_delta": round(c["supply_qty"] - b["supply_qty"], 3),
                        "gap_qty_delta": round((c["supply_qty"] - c["demand_qty"]) - (b["supply_qty"] - b["demand_qty"]), 3),
                    }
                )

        demand_status_delta = {grain: [] for grain in grains}
        for grain in grains:
            base_rows = {
                row["bucket"]: row
                for row in base_metrics["Trend Analysis"]["Demand Met vs UnMet vs Partially Met"]["by_grain"].get(grain, [])
            }
            cmp_rows = {
                row["bucket"]: row
                for row in cmp_metrics["Trend Analysis"]["Demand Met vs UnMet vs Partially Met"]["by_grain"].get(grain, [])
            }
            keys = _sort_bucket_keys(grain, list(set(base_rows.keys()) | set(cmp_rows.keys())))
            for key in keys:
                b = base_rows.get(key, {"met_count": 0, "partial_count": 0, "unmet_count": 0, "total_count": 0})
                c = cmp_rows.get(key, {"met_count": 0, "partial_count": 0, "unmet_count": 0, "total_count": 0})
                demand_status_delta[grain].append(
                    {
                        "bucket": key,
                        "met_delta": int(c["met_count"] - b["met_count"]),
                        "partial_delta": int(c["partial_count"] - b["partial_count"]),
                        "unmet_delta": int(c["unmet_count"] - b["unmet_count"]),
                        "total_delta": int(c["total_count"] - b["total_count"]),
                    }
                )

        return {
            "Insights Mode": "Scenario Compare",
            "Comparison Scope": {
                "week_id": resolved_week,
                "base_scenario_id": base_sc,
                "compare_scenario_id": cmp_sc,
                "week_column": "CAPTURE_WK",
                "scenario_column": "SIMULATION_NAME",
                "scope": scope,
                "context_resolution": cmp_context,
            },
            "Base Scenario Insights": base_metrics,
            "Compare Scenario Insights": cmp_metrics,
            "Scenario Delta": {
                "KPI Summary Delta (compare - base)": {
                    "overall_fill_rate_pct_delta": round(cmp_kpi["overall_fill_rate_pct"] - base_kpi["overall_fill_rate_pct"], 2),
                    "total_demand_qty_delta": round(cmp_kpi["total_demand_qty"] - base_kpi["total_demand_qty"], 3),
                    "total_met_qty_delta": round(cmp_kpi["total_met_qty"] - base_kpi["total_met_qty"], 3),
                    "met_status_record_count_delta": int(cmp_kpi["total_records_in_met_status_split"] - base_kpi["total_records_in_met_status_split"]),
                },
                "Demand/Supply Delta by Date": demand_delta,
                "Demand Status Count Delta": {
                    key: int(cmp_split.get(key, 0) - base_split.get(key, 0))
                    for key in split_order
                },
                "Demand Status Count Delta by Grain": demand_status_delta,
            },
            "Confidence and Data Gaps": {
                "confidence": "Medium" if not data_gaps else "Low-Medium",
                "data_gaps": data_gaps,
            },
        }

    context = _resolve_context(base_dir, week_id, scenario_id)
    resolved_week = context["week_id"]
    resolved_scenario = context["scenario_id"]
    if not resolved_scenario:
        data_gaps.append("No SIMULATION_NAME found in output data.")

    single_metrics = _collect_for_context(resolved_week, resolved_scenario)
    return {
        "Insights Mode": "Single Scenario",
        "Insights Scope": {
            "week_id": resolved_week,
            "scenario_id": resolved_scenario,
            "week_column": "CAPTURE_WK",
            "scenario_column": "SIMULATION_NAME",
            "scope": scope,
            "context_resolution": context,
        },
        "Trend Analysis": single_metrics["Trend Analysis"],
        "KPI Summary": single_metrics["KPI Summary"],
        "Confidence and Data Gaps": {
            "confidence": "Medium" if not data_gaps else "Low-Medium",
            "data_gaps": data_gaps,
        },
    }


def _short_table_name(file_name: str) -> str:
    name = (file_name or "").strip()
    if not name:
        return ""
    if name.lower().endswith(".csv"):
        name = name[:-4]
    return re.sub(r"-\d{14}$", "", name)


def _chat_table_catalog(base_dir: Path) -> List[Dict]:
    inventory = dataset_inventory(base_dir)
    catalog: List[Dict] = []
    for family, key in [("input", "input_files"), ("output", "output_files")]:
        for file_info in inventory.get(key, []):
            full_name = file_info.get("file") or ""
            table_name = _short_table_name(full_name)
            catalog.append(
                {
                    "family": family,
                    "file": full_name,
                    "table": table_name,
                    "rows": file_info.get("rows", 0),
                    "columns": file_info.get("columns", []),
                }
            )
    return catalog


def _match_tables_for_question(question: str, table_catalog: List[Dict], max_tables: int = 10) -> List[Dict]:
    q = (question or "").lower()
    tokens = set(re.findall(r"[a-z_][a-z0-9_]{2,}", q))

    scored: List[Tuple[int, Dict]] = []
    for table in table_catalog:
        table_name = (table.get("table") or "").lower()
        cols = [str(c).lower() for c in table.get("columns", [])]
        score = 0
        if table_name and table_name in q:
            score += 8
        for token in tokens:
            if token in table_name:
                score += 3
            if any(token == col or token in col for col in cols):
                score += 1
        if score > 0:
            scored.append((score, table))

    ranked = [item for _score, item in sorted(scored, key=lambda x: (x[0], x[1].get("rows", 0)), reverse=True)]
    return ranked[:max_tables]


def _related_linkages(matched_tables: List[Dict]) -> List[Dict]:
    names = {(item.get("table") or "").lower() for item in matched_tables}
    if not names:
        return BY_ESP_DOMAIN_KNOWLEDGE["linkages"][:4]

    related = []
    for linkage in BY_ESP_DOMAIN_KNOWLEDGE["linkages"]:
        frm = (linkage.get("from") or "").lower()
        to = (linkage.get("to") or "").lower()
        if any(name and (name in frm or name in to) for name in names):
            related.append(linkage)
    return related[:6]


def _build_chat_grounding(base_dir: Path, question: str, context: Dict, scope: Dict) -> Dict:
    table_catalog = _chat_table_catalog(base_dir)
    matched = _match_tables_for_question(question, table_catalog)

    guided_tables = []
    table_guidance = BY_ESP_DOMAIN_KNOWLEDGE["table_guidance"]
    for item in matched:
        table_name = item.get("table") or ""
        guided_tables.append(
            {
                "table": table_name,
                "family": item.get("family"),
                "rows": item.get("rows"),
                "columns": item.get("columns", [])[:25],
                "definition": table_guidance.get(table_name, "Definition not mapped yet. Use columns and linkage context."),
            }
        )

    if not guided_tables:
        defaults = [
            "if_snop_sku",
            "if_snop_billofmaterials",
            "by_if_snop_out_inddmdview",
            "by_if_snop_out_inddmdlink",
            "by_if_snop_out_skuprojstatic",
        ]
        quick_lookup = {item.get("table"): item for item in table_catalog}
        for table_name in defaults:
            item = quick_lookup.get(table_name, {})
            guided_tables.append(
                {
                    "table": table_name,
                    "family": item.get("family"),
                    "rows": item.get("rows"),
                    "columns": item.get("columns", [])[:25],
                    "definition": table_guidance.get(table_name, "Definition not mapped yet. Use columns and linkage context."),
                }
            )

    return {
        "context_resolution": context,
        "scope": scope,
        "solver_knowledge": BY_ESP_DOMAIN_KNOWLEDGE["solver"],
        "domain_framework": BY_ESP_DOMAIN_FRAMEWORK,
        "matched_tables": guided_tables,
        "key_linkages": _related_linkages(guided_tables),
    }


def _extract_requested_table_name(question: str) -> Optional[str]:
    q = (question or "").strip()
    if not q:
        return None

    patterns = [
        r"(?:explain|describe|define|show)\s+(?:table\s+)?([a-zA-Z0-9_]+)",
        r"table\s+([a-zA-Z0-9_]+)",
        r"for\s+table\s+([a-zA-Z0-9_]+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, q, flags=re.IGNORECASE)
        if match:
            return (match.group(1) or "").strip().lower()
    return None


def _run_table_explain_workflow(base_dir: Path, question: str) -> Dict:
    requested = _extract_requested_table_name(question)
    table_catalog = _chat_table_catalog(base_dir)

    if not requested:
        return {
            "workflow": "Table Explain",
            "clarification": {
                "question": "Which table do you want me to explain?",
                "examples": [
                    "Explain table by_if_snop_out_inddmdview",
                    "Describe if_snop_sku columns and linkage",
                ],
            },
        }

    normalized_requested = requested.replace(".csv", "")
    matches = []
    for item in table_catalog:
        table_name = (item.get("table") or "").lower()
        file_name = (item.get("file") or "").lower()
        if (
            table_name == normalized_requested
            or table_name.endswith(normalized_requested)
            or normalized_requested in table_name
            or normalized_requested in file_name
        ):
            matches.append(item)

    if not matches:
        suggestions = sorted({item.get("table") for item in table_catalog if item.get("table")})[:12]
        return {
            "workflow": "Table Explain",
            "clarification": {
                "question": f"I could not find table '{normalized_requested}'. Can you confirm the exact table name?",
                "suggestions": suggestions,
            },
        }

    top = sorted(matches, key=lambda item: item.get("rows", 0), reverse=True)[0]
    table_name = top.get("table") or normalized_requested
    guidance = BY_ESP_DOMAIN_KNOWLEDGE["table_guidance"].get(table_name, "Definition not mapped yet. Use columns and linkage context.")
    linkages = []
    for linkage in BY_ESP_DOMAIN_KNOWLEDGE["linkages"]:
        frm = (linkage.get("from") or "").lower()
        to = (linkage.get("to") or "").lower()
        if table_name.lower() in frm or table_name.lower() in to:
            linkages.append(linkage)

    return {
        "workflow": "Table Explain",
        "result": {
            "table": table_name,
            "family": top.get("family"),
            "file": top.get("file"),
            "row_count": top.get("rows"),
            "definition": guidance,
            "columns": top.get("columns", []),
            "linkages": linkages[:8],
        },
        "note": "Table explanation is grounded on local snapshot schema and configured BY ESP linkage guidance.",
    }


def _run_item_demand_supply_workflow(
    base_dir: Path,
    week_id: Optional[str],
    scenario_id: Optional[str],
    item_id: str,
    scope: Dict,
) -> Dict:
    root = run_root_cause(base_dir, week_id, scenario_id, item_id, scope)
    summary = root.get("Demand and Supply Summary", {})
    linkage = root.get("Lineage and Linkage Findings", {})
    planned = root.get("Planned Supply Evidence", {})
    constraints = root.get("Constraint and Exception Analysis", {})
    gaps = (root.get("Hypotheses and Missing Evidence") or {}).get("missing_evidence", [])

    return {
        "workflow": "Item Demand Supply",
        "result": {
            "Item": item_id,
            "Explainability Scope": root.get("Explainability Scope", {}),
            "Demand vs Supply Stats": {
                "demand_qty_total": summary.get("demand_qty_total"),
                "scheduled_qty_total": summary.get("scheduled_qty_total"),
                "unmet_qty": summary.get("unmet_qty"),
                "meet_status": summary.get("meet_status"),
                "on_time_scheduled_qty": summary.get("on_time_scheduled_qty"),
                "late_scheduled_qty": summary.get("late_scheduled_qty"),
                "demand_rows": summary.get("demand_rows"),
            },
            "Supply Evidence": {
                "plan_arrival_qty": planned.get("plan_arrival_qty"),
                "plan_order_qty": planned.get("plan_order_qty"),
                "plan_purchase_qty": planned.get("plan_purchase_qty"),
                "pegged_supply_qty": linkage.get("pegged_supply_qty"),
                "pegged_demand_qty": linkage.get("pegged_demand_qty"),
                "inddmdlink_rows": linkage.get("inddmdlink_rows"),
            },
            "Constraint Signals": {
                "sku_exception_rows_for_item": constraints.get("sku_exception_rows_for_item"),
                "capacity_exception_rows": constraints.get("capacity_exception_rows"),
                "capacity_overutil_qty": constraints.get("capacity_overutil_qty"),
                "higher_priority_competing_qty": constraints.get("higher_priority_competing_qty"),
            },
            "Data Gaps": gaps,
            "Reference": {
                "Root Cause Detail": root,
            },
        },
        "note": "Demand vs supply response is item-specific and grounded in by_if_snop_out_* evidence.",
    }


def _suggest_followups(workflow: str, question: str) -> List[str]:
    wf = (workflow or "").strip().lower()
    if wf == "domain focus - fulfillment":
        return [
            "Show OTIF and fill-rate trend for latest 12 workweeks",
            "Which buckets have highest unmet demand and backlog risk?",
            "Drill down fulfillment domain for a specific item",
            "What are the strongest service-level gaps by scenario?",
        ]
    if wf == "domain focus - generation":
        return [
            "Show capacity utilization spikes and likely bottlenecks",
            "Break down lead-time variability drivers",
            "Explain generation-domain constraints for a specific item",
            "Which weeks show calendar/policy stress signals?",
        ]
    if wf == "domain focus - data hygiene":
        return [
            "List top master-data defects by planning impact",
            "Show parameter-gap checks for safety stock/MOQ/lot size",
            "Which fixes should be prioritized first?",
            "Re-run hygiene checks for a specific week/scenario",
        ]
    if wf == "table explain":
        return [
            "Show referential integrity checks for this table",
            "Which output tables link directly to this table?",
            "What are the business definitions of the top 10 columns?",
            "How is this table used in root-cause explainability?",
        ]
    if wf == "validation gate":
        return [
            "List the top critical data quality issues",
            "Show orphan key counts by table",
            "Suggest fix order by planning impact",
            "Re-run validation with specific week and scenario",
        ]
    if wf == "scenario comparison":
        return [
            "Compare unmet demand and capacity utilization deltas",
            "Rank top KPI drivers between the two scenarios",
            "Show data gaps affecting confidence",
            "What identifiers are required for strict scenario comparison?",
        ]
    if wf == "analytics insights":
        return [
            "Explain fill rate trend for latest workweeks",
            "Which buckets have highest unmet demand?",
            "Drill into capacity utilization by month",
            "How does demand vs supply gap evolve by quarter?",
        ]
    if wf == "root cause":
        return [
            "Show primary constraint chain from demand to resource",
            "Which input tables best explain this unmet demand?",
            "Quantify the biggest limiting factor",
            "What checks should I run to validate this root cause?",
        ]
    if wf == "root cause clarification":
        return [
            "Use ITEM 100000000008 and proceed",
            "Use the latest week and scenario",
            "Set plant to 1004 and continue",
            "Show candidate demand items from current context",
        ]
    if wf == "item demand supply":
        return [
            "Share more details about demand vs supply for the item",
            "Show pegged supply and top supply methods",
            "Break down planned arrival, order, and purchase quantities",
            "What are the top constraints causing unmet quantity?",
        ]
    return [
        "Explain BY ESP LP optimization objective and constraints",
        "Explain table by_if_snop_out_inddmdview",
        "Show linkage from demand to plan orders and resources",
        "Run validation for latest week and scenario",
    ]


def _strip_quotes(value: str) -> str:
    text = (value or "").strip()
    if len(text) >= 2 and ((text[0] == '"' and text[-1] == '"') or (text[0] == "'" and text[-1] == "'")):
        return text[1:-1]
    return text


def _parse_chat_command(question: str) -> Dict:
    text = (question or "").strip()
    if not text.startswith("/"):
        return {
            "is_command": False,
            "command": None,
            "args": {},
            "positional": [],
            "raw": text,
            "free_text": text,
        }

    match = re.match(r"^/([a-zA-Z0-9_-]+)\s*(.*)$", text)
    if not match:
        return {
            "is_command": False,
            "command": None,
            "args": {},
            "positional": [],
            "raw": text,
            "free_text": text,
        }

    command = (match.group(1) or "").strip().lower()
    remainder = (match.group(2) or "").strip()
    tokens = re.findall(r'"[^"]*"|\S+', remainder)

    args: Dict[str, str] = {}
    positional: List[str] = []
    for token in tokens:
        cleaned = _strip_quotes(token)
        if "=" in cleaned:
            key, value = cleaned.split("=", 1)
            key = key.strip().lower()
            value = _strip_quotes(value.strip())
            if key:
                args[key] = value
        elif cleaned:
            positional.append(cleaned)

    return {
        "is_command": True,
        "command": command,
        "args": args,
        "positional": positional,
        "raw": text,
        "free_text": " ".join(positional).strip(),
    }


def _get_arg(args: Dict[str, str], *keys: str) -> Optional[str]:
    for key in keys:
        value = (args.get(key) or "").strip()
        if value:
            return value
    return None


def _build_command_scope(base_scope: Dict, args: Dict[str, str]) -> Dict:
    scope = dict(base_scope or {})
    site = _get_arg(args, "plant", "site", "loc", "location")
    if site:
        scope["site"] = site
    return scope


def _execute_chat_command(base_dir: Path, parsed: Dict, week_id: Optional[str], scenario_id: Optional[str], scope: Dict) -> Dict:
    cmd = parsed.get("command")
    args = parsed.get("args") or {}
    positional = parsed.get("positional") or []

    cmd_week = _get_arg(args, "week", "wk", "capture_wk") or week_id
    cmd_scenario = _get_arg(args, "scenario", "sc", "simulation", "simulation_name") or scenario_id
    cmd_scope = _build_command_scope(scope, args)

    if cmd in {"help", "commands"}:
        return {
            "workflow": "Command Help",
            "result": {
                "commands": {
                    "/help": "Show command guide.",
                    "/summary [week=] [scenario=]": "Dataset and context summary.",
                    "/validate [week=] [scenario=] [plant=]": "Run validation workflow.",
                    "/compare [week=] [base=] [compare=] [plant=]": "Run scenario comparison.",
                    "/insights [week=] [scenario=] [plant=]": "Run analytics insights.",
                    "/rootcause item=<ITEM> [week=] [scenario=] [plant=]": "Run demand-supply root cause.",
                    "/table <table_name>": "Explain table definition, columns, and linkages.",
                },
                "examples": [
                    "/table by_if_snop_out_inddmdview",
                    "/validate week=202547 scenario=CONSTRAINED",
                    "/compare week=202547 base=BASE compare=CONSTRAINED",
                    "/rootcause item=100000000008 week=202547 scenario=CONSTRAINED plant=1004",
                ],
            },
            "note": "Use commands for power-mode execution while keeping natural language available.",
            "context_override": {
                "week_id": cmd_week,
                "scenario_id": cmd_scenario,
                "scope": cmd_scope,
            },
        }

    if cmd in {"summary", "datasets"}:
        inv = dataset_inventory(base_dir)
        largest_input = max(inv["input_files"], key=lambda x: x["rows"], default=None)
        largest_output = max(inv["output_files"], key=lambda x: x["rows"], default=None)
        return {
            "workflow": "Dataset Summary",
            "result": {
                "input_file_count": inv["input_file_count"],
                "output_file_count": inv["output_file_count"],
                "largest_input_file": largest_input["file"] if largest_input else None,
                "largest_output_file": largest_output["file"] if largest_output else None,
            },
            "note": "Summary reflects current snapshot files.",
            "context_override": {
                "week_id": cmd_week,
                "scenario_id": cmd_scenario,
                "scope": cmd_scope,
            },
        }

    if cmd in {"validate", "validation"}:
        return {
            "workflow": "Validation Gate",
            "result": run_validation(
                base_dir,
                cmd_week,
                cmd_scenario,
                cmd_scope,
                ["master_data", "bom", "parameters", "output_sanity"],
            ),
            "note": "Validation command executed.",
            "context_override": {
                "week_id": cmd_week,
                "scenario_id": cmd_scenario,
                "scope": cmd_scope,
            },
        }

    if cmd in {"compare", "scenario"}:
        base_sc = _get_arg(args, "base", "base_scenario")
        cmp_sc = _get_arg(args, "compare", "cmp", "compare_scenario")
        return {
            "workflow": "Scenario Comparison",
            "result": run_scenario_compare(
                base_dir,
                cmd_week,
                base_sc,
                cmp_sc,
                cmd_scope,
                ["unmet_demand", "capacity_utilization", "lateness"],
            ),
            "note": "Scenario comparison command executed.",
            "context_override": {
                "week_id": cmd_week,
                "scenario_id": cmd_scenario,
                "scope": cmd_scope,
            },
        }

    if cmd in {"insights", "analytics"}:
        return {
            "workflow": "Analytics Insights",
            "result": run_insights(base_dir, cmd_week, cmd_scenario, None, None, cmd_scope),
            "note": "Insights command executed.",
            "context_override": {
                "week_id": cmd_week,
                "scenario_id": cmd_scenario,
                "scope": cmd_scope,
            },
        }

    if cmd in {"rootcause", "root", "rca"}:
        demand_item = _get_arg(args, "item", "demand", "demand_item")
        if not demand_item and positional:
            demand_item = positional[0]
        if not demand_item:
            return {
                "workflow": "Root Cause Clarification",
                "clarification": {
                    "question": "Provide demand item. Example: /rootcause item=100000000008 week=202547 scenario=CONSTRAINED",
                },
                "context_override": {
                    "week_id": cmd_week,
                    "scenario_id": cmd_scenario,
                    "scope": cmd_scope,
                },
            }
        return {
            "workflow": "Root Cause",
            "result": run_root_cause(base_dir, cmd_week, cmd_scenario, demand_item, cmd_scope),
            "note": "Root-cause command executed.",
            "context_override": {
                "week_id": cmd_week,
                "scenario_id": cmd_scenario,
                "scope": cmd_scope,
            },
        }

    if cmd in {"table", "schema"}:
        table_query = " ".join(positional).strip() or _get_arg(args, "name", "table") or ""
        query = f"explain table {table_query}".strip()
        result = _run_table_explain_workflow(base_dir, query)
        result["context_override"] = {
            "week_id": cmd_week,
            "scenario_id": cmd_scenario,
            "scope": cmd_scope,
        }
        return result

    return {
        "workflow": "Command Clarification",
        "clarification": {
            "question": f"Unknown command '/{cmd}'. Use /help to list supported commands.",
        },
        "context_override": {
            "week_id": cmd_week,
            "scenario_id": cmd_scenario,
            "scope": cmd_scope,
        },
    }


_DOMAIN_CATALOG_MAP = {
    "Fulfillment": "Fulfillment",
    "Generation": "Generation",
    "DataHygiene": "Data Hygiene",
}


def _dispatch_by_intent(
    base_dir: Path,
    meta: Dict,
    week_id: Optional[str],
    scenario_id: Optional[str],
    scope: Dict,
) -> Dict:
    """
    Clean dispatcher driven by RouterAgent IntentMetadata.
    Replaces the old if/elif keyword chain.
    """
    intent = meta.get("intent", "conversational")
    entities = meta.get("entities") or {}
    domain_raw = meta.get("domain")
    resolved_item = entities.get("item")
    router_meta = {
        "intent": intent,
        "workflow": meta.get("workflow"),
        "domain": domain_raw,
        "confidence": meta.get("confidence"),
        "matched_terms": meta.get("matched_terms"),
        "conflict": meta.get("conflict"),
        "conflicting_intents": meta.get("conflicting_intents"),
        "entities": entities,
        "entity_sources": meta.get("entity_sources"),
        "missing_slots": meta.get("missing_slots"),
    }

    # ── clarification needed (missing required slot) ─────────────────────
    if meta.get("needs_clarification"):
        q_text = (meta.get("question") or "").lower()
        rc_terms = ("why", "drop", "late", "short", "early", "low", "change", "utiliz", "underload")
        # Use regex item extraction as fallback when router entities didn't capture the item
        item = resolved_item or _resolve_chat_item(meta.get("question", ""), None).get("selected_item")
        # For resource utilization queries, extract resource ID from question (e.g. RES01, RES_ETCH)
        if not item and any(kw in q_text for kw in ("utiliz", "capac", "underload", "overload", "res")):
            import re as _re
            res_match = _re.search(r'\b(RES[_\-]?[A-Z0-9]{1,15}|[A-Z]{2,6}[_\-]?[0-9]{1,6})\b',
                                   meta.get("question") or "", _re.IGNORECASE)
            if res_match:
                item = res_match.group(1).upper()
        if item and any(kw in q_text for kw in rc_terms):
            rc_data = run_root_cause(base_dir, week_id, scenario_id, item, scope)
            return {
                "workflow": "Root Cause Analysis",
                "result": rc_data,        # run_root_cause returns flat dict; wrap it here
                "router_metadata": router_meta,
            }
        return {
            "workflow": f"{meta.get('workflow', intent)} Clarification",
            "clarification": meta["clarification"],
            "router_metadata": router_meta,
        }

    # ── sql_query (Text-to-SQL Engineer) ─────────────────────────────────
    if intent == "sql_query":
        from .text_to_sql_agent import run_sql_query  # lazy import
        return run_sql_query(base_dir, meta.get("question", ""), week_id, scenario_id, scope)

    # ── bom_drill ────────────────────────────────────────────────────────
    if intent == "bom_drill":
        from .langgraph_bom import run_bom_drill
        result = run_bom_drill(base_dir, week_id, scenario_id, resolved_item, scope)
        result["router_metadata"] = router_meta
        return result

    # ── item_demand_supply ───────────────────────────────────────────────
    if intent == "item_demand_supply":
        result = _run_item_demand_supply_workflow(base_dir, week_id, scenario_id, resolved_item, scope)
        result["router_metadata"] = router_meta
        return result

    # ── domain focus (Fulfillment / Generation / Data Hygiene) ──────────
    if intent in {"domain_fulfillment", "domain_generation", "domain_data_hygiene"}:
        domain_name = _DOMAIN_CATALOG_MAP.get(domain_raw or "", "Data Hygiene")

        # Conflict: multiple domains matched → ask the planner to choose
        conflicting = meta.get("conflicting_intents") or []
        if meta.get("conflict") and any(i.startswith("domain_") for i in conflicting):
            domain_candidates = [domain_name] + [
                _DOMAIN_CATALOG_MAP.get(
                    (_DOMAIN_CATALOG_MAP.get(INTENT_CATALOG_DOMAIN_KEY(c), c)), c
                )
                for c in conflicting if c.startswith("domain_")
            ]
            return {
                "workflow": "Domain Focus Clarification",
                "clarification": {
                    "question": "Your question spans multiple domains. Which lens should I prioritize?",
                    "options": domain_candidates,
                    "guidance": {
                        "Fulfillment": "Service impact: unmet demand, backorders, OTIF/fill-rate.",
                        "Generation": "Plan creation: capacity, lead-time, calendar, policy.",
                        "Data Hygiene": "Data quality/input defects driving bad outputs.",
                    },
                },
                "router_metadata": router_meta,
            }
        return _run_domain_focus_workflow(base_dir, domain_name, week_id, scenario_id, scope)

    # ── table_explain ────────────────────────────────────────────────────
    if intent == "table_explain":
        question = meta.get("question", "")
        return _run_table_explain_workflow(base_dir, question)

    # ── validation ───────────────────────────────────────────────────────
    if intent == "validation":
        return {
            "workflow": "Validation Gate",
            "result": run_validation(
                base_dir, week_id, scenario_id, scope,
                ["master_data", "bom", "parameters", "output_sanity"],
            ),
            "note": "Validation is focused on data quality, referential integrity, and planning readiness.",
            "router_metadata": router_meta,
        }

    # ── summary ──────────────────────────────────────────────────────────
    if intent == "summary":
        inv = dataset_inventory(base_dir)
        largest_input = max(inv["input_files"], key=lambda x: x["rows"], default=None)
        largest_output = max(inv["output_files"], key=lambda x: x["rows"], default=None)
        return {
            "workflow": "Dataset Summary",
            "result": {
                "input_file_count": inv["input_file_count"],
                "output_file_count": inv["output_file_count"],
                "largest_input_file": largest_input["file"] if largest_input else None,
                "largest_output_file": largest_output["file"] if largest_output else None,
            },
            "note": "Summary reflects current by_input and by_output snapshots.",
            "router_metadata": router_meta,
        }

    # ── scenario compare ─────────────────────────────────────────────────
    if intent == "compare":
        return {
            "workflow": "Scenario Comparison",
            "result": run_scenario_compare(
                base_dir, week_id, None, None, scope,
                ["unmet_demand", "capacity_utilization", "lateness"],
            ),
            "note": "Provide exact base and compare SIMULATION_NAME values for strict scenario deltas.",
            "router_metadata": router_meta,
        }

    # ── insights ─────────────────────────────────────────────────────────
    if intent == "insights":
        return {
            "workflow": "Analytics Insights",
            "result": run_insights(base_dir, week_id, scenario_id, None, None, scope),
            "note": "Insights show trend behavior by workweek, month, and quarter.",
            "router_metadata": router_meta,
        }

    # ── root_cause ───────────────────────────────────────────────────────
    if intent == "root_cause":
        context = _resolve_context(base_dir, week_id, scenario_id)
        if not resolved_item:
            return {
                "workflow": "Root Cause Clarification",
                "clarification": {
                    "question": "Which demand ITEM should I evaluate?",
                    "expected_fields": ["ITEM", "Week ID (optional)", "Scenario ID (optional)", "Plant (optional)"],
                    "examples": [
                        "Check demand ITEM 100000000008",
                        "Why is ITEM 100000000008 unmet for week 202547 and scenario CONSTRAINED?",
                    ],
                },
                "context": context,
                "router_metadata": router_meta,
            }
        # Validate item exists in demand data before committing to root cause
        demand_evidence = _item_demand_evidence(
            base_dir, context["week_id"], context["scenario_id"], resolved_item, scope
        )
        item_source = (entities.get("item") and (meta.get("entity_sources") or {}).get("item")) or "question"
        if item_source == "question" and not demand_evidence["is_demand_item"]:
            return {
                "workflow": "Root Cause Clarification",
                "clarification": {
                    "question": f"I found ITEM {resolved_item}. Should I treat it as the demand item?",
                    "examples": [
                        f"Yes, use {resolved_item}",
                        f"Use {resolved_item} for plant 1004",
                        "Use demand ITEM 100000000004 instead",
                    ],
                },
                "demand_evidence": demand_evidence,
                "context": context,
                "router_metadata": router_meta,
            }
        return {
            "workflow": "Root Cause",
            "result": run_root_cause(base_dir, week_id, scenario_id, resolved_item, scope),
            "note": "Root-cause analysis uses demand/supply/resource linkage evidence.",
            "router_metadata": router_meta,
        }

    # ── log_reader ───────────────────────────────────────────────────────
    if intent == "log_reader":
        question = meta.get("question", "")
        log_content = entities.get("log_content")  # optional separate log text
        result = run_log_reader(base_dir, question, log_content, week_id, scenario_id, scope)
        result["router_metadata"] = router_meta
        return result

    # ── vision_query ─────────────────────────────────────────────────────
    if intent == "vision_query":
        question = meta.get("question", "")
        image_base64 = entities.get("image_base64", "")
        result = run_vision_query(base_dir, question, image_base64, week_id, scenario_id, scope)
        result["router_metadata"] = router_meta
        return result

    # ── conversational fallback ──────────────────────────────────────────
    return {"workflow": "Conversational Copilot", "router_metadata": router_meta}


def INTENT_CATALOG_DOMAIN_KEY(intent_name: str) -> str:
    """Map router intent name to INTENT_CATALOG domain string."""
    from .router_agent import INTENT_CATALOG
    return (INTENT_CATALOG.get(intent_name) or {}).get("domain") or ""


def _run_chat_workflow_if_needed(
    base_dir: Path,
    question: str,
    week_id: Optional[str],
    scenario_id: Optional[str],
    scope: Dict,
    history: Optional[List[Dict[str, str]]] = None,
) -> Dict:
    from .router_agent import route_question
    meta = route_question(question, history, week_id, scenario_id, scope)
    meta["question"] = question  # make question available to dispatcher
    result = _dispatch_by_intent(base_dir, meta, week_id, scenario_id, scope)

    # Safety-net: if the router produced no workflow result but the question clearly
    # asks about demand fulfillment for a specific item, run the item_demand_supply
    # workflow directly rather than returning an empty conversational response.
    if result.get("workflow") in {None, "Conversational Copilot"} and not result.get("result"):
        ql = (question or "").lower()
        demand_terms = [
            "demand", "met", "unmet", "fulfill", "fulfil", "supply",
            "was met", "not met", "demand status", "check demand",
        ]
        item = (meta.get("entities") or {}).get("item")
        if not item:
            item = _resolve_chat_item(question, history).get("selected_item")
        if item and any(term in ql for term in demand_terms):
            result = {
                "workflow": "Item Demand Supply",
                "result": _run_item_demand_supply_workflow(base_dir, week_id, scenario_id, item, scope).get("result"),
                "note": "Auto-dispatched to Item Demand Supply based on detected item and demand question.",
                "router_metadata": result.get("router_metadata"),
            }

    # Safety-net for root cause clarification — if item is known, run root cause directly
    if "Clarification" in (result.get("workflow") or "") and not result.get("result"):
        ql = (question or "").lower()
        rc_terms = ["why", "drop", "late", "short", "early", "low", "change", "utiliz", "underload"]
        item = (meta.get("entities") or {}).get("item") or _resolve_chat_item(question, history).get("selected_item")
        if item and any(term in ql for term in rc_terms):
            rc_data = run_root_cause(base_dir, week_id, scenario_id, item, scope)
            result = {
                "workflow": "Root Cause Analysis",
                "result": rc_data,
                "note": "Auto-dispatched to Root Cause analysis.",
                "router_metadata": result.get("router_metadata"),
            }

    return result


def _build_item_demand_supply_reply(workflow_result: Dict) -> Optional[str]:
    stats = (workflow_result or {}).get("Demand vs Supply Stats") or {}
    item = (workflow_result or {}).get("Item")
    demand = stats.get("demand_qty_total")
    scheduled = stats.get("scheduled_qty_total")
    unmet = stats.get("unmet_qty")
    status = stats.get("meet_status")

    if item is None and all(value is None for value in [demand, scheduled, unmet, status]):
        return None

    return (
        f"Item {item}: Demand={demand}, Scheduled Supply={scheduled}, Unmet={unmet}, Status={status}. "
        "I also included pegged supply, planned supply breakdown, and constraint signals in details."
    )


def build_grounded_chat_prompt(
    base_dir: Path,
    question: str,
    week_id: Optional[str],
    scenario_id: Optional[str],
    scope: Dict,
    history: Optional[List[Dict[str, str]]] = None,
) -> Tuple[str, str, Dict]:
    """
    Run workflow analysis + RAG + grounding and return (system_prompt, grounded_prompt, meta).
    No LLM call happens here — pure data gathering, safe to run before streaming.
    """
    q = (question or "").strip()

    parsed_command = _parse_chat_command(q)
    effective_week = week_id
    effective_scenario = scenario_id
    effective_scope = dict(scope or {})

    if parsed_command.get("is_command"):
        workflow_payload = _execute_chat_command(base_dir, parsed_command, week_id, scenario_id, effective_scope)
        override = workflow_payload.get("context_override") or {}
        effective_week = override.get("week_id", effective_week)
        effective_scenario = override.get("scenario_id", effective_scenario)
        effective_scope = override.get("scope", effective_scope)
    else:
        workflow_payload = _run_chat_workflow_if_needed(base_dir, q, week_id, scenario_id, effective_scope, history=history)

    context = _resolve_context(base_dir, effective_week, effective_scenario)
    grounding = _build_chat_grounding(base_dir, q, context, effective_scope)

    rag_evidence = None
    try:
        if LLM_CONFIG["provider"] == "openvino":
            from .rag_openvino import get_openvino_rag_status, query_openvino_rag
            if get_openvino_rag_status(base_dir).get("status") == "ready":
                rag_evidence = query_openvino_rag(base_dir, q, week_id=context.get("week_id"),
                                                  scenario_id=context.get("scenario_id"), top_k=6)
        else:
            ensure_rag_index(base_dir, refresh_hours=24)
            item_hint = _resolve_chat_item(q, history).get("selected_item")
            rag_evidence = query_rag(base_dir, q, top_k=6,
                                     week_id=context.get("week_id"),
                                     scenario_id=context.get("scenario_id"),
                                     site=(effective_scope or {}).get("site"),
                                     item_id=item_hint)
    except Exception:
        pass

    workflow_name = workflow_payload.get("workflow") or "Conversational Copilot"
    workflow_result = workflow_payload.get("result")
    workflow_note = workflow_payload.get("note")
    clarification = workflow_payload.get("clarification")

    system_prompt = (
        "You are a senior Intel Foundry Supply Planning expert with deep knowledge of "
        "Blue Yonder Enterprise Supply Planning (BY ESP). "
        "Answer like a trusted colleague — directly, concisely, and using the actual numbers from the data provided. "
        "Skip generic disclaimers. Never say 'I cannot access the data' — the data is in the prompt. "
        "Use planning terminology naturally (UNMET, DMDITEM, SUPPLYLOC, BOM, etc.) only when it adds clarity. "
        "If a number answers the question, lead with that number. "
        "Separate what is confirmed from what is inferred."
    )

    prompt_sections: List[str] = []
    prompt_sections.append(f"## User Question\n{q}")
    prompt_sections.append(f"## Workflow Identified\n{workflow_name}")
    prompt_sections.append(f"## Resolved Planning Context\nWeek: {context.get('week_id')} | Scenario: {context.get('scenario_id')}")

    if workflow_result is not None:
        prompt_sections.append(
            f"## Grounded Planning Data (use this as primary evidence)\n{json.dumps(workflow_result, ensure_ascii=True)}"
        )

    if rag_evidence is not None:
        hits = (rag_evidence or {}).get("hits", [])[:4]
        if hits:
            prompt_sections.append(f"## RAG Evidence (top hits)\n{json.dumps(hits, ensure_ascii=True)}")

    if workflow_result is None:
        trimmed_grounding = {
            "context_resolution": grounding.get("context_resolution"),
            "matched_tables": grounding.get("matched_tables", [])[:5],
            "key_linkages": grounding.get("key_linkages", [])[:5],
        }
        prompt_sections.append(f"## Domain Grounding\n{json.dumps(trimmed_grounding, ensure_ascii=True)}")

    if clarification:
        prompt_sections.append(f"## Clarification Payload\n{json.dumps(clarification, ensure_ascii=True)}")
    if workflow_note:
        prompt_sections.append(f"## Workflow Note\n{workflow_note}")

    prompt_sections.append(
        "## Instructions\n"
        "Answer the planner's question directly using the data above. "
        "Lead with the actual answer (numbers, status, items). "
        "Explain why briefly if useful. "
        "End with one follow-up question only if it would materially help the planner. "
        "Do not use numbered lists unless listing multiple items. Keep it under 150 words."
    )
    if workflow_name.lower() == "item demand supply":
        prompt_sections.append(
            "For this demand query, state clearly: total demand, scheduled supply, unmet quantity, and whether demand was fully met, partially met, or not met."
        )

    meta = {
        "workflow": workflow_name,
        "workflow_result": workflow_result,
        "context": context,
        "rag_evidence": rag_evidence,
        "clarification": clarification,
        "follow_ups": _suggest_followups(workflow_name, q),
        "history_window": (history or [])[-10:],
        "grounding": grounding,
        "workflow_payload": workflow_payload,
    }
    return system_prompt, "\n\n".join(prompt_sections), meta


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
    if not q:
        return {
            "Assistant Reply": "Please type your question so I can help.",
            "Suggested Next Step": "Try: 'Explain linkage between inddmdview and inddmdlink for the latest scenario'.",
        }

    system_prompt, grounded_prompt, meta = build_grounded_chat_prompt(
        base_dir, q, week_id, scenario_id, scope, history=history
    )
    workflow_payload = meta["workflow_payload"]
    context = meta["context"]
    workflow_name = meta["workflow"]
    workflow_result = meta["workflow_result"]
    clarification = meta["clarification"]
    follow_ups = meta["follow_ups"]
    rag_evidence = meta["rag_evidence"]
    history_window = meta["history_window"]
    grounding = meta["grounding"]

    parsed_command = _parse_chat_command(q)
    effective_scope = dict(scope or {})

    # Re-derive rag_status for the response metadata
    rag_status = {"status": "ok", "backend": LLM_CONFIG["provider"]}

    grounding["rag"] = {
        "status": rag_status,
        "hits": (rag_evidence or {}).get("hits", []),
    }

    effective_week = context.get("week_id")
    effective_scenario = context.get("scenario_id")

    if llm_enabled:
        conversational_reply = _ollama_chat_with_model(
            grounded_prompt,
            system_prompt,
            llm_model,
            history=history_window,
        )
        if conversational_reply:
            judge_review = _judge_llm_output(
                q, conversational_reply, workflow_name, context,
                workflow_result if isinstance(workflow_result, dict) else None,
                llm_model,
            )
            response = {
                "Assistant Reply": conversational_reply,
                "Workflow": workflow_name,
                "Context Resolution": context,
                "Suggested Follow-ups": follow_ups,
                "LLM Provider": LLM_CONFIG["provider"].capitalize(),
                "LLM Model": (llm_model or LLM_CONFIG["model"]).strip() or LLM_CONFIG["model"],
            }
            if workflow_result is not None:
                response["Grounded Result"] = workflow_result
            if clarification is not None:
                response["Clarification Needed"] = clarification
            if rag_evidence is not None:
                response["RAG Evidence"] = rag_evidence
            if judge_review is not None:
                response["LLM Judge Review"] = judge_review
            if workflow_payload.get("router_metadata"):
                response["Router Metadata"] = workflow_payload["router_metadata"]
            return response

    fallback_reply = "I can answer BY ESP planning questions in natural language and run validation, compare, root-cause, and insights workflows."
    if workflow_name.lower() == "item demand supply" and isinstance(workflow_result, dict):
        fallback_reply = _build_item_demand_supply_reply(workflow_result) or fallback_reply

    fallback = {
        "Assistant Reply": fallback_reply,
        "Workflow": workflow_name,
        "Context Resolution": context,
        "Suggested Follow-ups": follow_ups,
        "Knowledge Areas": [
            "BY ESP LP optimization mechanics",
            "Input/output table definitions and columns",
            "Table linkage and referential integrity",
            "Planner-focused explainability",
        ],
        "Suggested Prompts": [
            "Explain LP optimization objective and constraints in BY ESP",
            "How are inddmdview, inddmdlink, and planorder linked?",
            "Check referential integrity between SKU and item/location/customer masters",
            "Why is demand unmet for ITEM 100000000008?",
            "/help",
            "/table by_if_snop_out_inddmdview",
        ],
    }
    if workflow_result is not None:
        fallback["Grounded Result"] = workflow_result
    if rag_evidence is not None:
        fallback["RAG Evidence"] = rag_evidence
    if clarification is not None:
        fallback["Clarification Needed"] = clarification
    if workflow_note:
        fallback["Note"] = workflow_note
    return fallback
