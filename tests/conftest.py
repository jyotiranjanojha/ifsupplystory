import os

# Ensure analyzer startup validation has a valid default semantic mode during test collection.
os.environ.setdefault("SEMANTIC_MODE", "legacy")

# Clear deprecated semantic flags that would intentionally fail startup validation.
for _flag in [
    "IFSP_SEMANTIC_RETRIEVAL_MODE",
    "IFSP_SEMANTIC_ROUTER_MODE",
    "IFSP_SEMANTIC_FILE_DISCOVERY_MODE",
    "IFSP_SEMANTIC_KPI_SELECTOR_MODE",
    "IFSP_SOLVER_EXPLAINABILITY_PLANNER_MODE",
    "IFSP_RECOMMENDATION_RETRIEVAL_PLANNER_MODE",
]:
    os.environ.pop(_flag, None)
