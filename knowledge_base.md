# Knowledge Base — Platform Engineering Intelligence Agent

## 1. Curated Resource List

These are the sources the agent should monitor, organized by domain. RSS availability and priority level are noted for implementation planning.

### DevOps & Platform Engineering

| Source | URL | RSS | Priority |
|--------|-----|-----|----------|
| DORA State of DevOps Report | https://dora.dev | No (annual) | High — foundational research |
| Platformengineering.org | https://platformengineering.org | Yes | High — IDP patterns |
| The New Stack | https://thenewstack.io | Yes | High — cloud-native, platform eng |
| Humanitec Blog | https://humanitec.com/blog | Yes | Medium — platform maturity models |
| PlatformCon recordings | https://platformcon.com | No (event) | Low — periodic review |

**Key reference books:** Team Topologies (Skelton & Pais), Platform Engineering on Kubernetes (Salatino)

### DevSecOps

| Source | URL | RSS | Priority |
|--------|-----|-----|----------|
| OWASP Top 10 / ASVS / SAMM | https://owasp.org | Partial | High — security maturity frameworks |
| Snyk Blog & State of OSS Report | https://snyk.io/blog | Yes | High — open source security data |
| CISA Advisories | https://www.cisa.gov | Yes | High — vulnerability alerts |
| tl;dr sec Newsletter | https://tldrsec.com | Yes (email) | High — curated appsec signal |

### QA & Testing

| Source | URL | RSS | Priority |
|--------|-----|-----|----------|
| Ministry of Testing | https://www.ministryoftesting.com | Yes | Medium — QA community, strategy |
| Google Testing Blog | https://testing.googleblog.com | Yes | Medium — test infra at scale |
| Applitools Blog | https://applitools.com/blog | Yes | Medium — visual regression, AI testing |
| Launchable Blog | https://www.launchableinc.com/blog | Yes | Medium — predictive test selection |
| Mabl Blog | https://www.mabl.com/blog | Yes | Low — intelligent test automation |

### Performance Testing

| Source | URL | RSS | Priority |
|--------|-----|-----|----------|
| k6 Blog & Docs | https://k6.io/blog | Yes | High — already in toolchain |
| Grafana Labs Blog | https://grafana.com/blog | Yes | Medium — observability + perf |
| Brendan Gregg's Blog | https://www.brendangregg.com/blog | Yes | Medium — systems performance authority |
| Gatling Blog | https://gatling.io/blog | Yes | Low — enterprise perf patterns |

### Ticketing & ITSM

| Source | URL | RSS | Priority |
|--------|-----|-----|----------|
| ServiceNow Community | https://community.servicenow.com | Partial | High — L'Oréal's ITSM platform |
| ServiceNow Developer Blog | https://developer.servicenow.com/blog | Yes | High — integration patterns |
| IT4IT Reference Architecture | https://www.opengroup.org/it4it | No | Medium — meta-framework |
| ITIL 4 Practice Guides | https://www.axelos.com | No | Low — vocabulary alignment |

### Cross-Cutting / Engineering Leadership

| Source | URL | RSS | Priority |
|--------|-----|-----|----------|
| InfoQ | https://www.infoq.com | Yes | High — architecture, eng leadership |
| LeadDev | https://leaddev.com | Yes | High — managing managers, org design |
| ThoughtWorks Technology Radar | https://www.thoughtworks.com/radar | No (biannual) | Medium — emerging vs established |
| Gartner Hype Cycle for DevOps | Via L'Oréal subscription | No | Medium — executive-level language |

---

## 2. Agent Architecture — Phase Plan

### Phase 1: RSS-to-LLM Digest (MVP)

**Goal:** Daily digest of relevant content delivered to Slack or email.

**Components:**
- GitHub Action on cron schedule (daily, early morning EST)
- RSS feed parser (feedparser for Python, or rss-parser for Node)
- Claude API (claude-sonnet model for cost efficiency) for relevance scoring and summarization
- Slack webhook or email for delivery

**Pipeline flow:**
1. Pull RSS feeds from all sources with feeds available
2. Deduplicate against previously seen article URLs (stored in a simple JSON file or SQLite in the repo)
3. For each new article, send title + description to Claude API with a relevance scoring prompt
4. Filter to articles scoring above threshold
5. Generate a categorized digest with 2-3 sentence summaries per article
6. Post to Slack channel or send via email

**Relevance scoring prompt should encode:**
- L'Oréal's current DevOps maturity (early-stage, foundational improvements are highly relevant)
- The specific toolchain: ServiceNow, GitHub, Kubernetes, Terraform, Spring Boot, SonarQube, Snyk
- Strategic priorities: CI/CD standardization, observability, developer experience, AI-augmented development
- Security advisories for tools in the stack should always score high
- Vendor announcements for tools in the stack should score high
- General thought leadership scores lower unless it directly relates to platform engineering org design

### Phase 2: Full Content Analysis

**Additions over Phase 1:**
- web_fetch or scraping for sources without RSS feeds (DORA, OWASP updates, ThoughtWorks Radar)
- Full article text sent to Claude for deeper summarization (not just title + description)
- Weekly trend synthesis: "This week, 3 sources discussed X" pattern detection
- Tagging system: security-advisory, vendor-update, best-practice, org-design, tool-comparison

### Phase 3: Searchable Knowledge Store

**Additions over Phase 2:**
- Vector store (e.g., ChromaDB, Pinecone, or pgvector) for semantic search over historical articles
- Query interface: "What have I seen recently about platform engineering team structures?"
- Competitive intelligence tracking: what other large enterprises are doing with platform engineering
- Integration with the Experience ID pattern for traceability (optional — may be over-engineering)

---

## 3. Relevant Technical Context

### Experience ID Pattern

A persistent identifier embedded in Git branch names that propagates through ServiceNow change requests, GitHub PRs, all pipeline stages, GKE pod labels, and Slack notifications. Enables genuine DORA metric measurement rather than approximation from disconnected data. This concept may inform how the agent tags and traces content through its own pipeline.

### Claude API Usage Patterns (from Demo Pipeline)

- Model: claude-sonnet for cost efficiency in automated pipelines
- Structured output via prompt engineering (JSON response format)
- Error handling: retry with exponential backoff, graceful degradation if API is unavailable
- Cost management: only send content that passes initial filtering to the LLM

### GitHub Actions Patterns (from Demo Pipeline)

- Secrets management via GitHub Secrets
- Cron-triggered workflows
- Artifact caching between steps
- Slack notification integration via webhook

---

## 4. Success Criteria

The agent is successful if it:
1. Surfaces at least one actionable insight per week that Chris would not have found through passive browsing
2. Catches security advisories relevant to L'Oréal's toolchain within 24 hours of publication
3. Reduces time spent manually scanning sources from ~30 min/day to ~5 min reviewing the digest
4. Provides a visible, shareable artifact that demonstrates AI-augmented workflow patterns to Chris's teams
