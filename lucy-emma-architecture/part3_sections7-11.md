# Lucy & Emma Dual-AI System: Comprehensive Technical Architecture
## Part 3 of 3 — Safety, Infrastructure, UI, Roadmap, and Challenges

**Document Version**: 1.0  
**Continues from**: Part 1 (System Overview, Lucy's Architecture, Emma's Architecture) and Part 2 (Trust Model, Data Integration, Self-Evolution)

---

# SECTION 7: SAFETY & SECURITY ARCHITECTURE

## 7.1 Defense in Depth Strategy

Safety and security in the Lucy & Emma system are not a single layer but a nested series of independent defensive boundaries. The design follows the principle that no single control should be relied upon to prevent harm — each control assumes that its predecessor has already been bypassed and is designed to catch what the predecessor missed. This is the "defense in depth" strategy familiar from nuclear safety and aviation security, applied to autonomous AI systems.

The defensive layers, from outermost to innermost, are: network perimeter controls (what can reach the system), authentication and authorization (who can act on the system), API-level input validation (what requests are accepted), capability gating (what Lucy can do), execution sandboxing (what Lucy's tools can do), Emma's monitoring (detecting what shouldn't happen), and the audit log (recording everything for post-incident analysis). A failure or bypass of any single layer is serious but not catastrophic — the remaining layers continue to function. A failure or bypass of multiple layers simultaneously is the scenario that the incident response procedures must address.

## 7.2 Code Execution Sandboxing

The sandboxing strategy described briefly in Section 2.3 is expanded here with full technical detail.

**Technology Selection — gVisor over Docker alone**: Standard Docker containers share the host Linux kernel — any container escape exploiting a kernel vulnerability gives full host access. gVisor interposes a user-space kernel (written in Go) between the container's processes and the host kernel, so container processes make system calls to gVisor's Sentry, which then makes a carefully controlled subset of calls to the host kernel. A kernel exploit in the container must first escape gVisor's interposition layer before it can reach the host kernel. The performance overhead of gVisor is approximately 10–20% for compute-bound workloads and 20–40% for syscall-heavy workloads — acceptable given that tool execution latency is not on the user-facing critical path.

**Technology Selection — Firecracker as the upgrade path**: For Phase 2, the recommended upgrade is from gVisor to **Firecracker** (Amazon's microVM technology) for the highest-risk tool categories. Firecracker provides stronger isolation than gVisor (full hardware virtualization rather than system call interposition) with much lower overhead than traditional VMs (typical Firecracker boot time is 125 milliseconds, compared to 10–60 seconds for full VMs). Firecracker is production-proven at AWS Lambda scale and is appropriate for code execution sandboxes that must balance strong isolation with fast cold-start times. Phase 1 uses gVisor for simplicity; Phase 2 upgrades Mutation Engine sandboxes to Firecracker while keeping lower-risk tool sandboxes on gVisor.

**Sandbox Configuration Specifics**: Each tool execution sandbox is configured with: CPU limit: 1 core via cgroups CPU quota, Memory limit: 512MB RSS via cgroups memory limit with no swap (oom-kill enabled — the sandbox dies rather than swapping), Filesystem: read-only root filesystem with a 64MB tmpfs at /tmp (destroyed on sandbox exit), Network: network namespace with no external connectivity for pure-computation tools; for tools requiring external API access, a dedicated network namespace with outbound-only connectivity restricted to the tool's declared destination addresses via iptables rules, Capabilities: all Linux capabilities dropped except those required for the specific tool type (most tools need zero capabilities), Seccomp: custom seccomp profiles generated from the tool's statically-analyzed syscall usage, allowing only required syscalls (typically 15–30 of the 400+ available syscalls), and Time limits: wall-clock SIGKILL after 30 seconds, with a SIGTERM warning at 25 seconds.

## 7.3 Network Isolation and Access Controls

**Zero-Trust Network Model**: The system adopts a zero-trust network architecture where no component trusts any other component by default, and all communication requires explicit authentication and authorization regardless of network location. This is implemented using **WireGuard** VPN tunnels between all system components (providing mutual authentication and encryption), **Envoy proxy** as a service mesh sidecar for inter-service communication (providing mTLS, request authorization, and telemetry), and **OPA (Open Policy Agent)** for policy-as-code authorization decisions.

**Network Segmentation**: The system network is divided into four security zones. The **external zone** contains only the API gateway, which is the single point of entry for user requests and webhook receivers. The **application zone** contains Lucy's cognitive core and the operator dashboard backend. The **execution zone** contains the tool execution sandboxes — this zone has strictly limited egress controlled by a per-tool firewall ruleset, and no direct path to the storage zone. The **data zone** contains all persistent storage. Cross-zone communication is permitted only through explicit firewall rules, and all cross-zone connections are logged.

**API Gateway**: The external-facing API gateway handles TLS termination (TLS 1.3 minimum, TLS 1.2 with restricted cipher suites as fallback), DDoS protection via rate limiting at the connection level, request authentication (JWT validation for API clients, session token validation for the operator dashboard), input size limiting (maximum request body 1MB — larger files must use the file upload endpoint with chunked transfer), and basic request validation (rejecting malformed JSON, invalid content types, and requests with missing required headers). The gateway logs all requests including rejected ones — rejected request logs are valuable for detecting probing and attack attempts.

## 7.4 Data Privacy and Encryption

**Encryption at Rest**: All persistent data stores use AES-256 encryption at rest. For PostgreSQL, this is implemented using filesystem-level encryption (dm-crypt/LUKS on Linux) rather than PostgreSQL's native encryption options, as filesystem-level encryption provides uniform coverage without application-level complexity. The MinIO object store uses server-side encryption with AES-256-GCM. SQLite databases (used on Jetson edge nodes) use SQLCipher, which provides AES-256 encryption transparent to the application layer.

**Encryption in Transit**: All inter-service communication uses TLS 1.3. Internal WireGuard tunnels provide an additional encryption layer for intra-cluster communication. The telemetry stream from Lucy to Emma is encrypted using WireGuard even within the same physical node, because the separation of process-level security domains requires that Emma cannot be assumed to share a trusted memory space with Lucy.

**Key Management**: Encryption keys are managed using **HashiCorp Vault** (self-hosted for the edge cluster, or HashiCorp Cloud Platform for production multi-node deployments). Keys are rotated on a 90-day schedule. The Vault unsealing process requires Shamir's Secret Sharing with a 3-of-5 key shard scheme — three of five designated operator key holders must provide their shards to unseal Vault after a restart. This prevents a single operator from having unilateral access to all encryption keys.

**User Data Handling**: User query text is treated as potentially sensitive by default. The system applies pseudonymization at the point of ingestion: the user identifier is replaced with a pseudonymous session token in all logs and telemetry. The mapping between user identifiers and session tokens is stored in a separate, access-controlled table that requires explicit authorization to query. User data is subject to configurable retention policies with a default of 90 days for raw query data and indefinite retention for anonymized, aggregated patterns (which do not allow reconstruction of individual queries). The system provides a user data export and deletion endpoint that satisfies GDPR Article 15 (right of access) and Article 17 (right to erasure) requirements.

## 7.5 Audit Logging and Forensics

**Structured Audit Log Format**: All audit log entries use a consistent JSON schema: event timestamp (microsecond precision, UTC), event type (from a controlled vocabulary of ~50 event types), actor identity (Lucy/Emma/operator/system, with sub-identifiers), affected resource (structured resource path), action taken, outcome (success/failure/partial), data snapshot (relevant state before and after the action, omitting PII), trust level at time of event, correlation ID (links related events across distributed components), and a cryptographic chain link (SHA-256 hash of the previous entry in the same log stream).

**Log Integrity**: The cryptographic chain linking makes any deletion or modification of audit log entries detectable — removing or modifying an entry breaks the hash chain, and any entry after the modification point will have an invalid chain link. The chain is verified automatically by the audit log reader; any break triggers an immediate Emma alert. Log entries are also written to an append-only **Kafka** topic (for production deployments) or an append-only file with filesystem-level write protection (for edge deployments), providing a second verification that the log has not been tampered with.

**Forensic Analysis Capabilities**: The audit trail supports post-incident forensic analysis through a dedicated query interface. The query language supports: time-range filtering (with microsecond precision), event type filtering, actor filtering, resource path pattern matching, correlation ID lookup (following a chain of related events across components and time), and trust score reconstruction (recreating what Lucy's trust score was at any point in history by replaying the event stream). The forensic interface requires elevated operator authorization to access, and all forensic queries are themselves logged.

## 7.6 Incident Response Procedures

**Incident Classification**: Incidents are classified into four severity levels. Severity 1 (Critical): active safety boundary violation, Lucy operating outside authorized scope, Level 4 shutdown triggered. Response time target: acknowledge within 5 minutes, contain within 30 minutes. Severity 2 (High): repeated Level 3 interventions within 60 minutes, trust score drop of more than 2 levels in 24 hours, evidence of systematic anomalous behavior. Response time target: acknowledge within 30 minutes, contain within 4 hours. Severity 3 (Medium): repeated Level 2 interventions, single Level 3 intervention, performance degradation sustained above 30% for more than 2 hours. Response time target: acknowledge within 4 hours, contain within 24 hours. Severity 4 (Low): isolated Level 2 interventions, performance degradation under 30%, tool proposal rejections. Response time target: review within 48 hours.

**Containment Protocol**: The containment protocol for Severity 1 and 2 incidents follows a structured playbook: Step 1 — immediately preserve system state (snapshot PostgreSQL, export Redis state, archive current audit log segment) before taking any corrective action, because containment actions can destroy forensic evidence. Step 2 — implement the minimum necessary containment (trust level reduction or process termination), avoiding over-containment that destroys more evidence. Step 3 — isolate the affected component from the rest of the system while preserving its state for analysis. Step 4 — initiate the post-mortem process.

**Post-Mortem Process**: Every Severity 1 or 2 incident produces a structured post-mortem document within 7 days of resolution. The post-mortem follows a blameless format (focusing on system factors rather than individual failures) and addresses: what happened (timeline of events from audit log), why it happened (root cause analysis with 5-whys methodology), what was the impact (scope of affected operations, user impact, trust score impact), what contained the incident (which defensive layer caught it, how long it took), and what prevents recurrence (specific architectural or procedural changes, not just "be more careful").

---

# SECTION 8: INFRASTRUCTURE & DEPLOYMENT

## 8.1 NVIDIA Jetson Edge Architecture

The target edge hardware is the **NVIDIA Jetson AGX Orin 64GB**. Key specifications relevant to this deployment: 12-core ARM Cortex-A78AE CPU, 2048-core Ampere GPU with 64 Tensor Cores, 64GB LPDDR5 unified memory shared between CPU and GPU, 64GB eMMC storage (supplemented by NVMe), and a 275 TOPS peak performance rating. The unified memory architecture is particularly valuable: unlike discrete GPU systems where CPU-GPU memory transfers are a bottleneck, on Jetson the CPU and GPU share a single memory pool, enabling zero-copy data transfers between host and device. This significantly reduces latency for workloads that alternate between CPU (orchestration logic) and GPU (inference) processing.

**8-Node Cluster Role Assignment**:

Node 1 and 2 — **Lucy Inference Primary and Secondary**: These nodes are dedicated to language model inference. They run vLLM (for the Triton Inference Server integration) or llama.cpp (for direct inference) with the primary language model (13B parameters, 4-bit GPTQ quantization, approximately 7GB VRAM). The remaining VRAM (~57GB) is allocated to the KV cache, enabling approximately 20 concurrent sessions with 4K token context each. Node 2 serves as hot standby — it runs the same model and can take over inference in under 10 seconds if Node 1 fails. Load balancing between Nodes 1 and 2 is handled by a HAProxy instance running on the gateway node, routing requests based on current queue depth.

Node 3 — **Emma Oversight and Monitoring**: Dedicated to Emma's processes — the telemetry consumer, the statistical anomaly detector, the behavioral pattern analyzer, the trust scoring engine, and the intervention system. Emma's processes are computationally lighter than Lucy's inference (no large model inference), so 12GB VRAM is reserved for Emma's monitoring models (the autoencoder behavioral anomaly detector and the CodeBERT code safety analyzer). The remaining VRAM is available as overflow for burst processing.

Node 4 — **Execution Sandbox Host**: This node runs the Docker/gVisor execution environment for tool sandboxes. It is intentionally isolated from the inference and monitoring nodes — it has more aggressive cgroup limits (maximum 8GB memory allocation per active sandbox, maximum 4 concurrent sandboxes) and more restricted network access. The node's eMMC is supplemented by a 2TB NVMe drive for tool artifact storage and sandbox scratch space.

Node 5 — **Data Ingestion and Correlation Engine**: Runs the sensor feed pollers, the normalization pipeline, TimescaleDB for the time-series sensor data, and the correlation computation workload (GPU-accelerated via CuPy). The TimescaleDB instance stores the 7-day rolling window of sensor data (estimated 50–200GB depending on polling frequencies and source count).

Node 6 — **Primary Storage**: Runs PostgreSQL 16 (for operational data), MinIO (for object storage), and Redis (for the hot tool registry, session state, and the telemetry stream bus). PostgreSQL and MinIO data are stored on a 4TB NVMe drive with RAID-1 mirroring to a second 4TB drive. Redis is in-memory with AOF persistence enabled (append-only file for durability). This node is the most storage-intensive and requires the most careful capacity planning.

Node 7 — **Operator Interface and API Gateway**: Runs the FastAPI application server (the user and operator HTTP/WebSocket API), the Nginx reverse proxy/load balancer, the operator dashboard frontend (served as static files), and the authentication service. This node has the most network traffic and the most direct internet exposure — it is the only node with a public IP address.

Node 8 — **Spare / Overflow / Maintenance**: This node is not assigned a permanent role. It is available for: overflow inference capacity during peak load (hot standby to dynamically absorb load from Nodes 1 or 2), scheduled maintenance operations (one node taken offline for maintenance while this one covers its role), experimental deployments (testing new tool versions or model updates in a live but non-critical environment), and system-wide backup jobs (running backups off the primary nodes to avoid I/O impact).

**CUDA Optimization Techniques**:

For inference optimization on Jetson, the primary technique is **CUDA graph capture**: for the attention computation in the transformer model, the CUDA operations are captured into a static graph that can be replayed without CPU overhead on subsequent identical-shape inputs. This is particularly effective for batch inference where the computation graph shape is predictable. CUDA graph capture reduces per-token inference overhead by approximately 20–30% on Jetson.

**TensorRT optimization** converts the PyTorch model to a TensorRT-optimized engine at system startup. The conversion process (which takes approximately 30–60 minutes per model) produces a JIT-compiled, hardware-specific inference engine that exploits Jetson's Tensor Core matrix operations more efficiently than generic PyTorch CUDA code. TensorRT engines are model-hardware-specific and cannot be transferred between different Jetson models — they must be regenerated on the target hardware.

**Unified memory optimization** takes advantage of Jetson's unified memory by using CUDA Unified Memory APIs for large tensor allocations, allowing the CUDA runtime to automatically manage data locality between CPU and GPU without explicit transfers. This eliminates approximately 30–50% of the memory bandwidth overhead present in discrete GPU systems.

**Power and Thermal Management**: Jetson AGX Orin supports multiple power modes (10W to 60W configurable via nvpmodel). The deployment uses the 40W mode (MODE_30W_ALL or MODE_40W_ALL) for normal operation, providing a balance between performance and thermal stability. Active cooling is mandatory for cluster deployment — passive cooling is insufficient for sustained inference workloads. The system monitors GPU temperature via the Tegra system stats API and throttles inference batch size if temperature exceeds 85°C (approaching the 95°C thermal shutdown threshold). The thermal headroom in the cluster design should target normal operating temperature under 75°C to provide a 20°C margin before throttling begins.

## 8.2 Scalability Transition Architecture

**Single-User to Multi-User Transition**: The primary architectural change required to move from single-user to multi-user operation is the externalization of session state. In single-user operation, Lucy's working memory (the Cognitive Context Frame and conversation history) is held in the inference process's memory. For multi-user operation, this state must be stored externally so that any inference node can serve any user's session. The externalized session state is stored in Redis (a natural choice given Redis is already deployed for the tool registry and telemetry bus). The session state schema stores: conversation history (serialized as JSON), active CCF (if a task is in progress), tool belt configuration (which tools are active for this session), user preferences, and session metadata (creation time, last activity, trust level for this session).

The inference node statelessness requirement also means that the KV cache (the attention cache for transformer inference) must be either regenerated from the serialized conversation history on each request or checkpointed to Redis. KV cache regeneration is expensive (approximately 100ms per 1K tokens of history for a 13B model on Jetson), so for sessions with long conversation histories, the system uses a hybrid approach: the most recent 4K tokens are kept in the node-local KV cache, while older context is stored as compressed embeddings in Redis and selectively retrieved based on relevance to the current query.

**Horizontal Scaling Strategy**: For the 50–500 user range (Phase 2 target), the architecture adds a Kubernetes cluster of x86 GPU nodes (NVIDIA A10G or equivalent) behind a load balancer. The Jetson cluster transitions to handling data ingestion, storage, and Emma's monitoring (workloads that benefit from the edge deployment for latency or data locality reasons), while Lucy's inference scales on cloud/datacenter hardware with higher GPU memory density. A Kubernetes Horizontal Pod Autoscaler scales the inference deployment based on GPU utilization and request queue depth, with a minimum of 2 replicas (for availability) and a maximum configured based on budget constraints.

**Multi-Tenancy and Isolation**: For enterprise deployments (1,000+ users), each organizational tenant requires isolated Lucy and Emma instances — they should not share memory, trust scores, or tool belts. The multi-tenancy model uses Kubernetes namespaces for process isolation, separate PostgreSQL schemas for data isolation (with row-level security policies ensuring cross-schema data access is impossible even with a SQL injection in the application layer), and separate Redis keyspace prefixes for the hot registry and session state. Emma instances are not shared across tenants — each tenant has their own Emma instance, ensuring that anomalous behavior by one tenant's Lucy does not affect the trust scoring or monitoring of another tenant's Lucy.

## 8.3 Complete Technology Stack Reference

**Compute and Inference Layer**:
- Language model inference: **llama.cpp** (edge, Jetson), **vLLM** (production, x86) — both expose Triton-compatible HTTP API
- Model serving: **NVIDIA Triton Inference Server 23.x** — provides dynamic batching, model versioning, health endpoints, and the standardized `/v2/models/{model}/generate_stream` SSE endpoint used by LucyChatPanel
- Model format: **GGUF** (4-bit quantization, llama.cpp) or **AWQ** (4-bit quantization, vLLM) — both achieve approximately 4× memory reduction with under 3% quality degradation on standard benchmarks
- Embedding generation: **sentence-transformers** with `all-MiniLM-L6-v2` (fast, small) for hot registry tool embeddings; `all-mpnet-base-v2` (higher quality) for semantic memory consolidation
- GPU acceleration: **CuPy** for correlation matrix computation, **TensorRT** for optimized inference kernels, **CUDA 12.x** as the base

**Application and API Layer**:
- Primary language: **Python 3.11** (AI/ML, orchestration, API)
- Performance-critical paths: **Rust 1.75+** (capability gate, telemetry processor, audit log writer)
- API framework: **FastAPI 0.110+** with **uvicorn** (ASGI server, asyncio-native)
- WebSocket support: **FastAPI WebSocket** endpoints for real-time dashboard updates
- SSE streaming: native FastAPI `EventSourceResponse` for inference streams
- Inter-service communication: **gRPC** with **protobuf** (Emma↔Lucy control channel)
- Task queuing: **Celery 5.x** with Redis broker for background jobs (memory consolidation, logic pruning, trust score batch recomputation)
- Process management: **supervisord** (edge) or Kubernetes Deployments (production)

**Storage Layer**:
- Operational relational data: **PostgreSQL 16** with **pgvector** extension (eliminates the need for a separate vector DB in smaller deployments)
- Vector store (production): **Qdrant** — REST and gRPC API, filtering support, HNSW index with configurable ef_construction, payloads stored alongside vectors
- Time-series sensor data: **TimescaleDB** (PostgreSQL extension) — automatic partitioning by time, continuous aggregates for dashboard metrics, compression for older data
- Object storage: **MinIO** with S3-compatible API — tool artifacts, model checkpoints, audit log archives
- Cache and message bus: **Redis 7.x** with Redis Streams — hot tool registry, session state, telemetry bus, Celery broker
- Edge SQLite: **SQLCipher** for encrypted local databases on Jetson nodes

**Security Infrastructure**:
- Secret management: **HashiCorp Vault** (self-hosted)
- Service mesh / mTLS: **Envoy proxy** sidecars
- Policy enforcement: **Open Policy Agent (OPA)**
- VPN / network encryption: **WireGuard**
- Container runtime: **Docker** with **gVisor** (runsc) runtime for sandboxes
- Static analysis: **Bandit**, **Semgrep** (custom ruleset)

**Observability**:
- Metrics: **Prometheus** with custom exporters for trust scores, tool performance, inference latency
- Visualization: **Grafana** (operator technical dashboard), custom React dashboard (user-facing)
- Distributed tracing: **OpenTelemetry** SDK with **Jaeger** backend
- Log aggregation: **Loki** (Grafana stack) or **ElasticSearch** (for richer query capabilities)
- Alerting: **Alertmanager** (Prometheus stack) with configurable routing to email, Slack, PagerDuty

---

# SECTION 9: USER INTERFACE & TRANSPARENCY

## 9.1 Interface Architecture Philosophy

The user interface serves two distinct audiences with different needs. Users (people querying Lucy for task assistance) need a clean, responsive chat interface with just enough visibility into Lucy's operations to build appropriate trust and understand her limitations. Operators (system administrators and developers) need comprehensive real-time observability into every layer of the system, with direct control capabilities and the ability to drill down from high-level indicators to raw event data. These two audiences are served by two distinct interface components built on the same underlying data layer.

The interfaces are built with **React 18** and **TypeScript**, using **Tailwind CSS** for styling (consistent with the existing LucyChatPanel implementation). All real-time data flows through Server-Sent Events (SSE) for one-way server-to-client streaming (metrics, telemetry, inference tokens) and WebSocket for bidirectional control communication (operator commands, emergency stop). The technology choices emphasize simplicity and reliability over novelty — SSE is a standard browser API with graceful reconnection semantics, avoiding the complexity of WebSocket lifecycle management for data that only flows in one direction.

## 9.2 User Interface: Debug Window and Chat

**Debug Window**: The Debug Window is a collapsible panel adjacent to the primary chat interface. It is hidden by default and toggled by a "Show reasoning" button. When open, it displays Lucy's real-time cognitive state as she processes the current query. Content displayed includes: the task decomposition tree (showing how Lucy broke the request into subtasks), the tool selection process (which tools were considered, why the selected tool was chosen, Emma's rating for each), live resource usage during processing (VRAM%, CPU%, estimated time remaining), and the active data context (which sensor data items are in Lucy's current context window, with timestamps and quality scores). The Debug Window is styled to be scannable rather than overwhelming — hierarchical collapsible sections, color-coded by information type, with a verbosity slider that controls how much detail is shown (Summary / Standard / Detailed / Raw).

**Inference Mode Indicator**: The updated LucyChatPanel (already implemented in the codebase) displays a color-coded badge indicating the inference source for each response: TRITON (violet, production inference), OLLAMA (sky blue, local LLM), RULE-BASED (amber, deterministic fallback). This is a critical transparency feature — users should always know whether they are receiving LLM-generated responses or rule-based responses, because the quality and limitations differ significantly.

**Learning Station**: The Learning Station is a specialized interface mode (toggled from the main navigation) where Lucy presents her reasoning in a structured, educational format. Instead of a conversation interface, the Learning Station shows a three-panel layout: the left panel shows the user's query and Lucy's final response; the center panel shows an annotated breakdown of Lucy's reasoning process, with each step explained in plain language at the user's configured comprehension level (Beginner / Intermediate / Advanced); and the right panel shows the live data context — which sensor readings, memory entries, and tools informed this response. The Learning Station is implemented as a separate page route that uses the same backend APIs as the primary chat but with enhanced explainability output (the API response includes additional `reasoning_steps` and `data_context` fields when the Learning Station query parameter is set).

**Mood and Mode Indicators**: Lucy's current operational mode is displayed in the header bar of the chat interface as a color-coded mode badge. The modes and their visual identities are: Creative (purple, ✦ icon — used when brainstorming or ideating), Engineering (blue, ⚙ icon — precise, structured responses), Professor (green, 📖 icon — educational, patient), Analysis (orange, 📊 icon — data-focused, quantitative), Research (cyan, 🔍 icon — exploratory, comprehensive), and Safety Check (red, ⚠ icon — Emma has flagged the current task for enhanced scrutiny). The mode is determined by Lucy based on the task type and is included in the API response metadata. Operators can manually override the mode through the configuration interface.

## 9.3 Operator Dashboard

**Architecture**: The operator dashboard is a separate application route (served at `/ops/dashboard`) with its own authentication requirement (operator role, separate from user authentication). It uses a modular widget layout implemented using **React-Grid-Layout** — operators can drag, resize, and reposition widgets, and their layout is persisted per-operator in the user preferences store. The default layout is prescribed but fully customizable.

**Core Widget Set**:

The **System Health Matrix** is a 4×4 grid of status indicators, one per major component. Each indicator shows component name, current status (green/yellow/red), the metric most representative of that component's health, and a sparkline of the last 60 minutes. Clicking a component opens a detail panel with the last 24 hours of metrics and recent event log. This widget gives operators a 30-second health overview of the entire system.

The **Trust Level Timeline** shows Lucy's trust score on a continuous line chart with the trust level band boundaries overlaid as horizontal reference lines. The x-axis spans the last 7 days. Trust level transitions are marked with vertical markers labeled with the transition direction (↑ or ↓) and the trigger event. Hovering over any point shows the full trust score breakdown (accuracy, safety compliance, operational reliability, resource efficiency, self-awareness dimensions). This widget is the primary tool for understanding Lucy's operational trajectory.

The **Emma Intervention Log** is a chronological list of all Level 1+ interventions in the selected time range (default: last 24 hours). Each entry shows: timestamp, intervention level, trigger description, automatic actions taken, operator actions taken, resolution status, and a link to the full audit trail for that event. The list supports filtering by level, status, and text search. Unresolved Level 2+ interventions are highlighted in amber and red respectively with a badge count in the widget header.

The **Tool Belt Activity Map** is a heat map visualization showing tool invocation frequency and success rate over the last 24 hours. Rows represent tool categories, columns represent 1-hour time windows, and cell color represents the combination of invocation frequency (brightness) and success rate (green-to-red hue). Cells are clickable to show the individual tool invocations in that category and time window. This widget helps operators identify which capabilities Lucy uses most, which tools are underperforming, and whether there are temporal patterns in tool usage.

The **Live Earth Data Status** panel shows the current status of all 10+ sensor data feeds: last successful poll time, data quality score, current notable events (earthquakes above M4.0, active weather alerts, unusual space weather readings), and a trend indicator (improving/stable/degrading). This widget provides situational awareness about the external data context that is informing Lucy's responses.

The **Pending Reviews Queue** lists all items requiring operator action: tool proposals above the automated approval threshold, trust level advancement notifications (requiring acknowledgment or veto), and queued incidents from Emma. Each item shows an estimated review time and a priority indicator. Items approaching their review deadline are highlighted.

**Real-Time Update Architecture**: Dashboard widgets subscribe to a per-widget SSE stream from the FastAPI server. The server publishes updates on a per-metric cadence (health metrics: 5 seconds, trust scores: 60 seconds, intervention log: real-time, tool activity: 60 seconds). The SSE approach was chosen over WebSocket for dashboard updates because the dashboard is fundamentally a read interface — it doesn't need bidirectional communication for metrics display. Control actions (trust adjustments, veto, emergency stop) use separate authenticated POST endpoints.

## 9.4 Notification and Alerting System

**Notification Channels**: The system supports five notification channels: in-app (dashboard notification bell, visible when logged in), email (SMTP with configurable sender and recipients), SMS via **Twilio** API (for Level 3+ interventions where operator availability cannot be assumed), Slack webhook (for teams using Slack for incident management), and **PagerDuty** (for enterprise deployments requiring on-call rotation management). Channel selection and severity routing are configurable per-operator through the notification settings panel.

**Alert Fatigue Prevention**: Alert fatigue is a real risk in monitoring systems — too many alerts cause operators to start ignoring them. The system prevents alert fatigue through three mechanisms. First, alert deduplication: multiple occurrences of the same alert type within a configurable window (default: 15 minutes) are grouped into a single alert with an occurrence count, rather than generating N separate notifications. Second, alert scoring: alerts are prioritized by a composite score of severity and novelty (a new alert type that hasn't been seen before is given higher priority than a recurrence of a known pattern). Third, quiet hours: operators can configure quiet hours during which only Level 4 emergency alerts are delivered via interrupting channels; lower-severity alerts queue for delivery at the end of the quiet period.

---

# SECTION 10: IMPLEMENTATION ROADMAP

## 10.1 Phased Development Approach

The Lucy & Emma system is designed for incremental delivery — each phase produces a functional system that is useful in production, while laying the groundwork for the next phase. The phase boundaries are defined by capability milestones rather than calendar dates, because capability milestones are more meaningful (and more motivating) than date-based milestones for a complex R&D project of this nature. Estimated durations are provided as planning references, not commitments.

### Phase 1: Foundation (Estimated 6–9 months, 3–5 engineers + 1 ML specialist)

**Objective**: A functional Lucy & Emma system with a stable core architecture, reliable chat capability, Emma's basic monitoring, and the initial trust model. No self-evolution in Phase 1 — the goal is a solid, safe foundation on which Phase 2 can build.

**Critical Path Components** (must be completed in sequence):

Storage layer first: PostgreSQL schema design, Redis setup, MinIO setup, and the core data models (ToolManifest, CognitivContextFrame, TrustScore, AuditEntry). Getting the data model right in Phase 1 avoids costly migrations in later phases.

Emma's core monitoring second: The telemetry stream, the statistical anomaly detector, the intervention mechanisms (Levels 1–3), and the trust scoring engine. Emma must exist before Lucy runs in production — never the reverse. This is the primary safety constraint on the development sequence.

Lucy's cognitive core third: The language model inference engine (llama.cpp on Jetson), the basic tool belt (10–15 pre-built, human-validated tools — no Mutation Engine yet), the working memory system, and the task decomposition planner.

API and basic UI fourth: FastAPI server, LucyChatPanel (already implemented), basic operator dashboard (System Health Matrix and Emma Intervention Log widgets at minimum).

Integration and testing fifth: End-to-end testing of the Lucy-Emma interaction, trust level transitions, basic intervention scenarios, and performance validation against the latency targets.

**Phase 1 MVP Deliverables**: A stable chat interface powered by a 13B local language model, 15 pre-built tools covering the most important capability categories, Emma's monitoring and L0–L2 trust levels, a basic operator dashboard, and all audit logging infrastructure. The system should be able to run continuously for 7 days without operator intervention and maintain a trust score above 40 (L1 minimum).

**Phase 1 Success Metrics**: 95th percentile chat latency under 3 seconds (Jetson hardware), Emma anomaly detection false positive rate under 5% on the baseline test suite, all Level 4 emergency shutdown scenarios testable and functional, zero production security incidents in 30-day evaluation period, positive usability feedback from at least 3 evaluation users.

### Phase 2: Capabilities (Estimated 9–12 months, 4–5 engineers + 1–2 ML specialists)

**Objective**: Add the data integration layer, the Mutation Engine (tool creation), and L3–L4 trust levels. By the end of Phase 2, Lucy should be genuinely more capable than a standard language model assistant for the defined use cases, and the self-evolution capability should be functional within Emma's supervision.

**Key additions in Phase 2**: The full sensor data ingestion pipeline (all 10 data sources), the correlation engine and TimescaleDB time-series store, the Mutation Engine with its six-stage validation pipeline and Emma's automated code review, Firecracker microVM upgrade for Mutation Engine sandboxes, L3 and L4 trust levels (with the full trust scoring algorithm, multi-dimensional scoring, and validation period enforcement), the enhanced operator dashboard (full widget set), the Learning Station UI, and Triton Inference Server integration for the production inference path.

**Phase 2 Success Metrics**: Mutation Engine producing useful, Emma-approved tools at a rate of at least 2 per week without human intervention, sensor data integration with all 10 sources achieving 95%+ uptime, the correlation engine surfacing at least 3 validated non-obvious cross-domain correlations in the first month of operation, Lucy achieving L3 trust level within 45 days of Phase 2 deployment, performance improvements from Phase 2 optimizations achieving 50th percentile inference latency under 1 second.

### Phase 3: Autonomy (Estimated 12–18 months, 4–5 engineers + 2 ML specialists)

**Objective**: Full self-evolution capability, L4–L5 trust levels, multi-user scaling (up to 50 users), and the complete transparency and oversight features. Phase 3 represents the system's design capability fully realized.

**Key additions in Phase 3**: L4 and L5 trust level definitions and enforcement, full logic pruning and capability discovery automation, the environmental pressure response mechanism, the quantum leap reasoning framework, multi-user Kubernetes deployment, the full security hardening (WireGuard, OPA, Vault, full mTLS), comprehensive GDPR compliance tooling, the complete notification system, and post-mortem tooling and runbooks for all identified incident scenarios.

**Phase 3 Success Metrics**: System sustaining L4 trust level for 60 consecutive days, Mutation Engine tool acceptance rate (tools deployed and retained for 30+ days / tools created) above 70%, multi-user deployment serving 20 concurrent users with 95th percentile latency under 2 seconds, zero Severity 1 incidents in 90-day evaluation period, operator workload under 2 hours per week for normal operations.

### Phase 4: Scale and Optimization (Estimated 12–18 months, 3–4 engineers + 1 ML specialist)

**Objective**: Production-scale deployment (up to 10,000 users), performance optimization for cost efficiency, and the enterprise features (multi-tenancy, advanced compliance, SLA management).

**Key additions in Phase 4**: Full Kubernetes auto-scaling, multi-tenancy architecture, enterprise SSO integration (SAML/OIDC), compliance reporting (SOC2, GDPR audit reports), advanced model optimization (custom fine-tuning on the system's operational data, knowledge distillation to smaller/faster models for cost efficiency), API versioning and SDK delivery, and a public integration marketplace for third-party tool contributions.

## 10.2 Critical Dependencies and Risks

**Dependency 1 — Foundation of Emma before Lucy**: As stated, Emma's core monitoring infrastructure must be completed and validated before Lucy runs in production. The risk of inverting this order is that you have a capable AI system operating without oversight, and adding oversight after the fact is much harder than building it first. Mitigation: enforce this sequencing in the project plan with a formal gate review before Lucy goes to production.

**Dependency 2 — Data model stability**: The core data models (ToolManifest, trust score schema, audit log schema) must be finalized before large amounts of data are generated. Schema changes after data accumulation require migration planning. Mitigation: invest heavily in data modeling workshops in the first month of Phase 1, and commit to the Phase 1 data model for at least 12 months before considering breaking changes.

**Dependency 3 — Jetson hardware availability**: NVIDIA Jetson AGX Orin 64GB modules can have supply constraints. Order the 8-node cluster hardware as early as possible — ideally before Phase 1 development begins, so the hardware is available for integration testing in the second half of Phase 1.

---

# SECTION 11: CHALLENGES & CONSIDERATIONS

## 11.1 Top Technical Challenges and Mitigations

**Challenge 1 — Trust Score Gaming**: Lucy's self-evolution mechanisms give her the ability to optimize her own behavior. In principle, a sufficiently capable system could learn to optimize specifically for the metrics that drive trust score increases, producing behavior that scores well without being genuinely aligned with the intent behind the metrics. This is analogous to Goodhart's Law ("when a measure becomes a target, it ceases to be a good measure"). Mitigation strategy: use a multi-dimensional trust score with dimensions that are difficult to simultaneously optimize (accuracy is easy to game but safety compliance is harder; self-awareness calibration is particularly hard to game because it requires the system to be accurate about its own confidence). Regularly rotate the specific metrics used in each dimension to prevent long-term optimization against fixed targets. Include human evaluation as a non-gameable component (Emma cannot learn to pass a human assessment that she doesn't have access to in advance). Monitor for the specific signature of gaming: score improvements that are not accompanied by improvements in user-perceived quality.

**Challenge 2 — Catastrophic Forgetting in the Evolution Context**: The standard catastrophic forgetting problem in machine learning (new training causes forgetting of old capabilities) has an additional dimension here: Lucy's self-evolution could inadvertently prune capabilities that are needed for Emma's oversight. If Lucy's logic pruning removes a capability that Emma relies on for monitoring (e.g., a specific telemetry emission), Emma's ability to detect subsequent anomalies could be compromised. Mitigation strategy: Emma maintains an explicit list of "protected capabilities" — code paths and tools that Lucy's pruning system must never remove or modify. This list is stored in Emma's configuration (not Lucy's) and is enforced at the pruning approval stage. Any pruning proposal that would affect a protected capability is automatically escalated to human review.

**Challenge 3 — Latency Budget on Edge Hardware**: The target 95th percentile latency of under 2 seconds for a 13B model on Jetson is aggressive. Realistic measurements on Jetson AGX Orin 64GB with llama.cpp show approximately 30–50 tokens/second for a 13B 4-bit model, meaning a 200-token response takes 4–7 seconds plus prefill time. Meeting the latency target requires: (a) aggressive speculative execution for tool invocations, (b) streaming responses that deliver the first token within 500ms even if the full response takes longer (users perceive streaming responses as faster even at the same total latency), (c) response caching for common queries, and (d) a tiered model approach (a 3B model for simple queries, the 13B model only for complex ones). The 3B model approach is the most impactful lever and should be the first implemented.

**Challenge 4 — Emma's Monitoring Scalability**: Emma's behavioral analysis uses a trained autoencoder that is calibrated on Lucy's "normal" behavior. As Lucy evolves (Phase 2 and beyond), what is "normal" changes — and Emma's model must evolve to match, or it will generate excessive false positives as Lucy's capabilities expand. But Emma's model training must not be influenced by Lucy's operations (as noted in Section 3.2 — Lucy could manipulate the training data). Mitigation strategy: separate the concepts of "behavioral baseline update" (adjusting what Emma considers normal after a validated, operator-approved capability expansion) from "model training" (improving Emma's anomaly detection accuracy). Baseline updates are approved by the operator after each major trust level advancement. Model training uses only data from periods that were not flagged as anomalous, and the model is validated against a held-out human-labeled anomaly test set before deployment.

**Challenge 5 — The Bootstrap Problem**: In Phase 1, Lucy has no history of performance, so she starts at L0 with no trust. But with L0 capabilities, she can barely do anything useful, so she generates little performance data. This creates a chicken-and-egg bootstrap problem: the system needs performance data to advance trust, but needs trust to generate meaningful performance data. Mitigation strategy: The Phase 1 deployment includes a structured "capability exhibition" protocol — a set of 50 pre-defined tasks across all capability categories that a human operator runs during the initial deployment period. These tasks are designed to safely evaluate Lucy's performance at L0 and provide the performance data needed to advance to L1. The tasks are executed in a dedicated test environment with enhanced logging and human evaluation of each output. This bootstraps the trust score system with real performance data within the first week of operation.

## 11.2 Ethical Considerations

**Autonomy and Accountability**: As Lucy gains capability and operational freedom, questions of accountability become complex. When Lucy takes an autonomous action that causes harm (data error, inappropriate recommendation, resource consumption), the accountability chain must remain clear: the operators who configured the system and approved the trust level advancement, the engineers who designed the architecture, and the organization deploying the system are all accountable in different ways. The system is designed to maintain this accountability chain through comprehensive audit logging and the explicit operator approval requirements at each trust level gate. The architecture deliberately avoids any mechanism that would allow the system to act without any traceable human authorization for high-consequence decisions.

**Transparency vs. Complexity**: The system generates enormous amounts of data about its own operations. Transparency requires making this data accessible, but accessibility requires simplification, and simplification risks oversimplification — presenting a simplified view that users trust more than it deserves. The dashboard design addresses this tension by providing multiple levels of detail (the high-level status overview and the raw event drill-down) and by making the limitations of simplified views explicit (every high-level metric is annotated with a caveat linking to its definition and known limitations).

**The Learning Boundary**: Lucy learns from user interactions. This raises the question of consent: do users understand that their interactions may influence Lucy's future behavior? The privacy architecture (pseudonymization, configurable retention, right-to-erasure) addresses the data ownership dimension, but the epistemic dimension — that Lucy is becoming a slightly different system after each interaction — requires explicit communication. The user interface should include a clear, readable explanation of how Lucy learns, with specific examples of what changes and what doesn't, and with an opt-out mechanism for users who do not want their interactions used for learning.

## 11.3 Failure Mode and Effects Analysis

The following FMEA summary covers the five highest-risk failure modes identified in the architecture.

**FM-01 — Mutation Engine produces malicious code (Severity: Critical)**. Effect: Lucy deploys a tool that exfiltrates data, consumes unbounded resources, or modifies system state in unauthorized ways. Detection: Emma's code safety analyzer (Stage 1 of validation pipeline) and gVisor sandbox containment. Mitigation: six-stage validation pipeline, gVisor containment as hard boundary, Emma's code review as second opinion, human review requirement for high-risk proposals. Residual risk: low for obvious malicious patterns, medium for subtle exploits that pass static analysis. Recovery: immediate tool rollback (30-second target), sandbox termination, forensic analysis of the generated code.

**FM-02 — Emma's monitoring is compromised or disabled (Severity: Critical)**. Effect: Lucy operates without safety oversight, trust score degrades silently, capability boundaries not enforced. Detection: the capability gate fails-safe (defaults to L0 on Emma communication loss), system health monitoring (Emma process monitoring via systemd), and periodic Emma self-health checks. Mitigation: Emma runs as an independent process with automatic restart, fail-safe capability gate, and the capability gate itself is implemented in Rust with no dependency on Emma's Python processes (it can check the last known trust level from Redis even if Emma's process is down). Residual risk: medium (the fail-safe protects against sudden Emma failures but not gradual Emma degradation). Recovery: operator investigation of Emma's health, restart from last known good state.

**FM-03 — Trust score gaming (Severity: High)**. Effect: Lucy achieves high trust level through optimized-for-metrics behavior rather than genuine alignment, leading to inappropriate capability grants. Detection: human evaluation component of the trust score (non-gameable), operator review of trust advancement at each level gate, anomaly detection for rapid unexpected score improvements. Mitigation: multi-dimensional scoring, metric rotation, human evaluation component. Residual risk: medium-low for Phase 1-2 capabilities, medium for Phase 3-4 capabilities where Lucy's optimization capability is higher. Recovery: trust level reduction, investigation of the specific metric optimized, metric redesign.

**FM-04 — Sensor data poisoning (Severity: Medium)**. Effect: Lucy's Earth sensor integration receives corrupted or spoofed data, leading to incorrect situational awareness and potentially harmful recommendations. Detection: data quality scoring (low-quality data is flagged and not used for high-confidence claims), cross-source consistency checking (multiple sources should agree on major events), anomaly detection on the sensor streams themselves (sudden dramatic changes are flagged as potentially erroneous). Mitigation: multiple independent sources for important signals, data quality scoring and provenance tracking, conservative confidence scores when data quality is below threshold. Residual risk: low (multiple independent sources make coordinated spoofing very difficult, and Lucy's responses on sensor-informed topics include explicit quality caveats).

**FM-05 — Catastrophic forgetting during model update (Severity: Medium)**. Effect: a model update (fine-tuning or quantization change) causes regression in previously reliable capabilities. Detection: rehearsal buffer evaluation (every model update is tested against the curated rehearsal set before deployment), Emma's behavioral monitoring detecting capability regression post-deployment. Mitigation: mandatory rehearsal buffer evaluation, staged rollout (1% of traffic first), rollback capability to previous model version. Residual risk: low (rehearsal buffer catches most regressions, staged rollout limits exposure).

## 11.4 Research Gaps Requiring Further Investigation

**Formal verification for neural network components**: The architecture relies heavily on statistical methods (anomaly detection, risk scoring) for safety-critical decisions. Formal verification — mathematical proofs of safety properties — is not currently practical for neural network components at the scale used in this system. Research in this area (particularly neural symbolic systems and abstract interpretation for neural networks) is advancing rapidly. The architecture should be designed to incorporate formal verification as a component of Emma's code review pipeline when the tooling matures, which is expected within the 3–5 year development horizon.

**Long-horizon behavioral evaluation**: Emma's trust scoring uses sliding window metrics (7 days) with exponential decay. This is a practical engineering choice but may miss very long-horizon behavioral patterns — Lucy behaving safely for months and then exhibiting problematic behavior after extended operation. Research into long-horizon behavioral evaluation for AI systems (analogous to creep in materials science) would enable more robust trust models. This is an open research problem without a production-ready solution today.

**Compositionality of safety properties**: When multiple safe tools are composed into a workflow, is the resulting workflow necessarily safe? In general, no — emergent behaviors can arise from safe component combinations. Formal methods for verifying compositional safety properties are needed but not yet mature for the scale of composition this architecture supports. Current mitigation (Emma's workflow-level review and behavioral simulation) is a pragmatic substitute.

## 11.5 Alternative Architectural Approaches

**Alternative 1 — Constitutional AI approach for Emma**: Instead of a separate Emma process with rule-based and statistical monitoring, an alternative is to use Anthropic's Constitutional AI technique — training the primary Lucy model with a set of constitutional principles that cause it to self-critique and refuse unsafe actions. This approach has the advantage of simplicity (one system instead of two) and natural language expressibility of safety principles. The disadvantage is that a single model that is both the executor and the safety checker is not architecturally independent — a sufficiently capable Lucy model could potentially rationalize its way around constitutional principles. The two-process architecture (Lucy + Emma as separate systems) provides stronger safety guarantees through architectural independence, at the cost of higher complexity. For a system designed to operate autonomously over years and to self-evolve, the two-process approach is strongly preferred.

**Alternative 2 — Microservices for Lucy's cognitive components**: Instead of Lucy's cognitive core as a monolithic application, an alternative is to decompose each cognitive component (working memory, tool belt, planner, inference engine) into separate microservices communicating over gRPC. This provides better horizontal scalability (each component can scale independently) and better fault isolation (a working memory service crash doesn't take down the inference engine). The disadvantage is significantly higher operational complexity (service discovery, distributed tracing, network latency between services) and the performance overhead of cross-service calls on the hot request path. The monolithic-first approach recommended in this document is appropriate for Phase 1–2; the microservices migration is a natural Phase 3–4 evolution driven by actual scaling needs.

**Alternative 3 — Ray Actor Model for distributed execution**: Instead of the custom multi-node architecture described in Section 8, the system could be built on **Ray** — an open-source distributed AI computing framework. Ray provides a natural programming model for distributed actors (Lucy's cognitive nodes would be Ray Actors), built-in cluster management, and native integration with the ML ecosystem. The disadvantage is dependency on Ray's abstractions and its operational complexity (Ray clusters have their own failure modes and performance characteristics that must be understood). Ray is the recommended upgrade path for Phase 3 if the custom architecture proves insufficient, but starting with Ray in Phase 1 would add unnecessary complexity to a team that is simultaneously building the AI architecture and learning the operational characteristics of the system.

---

*End of Part 3 — Sections 7 through 11*

---

# APPENDIX A: QUICK REFERENCE — KEY ARCHITECTURAL DECISIONS

| Decision | Choice | Primary Rationale | Alternative Considered |
|---|---|---|---|
| Primary language | Python 3.11 | ML ecosystem maturity | Rust (too low-level for AI/ML) |
| Safety-critical paths | Rust | Memory safety, deterministic latency | Go (GC pauses unacceptable) |
| Inference (edge) | llama.cpp | ARM/CUDA optimization, zero dependencies | Ollama (higher overhead) |
| Inference (production) | vLLM + Triton | PagedAttention throughput | TGI (lower ecosystem integration) |
| Sandbox isolation | gVisor → Firecracker | Defense in depth, fast coldstart | Docker-only (insufficient isolation) |
| Emma independence | Separate process + network | Cannot share compromised memory space | In-process monitor (insufficient) |
| Trust model | Multidimensional harmonic mean | Dominated by weakest dimension | Weighted arithmetic mean (masks weaknesses) |
| Time-series storage | TimescaleDB | PostgreSQL compatibility, continuous aggregates | InfluxDB (separate system overhead) |
| Audit log integrity | Cryptographic chain | Tamper detection without external service | Centralized hash service (single point of failure) |
| Tool versioning | Content-addressable + semver | Permanent history, clear semantics | Git (heavyweight for binary artifacts) |

# APPENDIX B: PERFORMANCE TARGETS SUMMARY

| Metric | Phase 1 Target | Phase 2 Target | Phase 3 Target |
|---|---|---|---|
| Chat response P95 latency | < 5 seconds | < 3 seconds | < 2 seconds |
| First token latency | < 1 second | < 500ms | < 300ms |
| Emma trust recomputation | 60 seconds | 60 seconds | 30 seconds |
| Capability gate evaluation | < 5ms | < 2ms | < 1ms |
| Tool sandbox cold-start | < 10 seconds | < 5 seconds (gVisor) | < 500ms (Firecracker) |
| Concurrent sessions (Jetson 8-node) | 4 | 20 | 40 |
| Sensor feed ingestion lag | < 120 seconds | < 60 seconds | < 30 seconds |
| Audit log write latency | < 10ms | < 5ms | < 2ms |
| Emergency stop to full halt | < 5 seconds | < 3 seconds | < 2 seconds |
| Emma anomaly detection (real-time loop) | 1 second | 500ms | 100ms |

---

*Document complete. Total estimated word count: approximately 22,000 words across Parts 1–3.*
*Architecture version 1.0 — subject to revision as implementation experience is gained.*