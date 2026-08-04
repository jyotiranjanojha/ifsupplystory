# Phase 2: Hybrid Structured Data + RAG Architecture

## Overview

This design combines deterministic structured-data workflows with document-grounded retrieval.

## High-Level Architecture

```mermaid
flowchart LR
    Q[Planner Query] --> I[Intent + Scope Resolver]
    I --> S[Structured Data Path\nCSV/Snowflake Solver Outputs]
    I --> R[RAG Path\nPolicy/SOP/Glossary Docs]

    S --> E1[Deterministic KPI + Explainability Engine]

    subgraph RAG_PIPELINE
        L[document_loader.py\nPDF DOCX TXT MD]
        C[chunking.py\nsize 800 overlap 150]
        M[embedding_service.py\nOpenVINO Embeddings]
        V[vector_store.py\nFAISS]
        T[retriever.py\nTop-k + citations]
        L --> C --> M --> V --> T
    end

    R --> T
    T --> E2[Evidence Assembler\nCitations + Context]

    E1 --> F[Final Response Composer]
    E2 --> F
    F --> A[Planner Answer\nStructured facts + cited docs]
```

## Ingestion Flow

```mermaid
sequenceDiagram
    participant U as User/Batch Job
    participant DL as document_loader.py
    participant CH as chunking.py
    participant EM as embedding_service.py
    participant VS as vector_store.py

    U->>DL: Load PDFs DOCX TXT MD
    DL->>DL: Attach metadata(document,page,section,timestamp)
    DL->>CH: Loaded documents
    CH->>CH: Chunk size 800, overlap 150
    CH->>EM: Chunk texts
    EM->>VS: Embedding vectors
    VS->>VS: Persist FAISS index + chunk metadata
```

## Retrieval + Citation Flow

```mermaid
sequenceDiagram
    participant Q as Query
    participant EM as embedding_service.py
    participant VS as vector_store.py
    participant RT as retriever.py

    Q->>EM: Embed query
    EM->>VS: Query vector
    VS->>RT: Top-k chunk hits
    RT->>RT: Build citations from metadata
    RT-->>Q: Retrieved chunks + citations
```

## Citation Format

Each retrieved chunk includes citation fields from metadata:
- document
- page
- section
- timestamp

Canonical citation string:

`<document> | page=<page> | section=<section> | ts=<timestamp>`
