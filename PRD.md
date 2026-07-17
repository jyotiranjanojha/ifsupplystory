Business Context
Intel Foundry Supply Planning spend significant time manually gathering and synthesizing planning data for understanding and explanability. Analysts search through Blue Yonder Supply Planning system and Intel Foundry Planning Data Hub for the data to access and build report for explanability of the planning outcome. Blue Yonder Enterprise Supply Planning use LP OPT based Solver to generate Plan. Interl Foundry Planning Data Hub is the main data source for all data inputs sent to BY ESP. All data inputs are exposed as view in Intel Foundry Planning Data Hub. BY ESP take all the input data and uses to run the solve and generate output which are sent back to Intel Foundry Planning Data Hub.

The challenge is that planning team or Intel Foundry Planning Data Hub team or Blue Yonder Enterprise Supply Planning Team spend a good amount of time to explain why demand is meet, why demand is not meet, and various different queries which is time consuming and takes writing intensive query between input and output and explaining the geneology, lineage and reason. The Supply Planning process is a weekly process. There could be multiple facts because Master Data setup was missing or Broken BOM or some parameter was missing. All data input or output resides in Intel Foundry Planning Data Hub which is built on Snowflake

A well-desing agentic system should be able to read both input and output and answer any query any user can have. This is the core of Agentic RAG.

Objective
Build an end-to-end Agentic RAG system which user can interact that:

Reads both input and output data files
Validates the input data
Validates the output data
Have intelligence to answer any queries with respect to Master Data or Output or any functional queries
System should be grounded to use the data supplied
System can train itself with the data since every week new data set will be there
Within each Week system can use multiple scenario based output
Since all data is hosted on Intel Foundry Planning Data Hub which is built on Snowflake, system can read from Snowflake or read csv file manually uplaoded or read from sharepath

Solution Approach:

The optimal solution is a Multi-Agent Hybrid RAG Architecture consisting of:

Snowflake as the single source of truth
Graph RAG for genealogy and lineage traversal
SQL RAG for structured planning data retrieval
Validation Agent for master data/BOM/parameter checks
Root Cause Agent for planning explainability
Scenario Comparison Agent for weekly plan analysis
Teams-based Planning Copilot for natural language interaction

+----------------------------------------------------+
|                User / Planner                      |
+---------------------+------------------------------+
                      |
                      v
+----------------------------------------------------+
|             Supply Planning Copilot                |
|                Agentic RAG Layer                   |
+----------------------------------------------------+
      |            |              |            |
      v            v              v            v

 Data Agent   Validation Agent  Root Cause  Scenario Agent
                                 Agent

      |            |              |            |
      -------------------------------------------
                          |
                          v

+----------------------------------------------------+
|             Semantic Planning Layer                |
|                                                    |
|  Vector Store                                     |
|  Knowledge Graph                                  |
|  Business Rules Repository                        |
|  Planning Metadata Catalog                        |
+----------------------------------------------------+
                          |
                          v

+----------------------------------------------------+
|            Intel Foundry Planning Hub             |
|                  Snowflake                         |
+----------------------------------------------------+
                          |
              -----------------------
              |                     |
              v                     v

      Input Data Views         Output Data Views

              |                     |
              v                     v

      Blue Yonder ESP      Weekly Scenarios