# Architecture

## Book appointment

```mermaid
flowchart TD
    A["Patient enters symptoms<br/>React · Multilingual input"]
    B["Receive intake<br/>FastAPI + Pydantic · Validate request"]
    P["Remove identifiers before tracing<br/>Python regex · Optional Presidio"]

    subgraph INTAKE["Intake workflow · LangGraph · LangSmith tracing optional"]
        C["Validate symptoms + load age / gender<br/>Python catalogue + Supabase"]
        D["De-identify text<br/>Python regex · Optional Presidio"]
        E["ONE Jev call · OpenRouter / HTTPX<br/>typesafe/jev-1.13 · Urgency + Specialty<br/>Original-language text · No translation call"]
        F{"Python routing<br/>Assessment result?"}
        G["Save emergency + specialty<br/>Supabase · Pending care"]
        H["Match city + find open slots<br/>Python + Supabase · No AI"]
        X["Assessment unavailable<br/>FastAPI → React · Retry message"]
        C --> D --> E --> F
        F -->|Emergency| G
        F -->|Non-emergency| H
        F -->|Model failure| X
    end

    I["Patient selects doctor + slot<br/>React · Slot selection"]
    J["Book atomically<br/>FastAPI + Supabase PostgreSQL RPC<br/>Reserve slot + create appointment · Idempotent"]
    K[("Shared appointments<br/>Supabase PostgreSQL<br/>Patient appointment ID = Consultation ID")]
    L["Care team assigns doctor + slot<br/>Explicit FastAPI assignment API"]

    A --> B --> P --> C
    H -->|Slots available| I --> J --> K
    G -->|Urgent guidance + pending queue| L --> J

    classDef model fill:#ede9fe,stroke:#7c3aed,color:#312e81
    classDef data fill:#e0f2fe,stroke:#0284c7,color:#0c4a6e
    classDef human fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef alert fill:#fff1f2,stroke:#e11d48,color:#881337
    class E model
    class G,J,K data
    class A,I,L human
    class X alert
```

## Consultation and SOAP

```mermaid
flowchart TD
    A[("Shared appointment<br/>Supabase PostgreSQL · Same visit ID")]
    B["Doctor opens visit + gives recording consent<br/>React + FastAPI · Signature required"]
    C["Start consultation<br/>Supabase · IN_PROGRESS"]
    D["Record → Stop → Upload<br/>Browser MediaRecorder + FastAPI"]
    E["Sarvam batch API · HTTPX<br/>saaras:v4 · Transcribe + Diarize<br/>Original languages · Person 1 / Person 2"]
    F["Save timestamped transcript<br/>Storage service · boto3 / S3 or local JSON"]
    G["Doctor selects Generate / Regenerate<br/>React + FastAPI · Explicit action"]

    subgraph SOAP["SOAP workflow · LangGraph · LangSmith tracing optional"]
        H["Validate + de-identify turns<br/>Python checks + regex · Optional Presidio"]
        I["LLM call 1 · English translation<br/>OpenRouter / OpenAI SDK<br/>OPENROUTER_MODEL · Default: google/gemini-3.8-flash"]
        V["Check turn order + scrub identifiers<br/>Pydantic + Python regex / optional Presidio"]
        J["LLM call 2 · SOAP extraction<br/>OpenRouter / OpenAI SDK · Same model<br/>Subjective / Objective / Assessment / Plan"]
        K["Validate schema + source excerpts<br/>Pydantic + Python · Grounding checks"]
        H --> I --> V --> J --> K
    end

    L["Save SOAP draft<br/>Storage service · boto3 / S3 or local JSON"]
    M["Doctor reviews + saves edits<br/>React + FastAPI · Human approval"]
    N["Sign and close<br/>FastAPI · Consent + signature checks"]
    O["Save fixed SOAP + signature snapshot<br/>Storage service · boto3 / S3 or local JSON"]
    Q[("Close shared appointment<br/>Supabase · COMPLETED + snapshot reference")]
    R["Read-only signed summary<br/>React · Doctor + patient portals"]

    A --> B --> C --> D --> E --> F --> G --> H
    K --> L --> M --> N --> O --> Q --> R
    M -->|Apply edits| L

    classDef model fill:#ede9fe,stroke:#7c3aed,color:#312e81
    classDef data fill:#e0f2fe,stroke:#0284c7,color:#0c4a6e
    classDef human fill:#dcfce7,stroke:#16a34a,color:#14532d
    class E,I,J model
    class A,C,F,L,O,Q data
    class B,D,G,M,R human
```

## Follow-up appointments

