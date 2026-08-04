# BY ESP Planning Model Analysis (Grounded to Current Files)

## Scope and Grounding

This analysis is grounded in actual CSV headers and row counts found in `by_input` and `by_output`.

Observed data characteristics:
- Input files are mostly pipe-delimited (`|`).
- Output files are mostly pipe-delimited, except `by_if_snop_out_por-*.csv` which is comma-delimited.
- `if_snop_calattribute-*` includes extra `Unnamed:*` columns.
- `if_snop_purchmethod-*` includes header encoding noise (`U_PLANMODULEÂ`).
- Some requested entities are not present in the folder snapshot: `schedrcptsdtl`, `vehicleload`, `vechileloadline`.

## 1. Inferred BY ESP Business Data Model

### Core planning entities
- Item master: `if_snop_items`
- Location master: `if_snop_locations`
- Customer master: `if_snop_customer`
- SKU policy grain: `if_snop_sku` (`ITEM`, `LOC`, `CUST`)
- Time/capacity calendars: `if_snop_calendars`, `if_snop_calpattern`, `if_snop_calattribute`

### Supply generation structures
- Material conversion: `if_snop_billofmaterials`, `if_snop_altbillofmaterials`
- Production recipe: `if_snop_productionmethod`, `if_snop_productionstep`, `if_snop_altproductionstep`
- Procurement: `if_snop_purchmethod`
- Sourcing transfers: `if_snop_sourcing`, `if_snop_network`
- Resource/capacity: `if_snop_res`

### Demand and starting-state structures
- Customer demand orders: `if_snop_customerorder`
- Forecast demand: `if_snop_dfutoskufcst`
- Initial inventory: `if_snop_inventory`
- Scheduled receipts/firm supply: `if_snop_schedrcpts`
- Supersession/substitution: `if_snop_supersession`

### Solver decision and explainability outputs
- Independent demand status: `by_if_snop_out_inddmdview`
- Pegging/links: `by_if_snop_out_inddmdlink`, `by_if_snop_out_orderlink`
- Dependent demand explosion: `by_if_snop_out_depdmdstatic`
- New supply decisions: `by_if_snop_out_planorder`, `by_if_snop_out_planpurch`, `by_if_snop_out_planarriv`
- Resource loading/projections: `by_if_snop_out_resloaddetail`, `by_if_snop_out_resprojstatic`, `by_if_snop_out_resloadinddmdlink`
- Exceptions/constraint violations: `by_if_snop_out_skuexception`, `by_if_snop_out_resexception`, `by_if_snop_out_exceptionorderrelation`
- SKU time-bucket KPI state: `by_if_snop_out_skuprojstatic`, `by_if_snop_out_skustatstatic`
- Forecast order materialization: `by_if_snop_out_fcstorder`
- JIT-style view: `by_if_snop_out_jit`

## 2. Relationships Between Files (BY ESP-specific)

### Master-data relationships
- `if_snop_sku.(ITEM,LOC,CUST)` -> `if_snop_items.ITEM`, `if_snop_locations.LOC`, `if_snop_customer.CUST`
- `if_snop_skueffinventoryparam.(ITEM,LOC)` -> `if_snop_sku.(ITEM,LOC)`
- `if_snop_res.LOC` -> `if_snop_locations.LOC`
- `if_snop_res.CAL` -> `if_snop_calendars.CAL`

### Material and production relationships
- `if_snop_billofmaterials.(ITEM,LOC,BOMNUM)` -> `if_snop_productionmethod.(ITEM,LOC,BOMNUM)`
- `if_snop_altbillofmaterials.(ITEM,SUBORD,LOC,BOMNUM)` -> `if_snop_billofmaterials.(ITEM,SUBORD,LOC,BOMNUM)`
- `if_snop_productionstep.(ITEM,LOC,PRODUCTIONMETHOD)` -> `if_snop_productionmethod.(ITEM,LOC,PRODUCTIONMETHOD)`
- `if_snop_altproductionstep.(ITEM,LOC,PRODUCTIONMETHOD,PRIMARYSTEPNUM)` -> `if_snop_productionstep`
- `if_snop_productionstep.RES` -> `if_snop_res.RES` (+ `LOC` alignment)

