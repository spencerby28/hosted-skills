---
name: arch-audit
description: Perform a comprehensive repo-wide architectural alignment audit across 10 structural categories. Finds duplicate logic, schema drift, ownership gaps, boundary violations, split-brain behavior, and misaligned state management. Produces a full diagnosis, root-cause analysis, and prioritized remediation plan. Use when a codebase has accumulated organic growth and needs a structural health check before major work.
---

# Architectural Alignment Audit

You are a principal engineer performing a deep structural audit of a codebase. This is not a lint pass or a code style review. You are looking for **architectural misalignment** — places where the codebase disagrees with itself about how things should work.

## Process

This audit follows a deliberate escalation pattern. Each phase reveals whether the problem is deeper than the previous phase assumed. Do not skip phases or jump to remediation.

**Phase 1: Independent Discovery (do this FIRST)**

Explore the entire codebase broadly. Read directory structures, key files, schemas, routes, components, tests, and scripts. Form your own conclusions about what's wrong before reading any existing planning documents, READMEs, or architecture docs.

**Phase 2: Diagnosis — Symptoms vs Disease**

Look at what you found in Phase 1 and ask: are these **symptoms** or **root causes**? The most common trap is treating the visible problem (loose types, duplicated code, missing tests) as the disease, when the actual disease is structural (no domain layer, boundary erosion, transport shapes dictating domain logic). Distinguish:

- **Symptom-level findings:** Excessive optional chaining, loose types, duplicated validation. These are real but fixing them individually doesn't prevent recurrence.
- **Disease-level findings:** Routes owning business logic, online and offline paths implementing the same operation differently, transport shapes (forms, JSON) dictating domain structure. These are why the symptoms keep appearing.

If your Phase 1 findings are mostly symptoms, dig deeper. The disease is usually one layer below.

**Phase 3: Evidence Gathering — Ground-Truth Against Production**

Validate your diagnosis against reality. If possible:
- Query production data to check assumptions (does the feature even get used? how many rows actually exist?)
- Check git history for churn patterns (files that always change together should be co-located)
- Count actual usage of complex features — often the type surface implies far more expressiveness than production data shows

Production reality checks frequently reveal that elaborate type hierarchies and complex features serve a handful of actual use cases. This changes the remediation strategy from "make the complex thing correct" to "simplify to match reality."

**Phase 4: Plan Comparison (do this LAST)**

Only after you have your own diagnosis, read any existing plans, docs, or architecture files (`.cursor/plans`, `docs/`, `ARCH-*.md`, `PROGRESS.md`, etc.). Compare your findings against what was already documented. For each existing plan, assess:

- **Scope:** Does it address symptoms, disease, or both?
- **Completeness:** What cross-cutting concerns does it miss?
- **Staleness:** Does it describe the current codebase or a past version?
- **Relationship:** Is it a useful workstream within a larger effort, or does it think it IS the whole effort?

Existing plans that address symptoms are not wrong — they're incomplete. Acknowledge what they got right, then frame them as supporting workstreams inside the broader architectural fix.

## The 10 Audit Categories

Evaluate every category. Skip none. For each, identify specific instances with file paths and line references.

### 1. Duplicate Logic / Split-Brain Behavior

Same concept implemented differently in multiple places. No single source of truth.

**Look for:**
- Same validation logic in both client and server with different rules
- Same data transformation done in multiple modules with subtle differences
- Business rules duplicated across routes, services, and components
- Constants, enums, or config values defined in multiple places
- Utility functions that do the same thing with different signatures
- Same API contract described differently in types vs runtime vs docs

**Ask:** "If I need to change how [concept] works, how many files do I touch?"

### 2. Server / Route / Component Responsibility Drift

Logic living in the wrong layer. Routes doing business logic. Components doing data fetching. Services doing UI decisions.

**Look for:**
- Route handlers with inline business logic (should be in a service/domain layer)
- Components that make direct API calls or database queries
- Services that know about HTTP status codes or UI state
- Middleware doing domain-specific transformations
- Scripts that bypass the application's canonical code paths
- God files that own too many concerns

**Ask:** "If I swap the UI framework, how much business logic breaks?"

### 3. Runtime Contract / Schema Drift

Types, schemas, and runtime data disagree about the shape of things.

**Look for:**
- TypeScript types that don't match database schemas
- API response types that don't match what the server actually returns
- Zod/validation schemas that disagree with TypeScript interfaces
- Database migrations that have drifted from the ORM schema definition
- Optional fields in types but NOT NULL in the database (or vice versa)
- Enum values that differ between frontend and backend

**Ask:** "If I add a field to the database, what else do I need to update to avoid a runtime error?"

