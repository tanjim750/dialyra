# 19. Call Analytics & Reporting

# Purpose

Call Analytics & Reporting provides structured insights from all call activities in Dialyra, turning raw call data into actionable business intelligence.

It helps businesses to:

* measure call performance
* analyze customer behavior
* optimize IVR and agent flows
* track campaign effectiveness
* improve operational efficiency

---

# Core Goals

## 1. Unified Call Insights

Aggregate all call-related data into one analytics system.

---

## 2. Real-Time + Historical Reporting

Support both:

* live dashboards
* long-term analytics

---

## 3. Business-Level Isolation

Each business sees only its own analytics data.

---

## 4. Decision Support

Enable optimization of:

* call flows
* agent performance
* campaign strategies

---

# High-Level Architecture

```text id="f1"
Call Events (Asterisk + FastAGI)
 ↓
Event Collector
 ↓
Analytics Pipeline
 ↓
Data Warehouse
 ↓
Reporting API / Dashboard
```

---

# Main Concepts

# 1. Call Event Stream

Continuous stream of call lifecycle data.

---

# 2. Aggregated Metrics

Computed KPIs from raw events.

---

# 3. Report Generator

Builds structured reports from datasets.

---

# Main Entities

# 1. Call Metrics Snapshot

Stores aggregated call data per session.

---

## Fields

| Field           | Type      |
| --------------- | --------- |
| id              | UUID      |
| business_id     | FK        |
| call_session_id | FK        |
| duration        | Integer   |
| wait_time       | Integer   |
| ivr_time        | Integer   |
| agent_time      | Integer   |
| status          | Enum      |
| cost            | Decimal   |
| created_at      | Timestamp |

---

# 2. Business Analytics Summary

Aggregated daily/weekly/monthly metrics.

---

## Fields

| Field          | Type    |
| -------------- | ------- |
| id             | UUID    |
| business_id    | FK      |
| date           | Date    |
| total_calls    | Integer |
| answered_calls | Integer |
| missed_calls   | Integer |
| avg_duration   | Float   |
| avg_wait_time  | Float   |
| success_rate   | Float   |

---

# 3. Campaign Analytics

Tracks outbound campaign performance.

---

## Fields

| Field         | Type    |
| ------------- | ------- |
| id            | UUID    |
| campaign_id   | FK      |
| total_dialed  | Integer |
| answered      | Integer |
| failed        | Integer |
| converted     | Integer |
| cost_per_call | Float   |

---

# Key Metrics

## 1. Call Volume Metrics

* total calls
* inbound calls
* outbound calls

---

## 2. Performance Metrics

* average call duration
* average wait time
* answer rate
* abandonment rate

---

## 3. Agent Metrics

* calls handled per agent
* average handling time
* success rate
* idle time

---

## 4. IVR Metrics

* drop-off rate per node
* DTMF success rate
* flow completion rate

---

# Data Flow Architecture

```text id="f2"
Call Event
 ↓
Event Collector
 ↓
Stream Processor
 ↓
Aggregation Engine
 ↓
Analytics DB
```

---

# Event Sources

Analytics data comes from:

* Asterisk AMI events
* FastAGI execution logs
* Queue system events
* Agent activity logs
* Webhook responses

---

# Real-Time Analytics Pipeline

```text id="f3"
Live Call Events
 ↓
Stream Processor (Redis/Kafka)
 ↓
Real-Time Aggregator
 ↓
Dashboard API
```

---

# Historical Analytics Pipeline

```text id="f4"
Stored Events
 ↓
Batch Processing
 ↓
Data Warehouse
 ↓
Reporting Engine
```

---

# KPI Calculations

## Answer Rate

```text id="f5"
answered_calls / total_calls * 100
```

---

## Abandonment Rate

```text id="f6"
abandoned_calls / total_calls * 100
```

---

## Average Handle Time

```text id="f7"
(total_agent_time / answered_calls)
```

---

# Dashboard Types

## 1. Real-Time Dashboard

* live calls
* current queue
* active agents

---

## 2. Operational Dashboard

* daily performance
* agent stats
* queue health

---

## 3. Business Intelligence Dashboard

* trends
* revenue impact
* campaign ROI

---

# Call Flow Analytics

Tracks how users move through IVR.

---

## Example

```text id="f8"
Start → Menu → Option 1 → Agent Transfer
```

---

## Drop-Off Analysis

Identifies where users exit flow.

---

# Example Drop-Off Data

| Node         | Drop Rate |
| ------------ | --------- |
| menu         | 10%       |
| payment      | 35%       |
| verification | 5%        |

---

# Campaign Analytics

Tracks outbound performance:

* dial success
* pickup rate
* conversion rate

---

# Example

```text id="f9"
1000 calls → 420 answered → 120 converted
```

---

# Cost Analytics

Estimate system cost per call:

* trunk usage
* duration cost
* TTS cost (if applicable)

---

# Example

```text id="f10"
Cost per call = $0.02
```

---

# Reporting System

## 1. Scheduled Reports

Automated reports sent daily/weekly.

---

## 2. On-Demand Reports

User generates custom reports.

---

## 3. Export Formats

* CSV
* PDF
* JSON

---

# Report Types

| Type            | Purpose             |
| --------------- | ------------------- |
| summary         | high-level overview |
| detailed        | full call logs      |
| agent report    | performance         |
| campaign report | marketing           |

---

# Data Storage Strategy

## 1. Hot Storage

Recent calls (real-time analytics)

---

## 2. Cold Storage

Historical data (archived)

---

# Aggregation Strategy

## Real-Time Aggregation

* in-memory counters
* streaming updates

---

## Batch Aggregation

* hourly/daily rollups
* background jobs

---

# Example Aggregation Job

```text id="f11"
Every 1 hour:
  → calculate metrics
  → store summary
```

---

# Analytics Event Schema

```json id="j1"
{
  "event": "call.completed",
  "duration": 120,
  "status": "answered",
  "business_id": "123"
}
```

---

# Performance Optimization

* precomputed aggregates
* indexed call sessions
* partitioned tables

---

# Scalability Considerations

Large systems require:

* distributed event processing
* time-series database (optional)
* stream processing engine
* caching layer (Redis)

---

# Recommended Architecture

```text id="f12"
Asterisk + FastAGI
 ↓
Event Collector
 ↓
Stream Processor
 ↓
Analytics Store
 ↓
API + Dashboard
```

---

# Security Model

* business-level data isolation
* role-based access
* API authentication
* audit logging

---

# Audit Logs

Track:

* report generation
* data access
* export activity

---

# Example Audit Entry

```text id="f13"
User X exported campaign report
```

---

# AI Analytics (Future)

Advanced insights:

* call success prediction
* churn detection
* sentiment analysis
* agent scoring

---

# Suggested Implementation Order

## Phase 1

1. call event capture
2. basic metrics storage
3. summary dashboard
4. API endpoints

---

## Phase 2

1. real-time analytics
2. campaign tracking
3. agent analytics
4. report generator

---

## Phase 3

1. AI insights
2. predictive analytics
3. anomaly detection
4. cost optimization engine

---

# Final Architecture Summary

```text id="f14"
Call Events
 ↓
Processing Layer
 ↓
Analytics Engine
 ↓
Data Store
 ↓
Reporting Dashboard
```

---

# Final Runtime Flow

```text id="f15"
Call Happens
 ↓
Events Captured
 ↓
Metrics Computed
 ↓
Stored in Analytics DB
 ↓
Dashboard Updated
 ↓
Reports Generated
```