```mermaid
flowchart TD
    A["Patient opens symptoms step<br/>React · Checks 'This is a follow-up appointment'"]
    B["Select a completed appointment<br/>React · Own history only"]
    C["Run intake + booking as usual<br/>Same LangGraph intake + slot selection"]
    D["Book atomically with link<br/>FastAPI + Supabase PostgreSQL RPC<br/>Writes linked_appointment_id with the booking"]
    E{"DB constraint checks<br/>Supabase PostgreSQL"}
    F["Reject booking<br/>FastAPI → React · Other patient / not completed / cycle / completed-after"]
    G[("Appointment with link<br/>Supabase PostgreSQL<br/>linked_appointment_id immutable once set")]
    H["Emergency intake + manual assignment<br/>FastAPI · Copies link from intake onto appointment"]
    I["Patient / doctor / helpdesk detail view<br/>React · 'View previous visit' opens linked record in new tab"]

    A --> B --> C --> D --> E
    E -->|Valid| G
    E -->|Invalid| F
    H --> G
    G --> I

    classDef data fill:#e0f2fe,stroke:#0284c7,color:#0c4a6e
    classDef human fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef alert fill:#fff1f2,stroke:#e11d48,color:#881337
    class D,G,H data
    class A,B,I human
    class F alert
```

## Helpdesk portal and reports

```mermaid
flowchart TD
    A["Helpdesk identifies by phone<br/>React + FastAPI · Demo phone, no session token"]
    B["Browse all consultations<br/>React + FastAPI · Filter by doctor/specialty/day/time · 50-row pages"]
    C["Open consultation detail<br/>React + FastAPI · Read-only clinical content"]
    D["Doctor-overview + SOAP styling<br/>React · Symptoms, draft/signed SOAP, medicines, signature"]
    E["Reports dialog<br/>React · Shared by patient, doctor and helpdesk"]
    F{"Actor + role check<br/>FastAPI · Assigned doctor / helpdesk / patient / other doctor"}
    G["Upload report<br/>FastAPI · PDF/PNG/JPEG ≤ 10 MB"]
    H["Store file<br/>Storage service · boto3/S3 or local<br/>reports/&lt;appointment-id&gt;/&lt;report-id&gt;"]
    I[("consultation_reports<br/>Supabase PostgreSQL · RLS, service-role access")]
    J["View / download only<br/>React · Patients and non-assigned doctors"]
    K["Scoped read on every request<br/>FastAPI · Checks appointment ID + report ID · No public URLs, no caching"]

    A --> B --> C --> D
    C --> E --> F
    F -->|Assigned doctor or helpdesk| G --> H --> I
    F -->|Patient or other doctor| J --> K --> I

    classDef data fill:#e0f2fe,stroke:#0284c7,color:#0c4a6e
    classDef human fill:#dcfce7,stroke:#16a34a,color:#14532d
    class H,I,K data
    class A,B,C,D,E,G,J human
```

## Pharmacy fulfillment

```mermaid
flowchart TD
    A["Doctor reviews SOAP + selects medicines<br/>React · Instructions + quantities"]
    B["Sign and close consultation<br/>FastAPI · Freezes prescription"]
    C["Reserve stock atomically<br/>Supabase PostgreSQL RPC"]
    D{"Stock sufficient?"}
    E[("Frozen prescription + reservation<br/>Supabase PostgreSQL")]
    F["Consultation stays open<br/>FastAPI → React · Insufficient stock, no signing"]
    G["Pharmacist identifies by phone<br/>React + FastAPI · Demo phone"]
    H["Browse 90 medicines / 166 brands<br/>React + FastAPI · Brand/specialty/composition/stock filters"]
    I["View frozen prescriptions<br/>React + FastAPI"]
    J["Mark medicines collected<br/>FastAPI · Supabase"]
    K{"Uncollected after 24h?"}
    L["Unlock reservation<br/>FastAPI · Releases held stock"]
    M["Flag as overdue<br/>React · Inventory shows available/reserved/total"]

    A --> B --> C --> D
    D -->|Yes| E
    D -->|No| F
    E --> I
    G --> H
    G --> I --> J
    I --> K
    K -->|Yes, still uncollected| L
    K -->|Within window| M

    classDef data fill:#e0f2fe,stroke:#0284c7,color:#0c4a6e
    classDef human fill:#dcfce7,stroke:#16a34a,color:#14532d
    classDef alert fill:#fff1f2,stroke:#e11d48,color:#881337
    class C,E data
    class A,G,H,I,J human
    class F,M alert
```