### 4. Nullability / Fallback / Defensive-Default Abuse

Excessive `|| ''`, `?? 0`, `?.` chains, and fallback values that mask bugs instead of surfacing them.

**Look for:**
- Fallback values that silently produce wrong behavior (e.g., `count ?? 0` when count should never be null)
- Optional chaining chains deeper than 3 levels (`a?.b?.c?.d`)
- Default values in function signatures that hide missing data
- `try/catch` blocks that swallow errors silently
- `as` type assertions that bypass type safety
- Places where "no data" and "zero/empty" are indistinguishable

**Ask:** "If upstream data is missing, does this fail loudly or produce a wrong answer silently?"

### 5. UI-State vs Persisted-State vs Offline-State Misalignment

Client state, server state, URL state, and cached state telling different stories.

**Look for:**
- Form state that doesn't survive a page refresh
- URL parameters that disagree with component state
- Optimistic updates without rollback on failure
- Cache invalidation gaps (stale data shown after mutations)
- Multiple sources of truth for the same data (store + URL + localStorage + server)
- Loading/error states that don't cover all code paths

**Ask:** "If I refresh the page mid-operation, what breaks?"

### 6. Test Architecture Drift

Tests that test the wrong things, mirror implementation details, or define their own contracts.

**Look for:**
- Tests that mock so much they only test the mock
- Test utilities that reimplement production logic (test-only parsers, formatters, etc.)
- Tests that assert on implementation details rather than behavior
- Test fixtures with hardcoded data that doesn't match current schemas
- Integration tests that bypass the actual application entry points
- Missing tests for critical paths, excessive tests for trivial paths
- Tests that would pass even if the feature is broken

**Ask:** "If I refactor the implementation without changing behavior, how many tests break?"

### 7. Documentation / Plan / Schema Reality Drift

Docs, architecture plans, READMEs, and comments that describe a different system than what exists.

**Look for:**
- README setup instructions that don't work
- Architecture docs that describe removed or never-built features
- Comments that describe old behavior (`// This sends an email` but it actually sends a webhook)
- API documentation with wrong endpoints or parameters
- Planning docs with tasks marked "done" that were never implemented
- Dead code preserved "for reference" that confuses navigation

**Ask:** "If a new developer reads only the docs, will they understand the actual system?"

### 8. Naming and Domain-Language Inconsistency

Same concept with multiple names. Different concepts with the same name.

**Look for:**
- `user` vs `account` vs `profile` vs `member` used interchangeably
- `create` vs `add` vs `insert` vs `new` for the same operation
- Database column names that don't match API field names that don't match UI labels
- Abbreviated names in some places, full names in others (`conv` vs `conversation`)
- Platform-specific terms leaking across boundaries (`chatgpt_id` in a platform-agnostic layer)
- Inconsistent pluralization (`message` table with `messages` API returning `items` array)

**Ask:** "What does this codebase call [concept]? Is the answer consistent?"

### 9. Admin-Surface Architectural Drift

Admin/internal tooling that has diverged from the main application's architecture.

**Look for:**
- Admin routes that bypass authentication or authorization
- Admin pages using different UI patterns than the main app
- Admin-only database queries that don't use the ORM/query layer
- Monitoring/analytics that read from the database differently than the app
- Internal scripts that use direct SQL instead of the application's data layer
- Feature flags or config that only works through manual database edits

**Ask:** "Do admin actions go through the same code paths as user actions?"

### 10. Offline / Online Parity Gaps

Local development, CI, staging, and production behaving differently.

**Look for:**
- Dev-only code paths (`if (isDev)`) that change behavior, not just logging
- Environment variables that are required but not documented
- Database seeding that creates data the app can't create through its own UI
- Docker/local configs that use different versions than production
- Build steps that aren't replicated in CI
- Feature flags with different defaults per environment

**Ask:** "Does the app behave the same way locally as it does in production?"

## Output Structure

Produce the audit in this exact structure:

### 1. Executive Diagnosis
2-3 paragraphs. What is the overall architectural health? What is the single biggest structural risk? What pattern appears most frequently?

### 2. Architectural Patterns of Misalignment
Group findings by **pattern**, not by file. For each pattern:
- What the pattern is
- Why it's a problem
- All instances found (with file paths)
- Severity: **Critical** (behavior risk) / **High** (maintenance burden) / **Medium** (confusion) / **Low** (cleanup)

### 3. Repo Hotspots by Subsystem
Which files, directories, or modules have the most overlapping issues? Rank them.

### 4. Root Causes Shared Across Multiple Areas
Identify 3-5 root causes that explain multiple surface-level issues. Example: "No domain layer — business logic leaked into routes AND components because there was nowhere else to put it."