### Sourcing and logistics relationships
- `if_snop_sourcing.(ITEM,SOURCE,DEST,TRANSMODE)` -> `if_snop_network.(SOURCE,DEST,TRANSMODE)`
- `if_snop_sourcing.(SOURCE,DEST)` -> `if_snop_locations.LOC`

### Demand relationships
- `if_snop_customerorder.(ITEM,LOC,CUST)` -> masters and SKU policy grain
- `if_snop_dfutoskufcst.ITEM` with `SKULOC` and `DMDGROUP` ties to SKU and demand grouping

### Input-output lineage relationships
- `by_if_snop_out_inddmdview.(ITEM,LOC,DMDTYPE,SEQNUM)` <-> `by_if_snop_out_inddmdlink.(DMDITEM,DMDLOC,DMDTYPE,DMDSEQNUM)`
- `by_if_snop_out_inddmdlink` links demand to supply (`SUPPLYTYPE`, `SUPPLYITEM`, `SUPPLYLOC`, `SUPPLYSEQNUM`)
- `by_if_snop_out_orderlink` provides pegging at order level for similar demand/supply keys
- `by_if_snop_out_planorder.(ITEM,LOC,SEQNUM)` referenced by link tables via supply sequence
- `by_if_snop_out_planpurch.(ITEM,LOC,SEQNUM)` referenced by link tables via supply sequence
- `by_if_snop_out_planarriv.(ITEM,SOURCE,DEST,SEQNUM)` mapped to transfer supplies
- `by_if_snop_out_resloaddetail.(ITEM,RES,LOC,SUPPLYSEQNUM,SUPPLYTYPE)` ties generated supply to resource load
- `by_if_snop_out_resloadinddmdlink` bridges demand, supply, and resource load in one table
- `by_if_snop_out_depdmdstatic` gives exploded dependent demand against parent supply/order context

## 3. File Classification by Planning Role

### Master Data
- `if_snop_items`
- `if_snop_locations`
- `if_snop_customer`
- `if_snop_res`
- `if_snop_calendars`
- `if_snop_calpattern`
- `if_snop_calattribute`
- `if_snop_network`

### Transaction Data (Demand/Supply Inputs)
- `if_snop_customerorder`
- `if_snop_dfutoskufcst`
- `if_snop_inventory`
- `if_snop_schedrcpts`

### Planning Parameters / Policy
- `if_snop_sku`
- `if_snop_skueffinventoryparam`
- `if_snop_billofmaterials`
- `if_snop_altbillofmaterials`
- `if_snop_productionmethod`
- `if_snop_productionstep`
- `if_snop_altproductionstep`
- `if_snop_purchmethod`
- `if_snop_sourcing`
- `if_snop_supersession`

### Solver Outputs (Decisions and Status)
- `by_if_snop_out_inddmdview`
- `by_if_snop_out_inddmdlink`
- `by_if_snop_out_orderlink`
- `by_if_snop_out_depdmdstatic`
- `by_if_snop_out_planorder`
- `by_if_snop_out_planpurch`
- `by_if_snop_out_planarriv`
- `by_if_snop_out_fcstorder`
- `by_if_snop_out_jit`
- `by_if_snop_out_skuprojstatic`
- `by_if_snop_out_skustatstatic`

### Constraint Outputs
- `by_if_snop_out_resexception`
- `by_if_snop_out_skuexception`
- `by_if_snop_out_exceptionorderrelation`
- `by_if_snop_out_resprojstatic` (capacity saturation evidence)
- `by_if_snop_out_resloaddetail` and `by_if_snop_out_resloadinddmdlink` (capacity burden attribution)

## 4. BY ESP-Optimized Intent Taxonomy

