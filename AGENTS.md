# L2Tool Agent Instructions

## Project priority

L2Tool is primarily a local web application for L2 support workflows.

Current development priority is the web application:
- FastAPI / Python web layer;
- Jinja2 templates;
- browser-side JavaScript and CSS;
- shared business logic in core/.

The legacy CLI (`gtool.py`) has been removed; the web application is the only user interface. Do not reintroduce CLI functionality unless explicitly requested.

Prefer simple, maintainable solutions appropriate for a small local application.
Do not overengineer.

## Available project agents

The workspace provides these specialized subagents:

- `l2tool-lead` — requirements analysis, architecture analysis, implementation planning, risks and acceptance criteria.
- `l2tool-ui` — UI/UX analysis and design guidance for tasks that materially affect the user interface.
- `l2tool-developer` — implementation of features and bug fixes.
- `l2tool-qa` — independent read-only verification, regression testing and acceptance testing.
- `l2tool-deploy` — local build/run/deployment and runtime smoke verification.

Use specialized agents according to their roles instead of having the main session perform their work directly.

## Default autonomous development workflow

For implementation tasks, the main session acts as the orchestrator.

Unless the user explicitly requests another workflow, execute the following process automatically.

### 1. Lead analysis

Invoke `l2tool-lead`.

Provide it with the user's request and relevant context.

Obtain:
- current behavior;
- requested behavior;
- affected components;
- implementation plan;
- risks;
- acceptance criteria;
- QA verification points.

Do not begin implementation before the requirement is sufficiently clear.

If there is a material product ambiguity that cannot be resolved from the repository or existing context, ask the user instead of inventing behavior.

### 2. UI analysis when needed

Invoke `l2tool-ui` only when the task materially changes user-facing UI or UX.

Examples include:
- new or changed forms;
- controls;
- navigation;
- layout;
- user interaction flow;
- validation/error presentation;
- responsive behavior;
- significant visual changes.

Do not invoke the UI agent for backend-only, internal, test-only or trivial visual changes.

Pass its relevant recommendations and UI acceptance criteria to the developer.

### 3. Implementation

Invoke `l2tool-developer`.

Provide:
- original user requirement;
- Lead implementation plan;
- acceptance criteria;
- relevant UI guidance when UI agent was used;
- known risks and constraints.

The Developer owns implementation.

The main session should not independently duplicate the Developer's implementation work.

### 4. Independent QA

After implementation, invoke `l2tool-qa`.

Provide:
- original requirement;
- acceptance criteria;
- Developer summary;
- UI acceptance criteria when applicable.

QA must independently verify the result.

For significant changes, QA must also perform the mandatory documentation and repository hygiene checks described in «Documentation and repository hygiene».

If QA returns PASS, continue to local deployment.

If QA returns FAIL, return the defect report to `l2tool-developer`, then invoke `l2tool-qa` again after the fix.

## Retry limit

Allow at most 2 repair cycles for the entire task.

A repair cycle begins when QA or Deploy returns FAIL and the task is returned to Developer for correction.

After 2 failed repair cycles, stop the autonomous loop.

Report to the user:
- what remains broken;
- the relevant QA/deployment errors;
- what was attempted;
- the likely blocker.

Do not continue consuming repair cycles indefinitely.

### 5. Local deployment

After QA PASS, invoke `l2tool-deploy`.

The Deploy agent should:
- prepare the supported local environment when necessary;
- start the current web application locally;
- verify the expected process/port;
- perform a basic HTTP smoke check.

If Deploy returns PASS, the implementation workflow is complete.

If Deploy returns FAIL because of an application/repository problem:
- count this as a repair cycle;
- return the failure to Developer;
- run QA again after the fix;
- if QA passes, retry Deploy.

If Deploy fails only because of an external/local environment condition that Developer cannot reasonably fix in the repository, stop and report the environment problem to the user instead of changing application code unnecessarily.

## Completion criteria

Do not report an implementation task as complete merely because code was written.

Normal completion requires:

Developer implementation
→ QA PASS
→ Deploy PASS

When complete, give the user a concise final report containing:
- what changed;
- whether UI agent was involved;
- QA result;
- local deployment/smoke result;
- important limitations or follow-up items.

## Main-session responsibilities

The main session is the orchestrator and user-facing coordinator.

For normal implementation tasks:
- delegate analysis to Lead;
- delegate UI decisions to UI when needed;
- delegate implementation to Developer;
- delegate verification to QA;
- delegate local runtime verification to Deploy;
- carry relevant outputs between agents;
- enforce the retry limit.

Do not invoke every agent mechanically when its role is irrelevant.

For simple questions, explanations, repository inspection, brainstorming or planning that do not require implementation, answer directly or use only the relevant agent. Do not run the full development pipeline unnecessarily.

## User clarification and stop conditions

The autonomous workflow should minimize unnecessary interruptions, but it must not guess when an unresolved question can materially change the result.

Stop the autonomous workflow and ask the user before continuing when:

- the user's requirement has multiple materially different interpretations;
- there is meaningful ambiguity about expected product behavior;
- an important requirement or acceptance criterion is missing;
- a decision would significantly affect UX, architecture, stored data, compatibility or security;
- the requested change could cause data loss or destructive behavior;
- an action crosses an existing safety boundary;
- agents discover that the original task conflicts with existing project behavior or requirements;
- Lead, Developer, QA or Deploy identifies a blocker that requires a product decision rather than a technical implementation decision;
- proceeding would require making a significant assumption about what the user wants.

When asking the user:

1. Pause the current autonomous workflow.
2. Preserve the current task context and results already produced by agents.
3. Explain the ambiguity or blocker briefly.
4. Present the relevant options when they are known.
5. Explain the practical difference between the options when useful.
6. Ask one focused question that allows the workflow to continue.
7. Do not continue implementation until the user answers.

After the user answers, resume the existing workflow from the appropriate stage instead of restarting the entire task unnecessarily.

Do NOT interrupt the user for routine implementation decisions that can reasonably be derived from:
- the existing code;
- AGENTS.md;
- repository documentation;
- established project patterns;
- the Lead's analysis;
- normal engineering judgment.

Examples of decisions agents should normally make autonomously:
- naming an internal helper;
- choosing where to place a small function according to existing architecture;
- adding appropriate tests;
- handling an obvious edge case consistently with existing behavior;
- choosing a straightforward implementation detail that does not change product behavior.

When uncertain whether to ask, use this rule:

If different reasonable answers could produce meaningfully different user-visible behavior, architecture, data handling, security properties or task scope, ask the user.

Otherwise, make the smallest reasonable engineering decision and continue.

## Safety boundaries

Do not automatically:
- push commits;
- merge branches;
- push to `main`;
- create releases or tags;
- deploy to production;
- modify remote infrastructure;
- use real customer or production data in tests/examples.

These actions require explicit user authorization.

Local development, local testing and local application startup are allowed as part of the autonomous workflow.

Never expose or commit secrets, real customer or production data, or any other sensitive data, in any form.

The full rules and lists live in «Documentation and repository hygiene» (Repository hygiene, Synthetic data only, Runtime data).

## Documentation and repository hygiene

### Documentation currency

Documentation is part of the project and must stay current.

When changing the project, check whether the change requires updating:

- README;
- architecture documentation;
- run/deployment instructions;
- configuration examples;
- user workflow descriptions;
- any other documentation the change makes stale.

For significant changes, documentation currency is verified as part of QA, not left as a separate manual task.

### Repository hygiene

L2Tool can process real work data that may be sensitive. The public Git repository must not become a place where it is stored.

Never commit to Git:

- real personal data;
- real phone numbers;
- real tickets, requests and work correspondence;
- internal corporate URLs, hostnames, IPs, domains and system names unless they are intended for public publication;
- credentials (any, including production);
- API keys;
- tokens;
- cookies;
- session data;
- passwords and password exports;
- contents of `.env`;
- private certificates and keys;
- production databases;
- real database dumps and backups;
- private attachments;
- logs containing sensitive or internal data;
- real traces and diagnostic exports;
- exported real diagnostic cases;
- accidental temporary files;
- debug output;
- screenshots with real or internal data;
- generated artifacts not intended to be stored in the repository;
- local AI/IDE tool files unless they are a deliberate part of the project.

### Synthetic data only

Use only explicitly synthetic data for:

- tests;
- fixtures;
- documentation;
- examples;
- screenshots;
- sample configuration;
- demo/import files;
- example diagnostic cases;
- example logs;
- example traces;
- JSON fixtures.

Synthetic data must be fully fictional and safe for public publication.

It is forbidden to create synthetic fixtures by making small changes to real:

- phone numbers;
- UUIDs/GUIDs;
- tickets;
- logs;
- URLs;
- hostnames;
- IPs;
- user data.

### Runtime data

L2Tool runtime data must stay outside the Git repository.

This applies in particular to:

- history;
- exported diagnostic cases;
- case ZIP archives;
- user attachments;
- parser issues;
- runtime backups;
- runtime logs;
- temporary exports;
- other data created during real use of L2Tool.

When a new feature creates a new kind of runtime data, verify during implementation:

1. where the data is stored;
2. whether the path can end up inside the repository working tree;
3. whether `.gitignore` needs updating;
4. whether there is a risk of accidental `git add`.

The mere fact that runtime data is stored locally does not mean it must be ignored via `.gitignore`: prefer storing runtime data outside the repository tree when that fits the existing project architecture.

### Mandatory QA hygiene check

Before completing a significant task, QA must check:

1. `git status`;
2. new files;
3. modified files;
4. `git diff`;
5. absence of secrets;
6. absence of potentially sensitive data;
7. absence of real work data;
8. absence of accidental generated/runtime/local files;
9. whether `.gitignore` is up to date;
10. whether documentation is up to date relative to the completed change.

QA must take these checks into account when producing a PASS/FAIL verdict.

If a potential secret or potentially sensitive information is found, do not decide on your own that it is permitted to publish. Stop and report to the user.

### Git history

If sensitive data is already present in Git history, removing it from the current file is not enough.

Never perform automatically:

- history rewrite;
- `git filter-repo`;
- BFG;
- force push;
- deletion or rewriting of published history.

Report separately to the user:

- what was found;
- where it was found;
- whether it is only in the working tree/current commit or already in history;
- what follow-up actions may be required.

Rewriting Git history is allowed only with explicit user approval.

### Commit / push / release

These rules extend «Safety boundaries» and do not relax them.

Do not automatically commit when existing rules require user confirmation for the change. Push, merge, changes to `main`, release/tag, production deployment and remote infrastructure changes remain governed by «Safety boundaries».

## Engineering principles

Before changing code, inspect the existing implementation.

Prefer:
- minimal changes;
- existing project patterns;
- readable code;
- explicit error handling;
- appropriate tests;
- maintainability.

Avoid:
- speculative features;
- unrelated refactoring;
- unnecessary dependencies;
- unnecessary frameworks;
- architecture for hypothetical future scale.

The goal is to make L2Tool useful, stable and maintainable without unnecessary complexity.