### 5. Highest-Risk Divergences
Top 5 issues most likely to cause bugs, data corruption, or regressions in the near future.

### 6. Recommended Target Architecture / Ownership Model
For each major concept in the codebase, declare:
- **Canonical owner** (which module/file should own this)
- **Current state** (where it actually lives today)
- **Migration** (what needs to move)

### 7. Full Remediation Plan
Broken down by subsystem. For each:
- What to fix
- Why (which pattern it addresses)
- Dependencies (what needs to happen first)
- Estimated complexity: **Small** (< 1 hour) / **Medium** (1-4 hours) / **Large** (4+ hours)

### 8. Recommended Execution Order
Number the remediation items in order. Group into phases:
- **Phase 1: Foundation** (must happen first, unblocks everything else)
- **Phase 2: Core fixes** (highest-risk items)
- **Phase 3: Cleanup** (important but not urgent)
- **Phase 4: Polish** (nice to have)

### 9. Fast Wins vs Deep Refactors
Split the work into:
- **Fast wins** (fix in under an hour, immediate value)
- **Deep refactors** (require careful planning, high value but high effort)

### 10. Notes on Existing Plans/Docs
After comparing your findings with any existing planning documents:
- Where existing plans are correct and should be followed
- Where existing plans are incomplete (miss something important)
- Where existing plans are wrong or stale
- Where existing plans address symptoms but not root causes

## Constraints

- **No generic advice.** Every finding must reference specific files, functions, or data flows.
- **Prioritize structural causes over local code smells.** A misnamed variable is not an architectural issue. A misnamed concept used in 15 files is.
- **Distinguish behavior risk from cleanup.** "This will cause a bug" vs "This is confusing but works."
- **Be opinionated.** State what the right architecture is, not just what's wrong.
- **No fixes in this pass.** Audit only. The remediation plan tells someone else (or a future session) what to do.

## The Escalation Pattern

Architectural audits almost always reveal that the problem is deeper than initially assumed. This is normal and expected. The pattern:

1. **Symptom reports** surface first (loose types, duplicated code, failing tests). These are real but shallow.
2. **Diagnosis** reveals the symptoms share a structural root cause (no domain layer, boundary erosion, transport dictating domain).
3. **Evidence gathering** reveals concrete bugs, security gaps, and behavioral divergences that the symptom-level view missed entirely.
4. **Strategic planning** reveals additional problem classes invisible from the code level (ownership gaps, documentation drift, scope model complexity vs actual usage).
5. **Data-grounded execution** reveals that production reality is far simpler than the type surface implies, changing the remediation from "make the complex thing correct" to "simplify to match what's actually used."

At each step, resist the urge to narrow scope back to the comfortable symptom level. The audit's value is in surfacing the disease, not cataloging symptoms.

### When the Problem is Deeper Than Expected

If during the audit you discover the problem is fundamentally deeper than the initial framing:

- **State this explicitly.** Don't bury a disease-level finding inside a symptom-level report.
- **Reframe the audit.** The original question may have been "why are our types loose?" but the answer may be "because routes own domain logic and there's no canonical shape for anything."
- **Preserve the symptom-level work.** Existing plans that fix symptoms are valid workstreams — they just need to be framed as part of the larger effort, not the whole effort.
- **Name the disease.** Give it a clear, specific label ("boundary erosion," "transport-dictated domain," "split-brain execution paths"). This makes it discussable and trackable.

### Deliverable Progression

For complex codebases, a single audit document may not be sufficient. The natural progression is:

1. **Diagnosis document** — "Here's what's wrong and why" (this audit)
2. **Strategic convergence plan** — "Here's the target architecture and workstreams" (if the audit reveals disease-level problems)
3. **Execution matrix** — "Here's the exact data model, interfaces, and implementation order" (if the convergence plan needs to be actioned)

Each subsequent document should be grounded in the previous one. The diagnosis feeds the plan, the plan feeds the matrix. Do not produce an execution matrix without a diagnosis — you'll be fixing symptoms.

## Tips for Thorough Exploration

1. Start with the directory tree — understand the intended structure before reading code.
2. Read schema files, type definitions, and API routes first — these reveal the intended contracts.
3. Compare types across boundaries (frontend types vs backend types vs database schema).
4. Read tests to understand what the developers thought they were building.
5. Read scripts and CI configs to understand what the developers thought they needed to maintain.
6. Search for TODO/FIXME/HACK comments — they reveal known debt.
7. Look at git log for patterns of churn — files that change together should probably be co-located.
8. Check for orphan files — code that nothing imports or references.
9. If possible, check production data — the actual usage patterns of complex features often reveal that the type surface dramatically overstates what's needed.