Solver-first intents:
1. `DemandStatusLookup`
   - Independent demand status, lateness, partial, unmet.
2. `DemandSupplyPeggingExplain`
   - Demand -> supply linkage and pegged quantities.
3. `CapacityConstraintExplain`
   - Resource overload, utilization, exception drivers.
4. `MaterialConstraintExplain`
   - BOM/subcomponent shortages and dependent-demand propagation.
5. `PlanOrderDecisionExplain`
   - Why planned production orders were or were not created.
6. `PlanPurchDecisionExplain`
   - Why planned purchase orders were or were not created.
7. `TransferDecisionExplain`
   - Why plan arrivals/transfers were or were not created.
8. `InventoryProjectionExplain`
   - Projected OH, stockout windows, coverage under constraints.
9. `AllocationPriorityExplain`
   - How priority, customer, demand group affected fulfillment.
10. `ForecastConsumptionExplain`
   - Forecast consumption and interaction with customer orders.
11. `ScenarioSolveComparison`
   - Solve version/simulation comparison using output deltas.
12. `InputDataValidation`
   - Data quality/RI/parameter integrity checks.

Fallback intents:
13. `MasterDataLookup`
14. `ParameterLookup`
15. `Other`

## 5. Semantic Layer Mapping (Business Concept -> File -> Columns)

1. Independent Demand -> `by_if_snop_out_inddmdview` -> `ITEM`, `LOC`, `DMDTYPE`, `SEQNUM`, `NEEDDATE`, `QTY`, `SCHEDQTY`, `SCHEDSTATUS`, `CUST`, `DMDGROUP`
2. Demand-Supply Pegging -> `by_if_snop_out_inddmdlink` -> `DMDITEM`, `DMDLOC`, `DMDSEQNUM`, `SUPPLYTYPE`, `SUPPLYITEM`, `SUPPLYLOC`, `SUPPLYSEQNUM`, `DMDPEGQTY`, `SUPPLYPEGQTY`
3. Order-Level Pegging -> `by_if_snop_out_orderlink` -> `DMDSEQNUM`, `SUPPLYSEQNUM`, `PEGQTY`, `ORDERID`, `SHIPDATE`
4. Dependent Demand -> `by_if_snop_out_depdmdstatic` -> `ITEM`, `LOC`, `QTY`, `PARENT`, `PARENTORDERNUM`, `PARENTORDERTYPE`, `EARLIESTNEEDDATE`
5. Planned Production -> `by_if_snop_out_planorder` -> `ITEM`, `LOC`, `SEQNUM`, `STARTDATE`, `SCHEDDATE`, `QTY`, `PRODUCTIONMETHOD`
6. Planned Purchase -> `by_if_snop_out_planpurch` -> `ITEM`, `LOC`, `SEQNUM`, `NEEDDATE`, `STARTDATE`, `SCHEDDATE`, `QTY`, `PURCHMETHOD`
7. Planned Transfer -> `by_if_snop_out_planarriv` -> `ITEM`, `SOURCE`, `DEST`, `SEQNUM`, `SCHEDSHIPDATE`, `SCHEDARRIVDATE`, `QTY`, `SOURCING`, `TRANSMODE`
8. Resource Load Detail -> `by_if_snop_out_resloaddetail` -> `RES`, `LOC`, `ITEM`, `SUPPLYTYPE`, `SUPPLYSEQNUM`, `WHENLOADED`, `LOADQTY`, `SUPPLYQTY`, `DMDORDERTYPE`
9. Resource Demand Link -> `by_if_snop_out_resloadinddmdlink` -> `RES`, `SUPPLYSEQNUM`, `DMDSEQNUM`, `DMDITEM`, `CAPACITYPEGQTY`, `INDDMDPRIORITY`
10. Resource Projection -> `by_if_snop_out_resprojstatic` -> `RES`, `LOC`, `STARTDATE`, `AVAILCAP`, `MPTOTLOAD`, `PCTUSED`, `RESCOUNTEXCEPTION`
11. Resource Exceptions -> `by_if_snop_out_resexception` -> `EXCEPTION`, `RES`, `LOC`, `ITEM`, `OVERUTILQTY`, `UTILPCT`, `MINVAL`, `MAXVAL`, `SCHEDVAL`
12. SKU Exceptions -> `by_if_snop_out_skuexception` -> `EXCEPTION`, `ITEM`, `LOC`, `SEVERITY`, `VIOLATIONVAL`, `PRODUCTIONMETHOD`, `PURCHMETHOD`, `SOURCING`
13. Inventory Projection -> `by_if_snop_out_skuprojstatic` -> `ITEM`, `LOC`, `STARTDATE`, `PROJOH`, `PROJAVAIL`, `TOTDMD`, `TOTSUPPLY`, `INVENTORY`, `UNMET metrics`
14. Stockout/Coverage Stats -> `by_if_snop_out_skustatstatic` -> `CONSTRSTOCKOUTDATE`, `CONSTRSTOCKOUTQTY`, `CONSTRSTOCKOUTDUR`, `MINCONSTRCOVDUR`, `MAXCONSTRPROJOH`
15. Forecast Order -> `by_if_snop_out_fcstorder` -> `ITEM`, `LOC`, `DMDGROUP`, `NEEDDATE`, `QTY`, `CONSUMEDQTY`, `MAXLATEDUR`
16. Customer Orders Input -> `if_snop_customerorder` -> `ORDERID`, `ITEM`, `LOC`, `CUST`, `QTY`, `MAXLATEDUR`, `STATUS`, `FCSTSW`
17. Forecast Input -> `if_snop_dfutoskufcst` -> `ITEM`, `SKULOC`, `DMDGROUP`, `STARTDATE`, `TOTFCST`, `TYPE`, `DUR`
18. Inventory Input -> `if_snop_inventory` -> `ITEM`, `LOC`, `QTY`, `AVAILDATE`
19. BOM -> `if_snop_billofmaterials` -> `ITEM`, `SUBORD`, `LOC`, `BOMNUM`, `DRAWQTY`, `YIELDFACTOR`, `OFFSET`
20. Production Method/Step -> `if_snop_productionmethod` + `if_snop_productionstep` -> `LEADTIME`, `PRIORITY`, `PRODRATE`, `PRODDUR`, `RES`

## 6. Required Files by Explainability Question Type

### Capacity Constraints
Primary solver outputs:
- `by_if_snop_out_resprojstatic`
- `by_if_snop_out_resexception`
- `by_if_snop_out_resloaddetail`
- `by_if_snop_out_resloadinddmdlink`
Supporting input parameters:
- `if_snop_res`
- `if_snop_productionstep`
- `if_snop_productionmethod`
- `if_snop_calendars`, `if_snop_calpattern`, `if_snop_calattribute`

### Material Constraints
Primary solver outputs:
- `by_if_snop_out_depdmdstatic`
- `by_if_snop_out_inddmdlink`
- `by_if_snop_out_skuexception`
Supporting inputs:
- `if_snop_billofmaterials`, `if_snop_altbillofmaterials`
- `if_snop_inventory`
- `if_snop_schedrcpts`

### Unmet Demand
Primary solver outputs:
- `by_if_snop_out_inddmdview`
- `by_if_snop_out_inddmdlink`
- `by_if_snop_out_orderlink`
Supporting outputs:
- `by_if_snop_out_skuprojstatic`
- `by_if_snop_out_exceptionorderrelation`

### Inventory Shortages
Primary solver outputs:
- `by_if_snop_out_skustatstatic`
- `by_if_snop_out_skuprojstatic`
Supporting inputs:
- `if_snop_inventory`
- `if_snop_skueffinventoryparam`

### Production Decisions
Primary solver outputs:
- `by_if_snop_out_planorder`
- `by_if_snop_out_resloaddetail`
- `by_if_snop_out_inddmdlink`
Supporting inputs:
- `if_snop_productionmethod`
- `if_snop_productionstep`
- `if_snop_billofmaterials`

### Allocation Decisions
Primary solver outputs:
- `by_if_snop_out_inddmdview`
- `by_if_snop_out_inddmdlink`
- `by_if_snop_out_orderlink`
Supporting inputs:
- `if_snop_sku` (policy flags, allocation horizons)
- `if_snop_customerorder` (priority-like demand attributes)

### Why-demand-not-met
Primary solver outputs:
- `by_if_snop_out_inddmdview` (status and scheduled quantity)
- `by_if_snop_out_inddmdlink` (supply pegging deficits)
- `by_if_snop_out_resexception` and `by_if_snop_out_skuexception` (constraint evidence)
- `by_if_snop_out_depdmdstatic` (upstream component constraints)

### Why-plan-generated / not-generated
Primary solver outputs:
- `by_if_snop_out_planorder`, `by_if_snop_out_planpurch`, `by_if_snop_out_planarriv`
- `by_if_snop_out_inddmdlink` (demand pull)
- `by_if_snop_out_resprojstatic` / `by_if_snop_out_resexception` (capacity pushback)
Supporting inputs:
- Methods (`if_snop_productionmethod`, `if_snop_purchmethod`, `if_snop_sourcing`)
- Policy (`if_snop_sku`, `if_snop_skueffinventoryparam`)

## 7. Proposed Specialized Agents

### Constraint Agent
- Mission: Explain active constraints and violations.
- Primary sources: `resexception`, `skuexception`, `resprojstatic`, `resloaddetail`.
- Outputs: ranked constraints, violation magnitudes, impacted items/orders.

### Solver Explainability Agent
- Mission: Build end-to-end demand->supply->resource explanation.
- Primary sources: `inddmdview`, `inddmdlink`, `orderlink`, `resloadinddmdlink`, `depdmdstatic`.
- Outputs: confirmed cause chain, confidence, missing evidence.

### Inventory Agent
- Mission: Explain projected inventory, stockout windows, coverage.
- Primary sources: `skuprojstatic`, `skustatstatic`.
- Supporting: `inventory`, `skueffinventoryparam`, `schedrcpts`.

### Supply Agent
- Mission: Explain production/purchase/transfer decisions.
- Primary sources: `planorder`, `planpurch`, `planarriv`, `inddmdlink`.
- Supporting: `productionmethod`, `purchmethod`, `sourcing`, `network`.

### Recommendation Agent
- Mission: Propose corrective actions constrained by evidence.
- Inputs: outputs from the four agents above.
- Rule: recommendations must reference explicit violated constraints or parameter levers.

## 8. Query Catalog

See `BY_ESP_QUERY_CATALOG.csv` for 100 BY ESP planner questions mapped to intents and source files.

## 9. Solver-First Retrieval Policy

Priority order for answering planner questions:
1. Solver output tables (`by_if_snop_out_*`) for decisions and outcomes.
2. Input policy/master files only to explain why outputs happened.
3. RAG narrative only for augmentation, never as source of truth when solver outputs exist.

Operational routing rule:
- If required output table exists for intent, force SQL/dataframe retrieval from output table first.
- Use RAG only when:
  - user asks conceptual/documentation question, or
  - required structured output rows are missing.

## 10. Data-Groundedness and Quality Guardrails

Hard guardrails:
- Never claim root cause without citing output evidence from link/exception/projection tables.
- Separate confirmed evidence vs hypotheses.
- Include simulation context keys (`CAPTURE_WK`, `SIMULATION_NAME`, `SOLVE_VERSION`) in every answer payload.
- Flag delimiter/schema anomalies before query execution:
  - `by_if_snop_out_por` comma-delimited unlike others.
  - `if_snop_calattribute` extra unnamed columns.
  - `if_snop_purchmethod` header encoding artifact.
