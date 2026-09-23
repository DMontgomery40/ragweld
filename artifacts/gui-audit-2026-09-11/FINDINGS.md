# Ragweld: confused, impatient user GUI audit

Status: IN PROGRESS. This is a live findings register, not a completion claim.

Scope: the entire repository's user-facing GUI, reconciled with the live deployment at https://ragweld.dtmont.com/web/. Browser screenshots and interactions captured during this run provide evidence. Source inventory is coverage support, not proof that a screen works or fails.

Each ID names a distinct observed problem. P1 = blocked core task or serious misleading behavior; P2 = substantial confusion/friction/accessibility issue; P3 = local clarity/polish. Recommendations describe the desired correction, not an implemented fix. No artificial issue-count target.

## Authentication

### GUI-001 — P2 — Login screen never identifies Ragweld
- Location: public app entry redirects to ragweld-auth.dtmont.com; centered sign-in block.
- Evidence: [001](screenshots/001-auth-entry.png), 1280×720.
- Observed: generic avatar, “Sign in,” and “Powered by Authelia”; no Ragweld name or destination explanation.
- User impact: someone following an app link cannot confirm which product is asking for their password.
- Desired correction: identify Ragweld and the destination above the form.

### GUI-002 — P2 — No recovery/help route on the login screen
- Location: below Password and Sign in.
- Evidence: [001](screenshots/001-auth-entry.png) and login accessibility tree.
- Observed: no forgotten-password link, contact-owner text, or explanation of how to regain access.
- User impact: a forgotten password is a dead end; users cannot discover the administrative recovery procedure from the interface.
- Desired correction: provide a usable recovery or contact path appropriate to this deployment.

### GUI-003 — P3 — “Remember me” does not explain its duration
- Location: checkbox immediately above Sign in.
- Evidence: [001](screenshots/001-auth-entry.png).
- Observed: the label provides no duration or explanation of what is remembered.
- User impact: a user cannot distinguish saving the username from extending authentication.
- Desired correction: state the session behavior and duration next to the option.

### GUI-004 — P3 — Login has no account-format guidance
- Location: Username field.
- Evidence: [001](screenshots/001-auth-entry.png).
- Observed: only “Username”; no guidance distinguishing owner username from email.
- User impact: a user who normally signs in with email must guess which identity this deployment expects.
- Desired correction: provide an account-format hint without disclosing another user's credentials.

## Shared shell and Dashboard / System Status

### GUI-005 — P2 — Global healthy status conflicts with dependency and alert states
- Location: top-right “Health OK,” Dashboard “HEALTH healthy,” health popover, Admin / Dependencies, and Dashboard / Monitoring.
- Evidence: [008](screenshots/008-dashboard-system-accepted.png), [009](screenshots/009-health-popover.png), and [027](screenshots/027-dashboard-monitoring.png).
- Observed: the shell and System Status summary report healthy; the popover says “All dependencies ready” and labels vLLM “ready” while also saying it is disabled; Admin says four operator surfaces are blocked; Monitoring says two alerts are firing and local generation requests will fail.
- User impact: an impatient operator cannot tell whether the product is safe to use or which “healthy” scope excludes the blocked capabilities.
- Desired correction: label each health scope and roll capability-blocking dependencies into a clearly qualified overall state.

### GUI-006 — P1 — The empty side panel stays open at its saved width with no hide action
- Location: right-side dock while Dashboard / System Status is active.
- Evidence: [008](screenshots/008-dashboard-system-accepted.png), [021](screenshots/021-empty-dock-still-open.png), [037](screenshots/037-chat-interface-current.png), and current Chat geometry: 1,630px viewport, 628px rail, 170px left nav, 833px main content.
- Observed: at the initial saved allocation the panel occupied 628px (38.5% of the viewport); “Clear” removes its content but leaves that space reserved with no conventional hide/close action. Correction: the desktop resize handle was missed in the initial pass. A later direct drag changed the allocation from 348px to 546px and survived reload (step 025). It is inaccurate to call the desktop width permanently fixed.
- User impact: the core workspace receives barely half the viewport even when the secondary surface has no content.
- Desired correction: add one-click hide/show without clearing the Dock target, make the existing splitter discoverable, support remembered per-mode width, and provide minimum widths and dock-aware responsive content for both panes.

### GUI-007 — P2 — Adjacent panes create two competing vertical scroll regions
- Location: Dashboard main pane and docked Admin / Dependencies pane.
- Evidence: [008](screenshots/008-dashboard-system-accepted.png).
- Observed: both columns have independent visible scrollbars with no persistent focus or region label.
- User impact: wheel, trackpad, and keyboard scrolling can affect a different pane than the one the user intended.
- Desired correction: make pane ownership obvious, keep focus visible, and avoid nested scroll regions where one page flow is sufficient.

### GUI-008 — P2 — High-impact jobs look equivalent to a harmless refresh
- Location: Dashboard “Quick Actions.”
- Evidence: [008](screenshots/008-dashboard-system-accepted.png).
- Observed: Generate Keywords, Run Indexer, Run Eval, Reload Config, Corpus, and Refresh Status share the same compact button treatment; no duration, cost, data-change, or consequence text is shown.
- User impact: a rushed user can start a long-running or state-changing operation while believing it is comparable to refreshing status.
- Desired correction: separate read-only navigation/refresh from jobs, and disclose job scope, expected duration, and confirmation behavior before execution.

### GUI-009 — P2 — Two “Refresh Status” controls have no scope distinction
- Location: Runtime card and Quick Actions card.
- Evidence: [008](screenshots/008-dashboard-system-accepted.png).
- Observed: both controls use the exact label “Refresh Status,” but the page does not say whether they refresh the same data or different portions of the dashboard.
- User impact: users cannot predict which control to use or verify that the intended data was refreshed.
- Desired correction: consolidate the actions or name their distinct scopes and provide a last-updated/result state.

### GUI-010 — P2 — “Reload Config” omits source, scope, and outcome
- Location: Dashboard “Quick Actions.”
- Evidence: [008](screenshots/008-dashboard-system-accepted.png).
- Observed: the action does not identify which configuration is reloaded, from where, which services are affected, or whether it restarts anything.
- User impact: an operator cannot judge operational risk before clicking it.
- Desired correction: state the configuration source and affected runtime, then show a bounded confirmation and result.

### GUI-011 — P2 — Internal implementation strings replace user-level status
- Location: Runtime and Index modules within System Status.
- Evidence: [008](screenshots/008-dashboard-system-accepted.png).
- Observed: status text includes values such as “running :58012,” “built bundle,” and transport/backend identifiers instead of explaining what capability is available.
- User impact: the screen requires infrastructure knowledge to interpret and exposes detail that does not help a normal operator decide what to do.
- Desired correction: lead with capability and action-oriented status; place ports and backend identifiers in an expandable diagnostics view.

### GUI-012 — P2 — “Live index accounting: Unavailable” is visually buried inside a healthy page
- Location: Index module within System Status.
- Evidence: [008](screenshots/008-dashboard-system-accepted.png).
- Observed: unavailable live accounting appears as one line inside a green-accented status card while the page-level state remains healthy; the visible state offers no reason or recovery action.
- User impact: users may miss degraded observability or assume the green framing means the complete index status is valid.
- Desired correction: surface degraded sub-capabilities in the summary and provide the cause, effect, and recovery route inline.

### GUI-013 — P3 — Current corpus displays an unexplained blank branch
- Location: “Current Corpus” card.
- Evidence: [008](screenshots/008-dashboard-system-accepted.png).
- Observed: the card displays “Branch: —” with no indication whether branch is optional, still loading, unsupported, or missing.
- User impact: the placeholder reads like incomplete data and weakens confidence in the selected corpus context.
- Desired correction: replace the em dash with a meaningful state such as “not applicable” or an actionable missing-data explanation.

### GUI-014 — P2 — A recent index error is disconnected from the healthy summary
- Location: “Recent Index Runs,” NASA Apollo row, versus the page health summary.
- Evidence: [008](screenshots/008-dashboard-system-accepted.png).
- Observed: a recent run is marked “error,” but the page-wide state remains healthy and the visible row provides no plain-language cause or direct recovery action.
- User impact: a user can either overlook a failed workflow or distrust the overall health indicator.
- Desired correction: distinguish runtime health from workflow success and make each failed row lead to its cause, logs, and safe retry path.

### GUI-015 — P3 — Mixed emoji icons make action meaning and rendering inconsistent
- Location: Quick Actions and shared navigation.
- Evidence: [008](screenshots/008-dashboard-system-accepted.png).
- Observed: stars, folders, sync arrows, a gear, a test tube, and a pin are rendered as platform emoji alongside product icons, producing inconsistent color, weight, and baseline.
- User impact: controls are harder to scan and can change appearance across operating systems.
- Desired correction: use one accessible icon set with text labels and consistent sizing.

### GUI-016 — P2 — The active route and docked route compete for page context
- Location: Dashboard breadcrumb/title and “Dock: Admin — Dependencies.”
- Evidence: [008](screenshots/008-dashboard-system-accepted.png).
- Observed: two different product locations are presented side by side, but the interface does not explain which one owns global actions, keyboard focus, or subsequent navigation.
- User impact: a user can act in the wrong context or believe Admin / Dependencies is part of Dashboard.
- Desired correction: visually separate the dock as a secondary context, expose focus, and name how navigation affects each pane.

### GUI-017 — P3 — The pin/dock relationship is unexplained
- Location: left navigation “Admin 📌” and dock header controls.
- Evidence: [008](screenshots/008-dashboard-system-accepted.png).
- Observed: Admin includes an unexplained pin emoji while the open pane is described with “Dock”; no visible legend connects these concepts.
- User impact: a first-time user cannot infer whether Admin is pinned, pinnable, or merely decorated.
- Desired correction: use a consistent pin/dock vocabulary and expose the current state as a labeled control.

## Corpus registry

### GUI-018 — P2 — Corpus creation fields lose their labels after typing
- Location: corpus picker → Create corpus.
- Evidence: [011](screenshots/011-corpus-registry-bottom.png) and [013](screenshots/013-corpus-create-relative-path.png).
- Observed: Corpus name, root path, and description are represented only by placeholders inside the fields; the first two labels disappear once values are entered.
- User impact: users reviewing a completed form, and users of some assistive technologies, must remember which value belongs to which field.
- Desired correction: add persistent visible labels and programmatic associations above every field.

### GUI-019 — P2 — The create action enables for a path the UI says is invalid
- Location: corpus picker → Create corpus → root path.
- Evidence: [013](screenshots/013-corpus-create-relative-path.png) and live accessibility state.
- Observed: the empty-state placeholder requires “/absolute/path/to/corpus,” but entering `relative/path` enables “Create and select” with no warning.
- User impact: a user can submit a value that contradicts the only format guidance and discover the problem only after an operational request.
- Desired correction: validate the path before enabling submission and explain the accepted filesystem scope inline.

### GUI-020 — P2 — Creating a corpus requires unexplained server-filesystem knowledge
- Location: corpus picker → Create corpus.
- Evidence: [011](screenshots/011-corpus-registry-bottom.png).
- Observed: the form asks for an absolute path but does not say which host/container the path belongs to, whether it must already exist, or how a user is expected to place files there.
- User impact: a product user cannot complete the task without out-of-band infrastructure knowledge.
- Desired correction: name the execution host and path requirements, or replace raw path entry with a governed source/folder selection flow.

### GUI-021 — P3 — Corpus selection and destructive deletion are repeated side by side
- Location: corpus picker corpus rows.
- Evidence: [010](screenshots/010-corpus-registry.png).
- Observed: each corpus row is a large selection target with a separate red Delete button immediately beside it, including the active corpus.
- User impact: repetitive adjacent targets increase selection errors during fast scanning, although the observed second-step confirmation is detailed and clear.
- Desired correction: move deletion into a row menu or detail view while retaining the strong confirmation shown in [012](screenshots/012-delete-corpus-confirmation.png).

## Global settings search

### GUI-022 — P2 — “Global” search cannot find visible product destinations
- Location: shared header settings search.
- Evidence: [014](screenshots/014-global-search-empty.png) and [015](screenshots/015-global-search-health-no-results.png).
- Observed: the overlay is announced as Global search but searches only settings; querying “health” returns no result even while Health and Dashboard / Monitoring are visible product destinations.
- User impact: a user invoking Ctrl+K to find a task can reasonably conclude that health controls do not exist.
- Desired correction: search routes, actions, help, and settings together, or rename the control unambiguously to “Search configuration settings.”

### GUI-023 — P2 — A search result replaces the current page without an in-product return path
- Location: global settings search → “Benchmark · Max Concurrent Models.”
- Evidence: [016](screenshots/016-global-search-model-results.png) and [017](screenshots/017-global-search-destination.png).
- Observed: selecting the result navigates from Dashboard to Admin / Advanced and leaves the prior task context behind; the destination provides no “Back to Dashboard” or search-results return control.
- User impact: users who were only inspecting a setting must rely on browser history and can lose their place.
- Desired correction: preserve a return affordance and communicate before selection that the result navigates to Admin.

## Parameter glossary

### GUI-024 — P2 — Glossary search has no persistent or programmatic label
- Location: Dashboard / Glossary search field.
- Evidence: [019](screenshots/019-dashboard-glossary-top.png) and the live accessibility tree, where the search field has no accessible description.
- Observed: “Search parameters…” appears only as placeholder text and disappears while typing.
- User impact: users cannot verify the field’s purpose after entering a query, and screen-reader navigation encounters an unnamed search field.
- Desired correction: add a visible “Search glossary” label and an accessible name.

### GUI-025 — P2 — All 456 glossary entries flood one accessibility tree
- Location: Dashboard / Glossary, unfiltered All state.
- Evidence: [019](screenshots/019-dashboard-glossary-top.png) and current-run accessibility snapshot reporting 3,740 descendant items.
- Observed: hundreds of full descriptions and documentation links are exposed at once without pagination, progressive disclosure, or virtualized accessibility boundaries.
- User impact: keyboard and screen-reader users must traverse thousands of nodes before reaching later page content; the page is also difficult to orient within.
- Desired correction: provide results pagination or list virtualization with truthful position/count semantics and expandable entry details.

### GUI-026 — P2 — Glossary cards force long technical essays into dense scan surfaces
- Location: Dashboard / Glossary parameter cards.
- Evidence: [019](screenshots/019-dashboard-glossary-top.png) and [020](screenshots/020-dashboard-glossary-filtered.png).
- Observed: each result shows identifier badges, a multi-sentence technical essay, and several external sources in the card itself; there is no summary/detail toggle.
- User impact: users searching for a definition must read a dense document wall rather than compare concise answers.
- Desired correction: lead with a one-sentence definition and move rationale, tradeoffs, and references into expandable details.

## Dock and side rail

### GUI-027 — P2 — Clearing dock contents does not close or reclaim the dock
- Location: side rail → Dock → Clear.
- Evidence: [021](screenshots/021-empty-dock-still-open.png).
- Observed: after Clear, the right third becomes a blank “Nothing docked yet” canvas; no close/collapse action appears and main content does not expand.
- User impact: the action fails the common expectation that clearing a side pane restores workspace.
- Desired correction: add Close/Collapse, and either make Clear close the rail or clearly distinguish “clear content” from “hide rail.”

### GUI-028 — P2 — Dock chooser duplicates parent routes and default subtabs
- Location: side rail → Choose… → filtered “dashboard.”
- Evidence: [024](screenshots/024-dock-chooser.png) and [025](screenshots/025-dock-chooser-dashboard-results.png).
- Observed: “Dashboard /dashboard” and “Dashboard — System Status” appear as different choices even though the parent route opens that default state; the same pattern appears for Chat and Chat / Interface.
- User impact: users cannot predict whether duplicated destinations behave differently.
- Desired correction: collapse equivalent targets or explain the difference in persistent secondary text.

### GUI-029 — P2 — Dock chooser exposes unexplained implementation labels
- Location: side rail → Choose… → Everything.
- Evidence: [024](screenshots/024-dock-chooser.png) and live accessibility state.
- Observed: raw route slugs such as `/dashboard` and badges such as “EMBED” are shown without explanation.
- User impact: non-developers must interpret routing and embedding terminology to choose a workspace.
- Desired correction: use task-oriented descriptions and explain any capability/limitation badge.

### GUI-030 — P2 — “Dock Current” unexpectedly navigates the main view to Chat
- Location: Dashboard / Glossary → side rail → Dock Current.
- Evidence: [026](screenshots/026-dock-current-moves-main-to-chat.png) and the observed route transition to `/web/chat?subtab=ui`.
- Observed: a control labeled only “Dock Current” moves Glossary into the rail and changes the main page to Chat; a brief toast is the only explanation.
- User impact: the user’s current page changes despite the label describing only docking, and the short-lived Undo can disappear before recovery.
- Desired correction: disclose the destination before acting, preserve the main page when possible, and provide a persistent undo/history affordance.

### GUI-031 — P3 — Empty Settings and Source panels use the full rail for one sentence
- Location: side rail → Settings and Source with no source selected.
- Evidence: [022](screenshots/022-sidepanel-settings.png) and [023](screenshots/023-sidepanel-source-empty.png).
- Observed: each mode reserves the full pane at the currently saved allocation for a single explanation/action while still compressing the primary task. The desktop pane can be resized; it does not offer a conventional hide action.
- User impact: switching modes does not reclaim space even when the selected tool has almost no content.
- Desired correction: auto-collapse lightweight empty states or present them as compact overlays until content exists.

## Dashboard / Monitoring

### GUI-032 — P2 — Monitoring says data is read on “every refresh” but offers no refresh control
- Location: Dashboard / Monitoring → Alerts.
- Evidence: [027](screenshots/027-dashboard-monitoring.png).
- Observed: copy says alerts are read live “on every refresh,” but the subtab has no visible Refresh button or last-read timestamp.
- User impact: operators cannot intentionally request fresh data or verify its age.
- Desired correction: add a labeled refresh action, loading/result feedback, and a last-updated timestamp.

### GUI-033 — P2 — Alert severity “NONE” is presented beside a permanently firing alert
- Location: Dashboard / Monitoring → RagweldWatchdog.
- Evidence: [027](screenshots/027-dashboard-monitoring.png).
- Observed: the raw alert name is followed by “NONE,” while the description says it is always firing and its absence means the pipeline is broken.
- User impact: “NONE” reads as no alert/no severity even though the card is deliberately active.
- Desired correction: translate the watchdog into a user-facing status such as “Alert pipeline check — firing as expected,” and hide raw labels in diagnostics.

### GUI-034 — P2 — Six-day-old firing alerts lack ownership or resolution state
- Location: Dashboard / Monitoring → Alerts.
- Evidence: [027](screenshots/027-dashboard-monitoring.png).
- Observed: both alerts show “Firing since 9/5/2026” on a 9/11/2026 audit, but there is no acknowledgement, owner, silence, investigation, or recovery status.
- User impact: an operator cannot distinguish an actively handled condition from an abandoned incident.
- Desired correction: expose acknowledgement/owner/status and link each alert to its runbook or detailed incident.

### GUI-035 — P2 — Duplicate query rows are indistinguishable
- Location: Dashboard / Monitoring → Recent Query Traces.
- Evidence: [027](screenshots/027-dashboard-monitoring.png) and live table state.
- Observed: multiple query/corpus pairs repeat with the same displayed second-level timestamp, and the table omits request ID, source (chat/search), status, and duration.
- User impact: users cannot tell whether duplicates are retries, separate requests, or an ingestion/display error.
- Desired correction: add trace identity, request type, result status, and enough timestamp precision to distinguish rows.

### GUI-036 — P3 — Loki status exposes a loopback endpoint as primary UI content
- Location: Dashboard / Monitoring → Loki Log Aggregation.
- Evidence: current-run accessibility snapshot for the Monitoring state.
- Observed: the status section presents `http://127.0.0.1:53100` without explaining whose loopback interface it is or offering a user task.
- User impact: the value is ambiguous from a remote browser and encourages infrastructure interpretation instead of product-level monitoring.
- Desired correction: lead with log availability and open-log action; move the endpoint to expandable diagnostics with host context.

## Dashboard / Storage

### GUI-037 — P2 — Unit selector labels are visibly clipped in the compressed layout
- Location: Dashboard / Storage → Storage Requirements and Optimization Planner.
- Evidence: [029](screenshots/029-dashboard-storage-calculators.png).
- Observed: selectors that represent KiB and GiB render only “Ki” and “Gi” while the fixed side rail is open.
- User impact: users cannot reliably distinguish byte units, making capacity calculations error-prone.
- Desired correction: prevent unit text clipping, add responsive breakpoints, and test the calculator at the actual split-pane width.

### GUI-038 — P2 — Storage uses repeated unlabeled question-mark help targets
- Location: Dashboard / Storage calculator inputs.
- Evidence: [029](screenshots/029-dashboard-storage-calculators.png) and live accessibility state.
- Observed: many labels are followed by tiny “?” containers that are not exposed as named buttons or links.
- User impact: keyboard and screen-reader users cannot discover the explanatory content, and pointer users face very small targets.
- Desired correction: use focusable help buttons with descriptive names such as “Help for replication factor.”

### GUI-039 — P2 — Storage is a 3,088-pixel mixed-purpose scroll with no internal navigation
- Location: Dashboard / Storage.
- Evidence: [028](screenshots/028-dashboard-storage-top.png), [029](screenshots/029-dashboard-storage-calculators.png), [030](screenshots/030-dashboard-storage-bottom.png), and measured main scroll height of 3,088 CSS px.
- Observed: live measurements, two calculators, results, fit analysis, and optimization tips are stacked into one page without section navigation or sticky context.
- User impact: users lose the distinction between live storage and hypothetical planning while scrolling and must repeatedly traverse duplicated inputs.
- Desired correction: split live usage and capacity planning into clear subtabs or anchored sections with a persistent “hypothetical” state.

### GUI-040 — P2 — Calculator duplicates scenario inputs with ambiguous cross-panel dependency
- Location: Dashboard / Storage → side-by-side Storage Requirements and Optimization Planner.
- Evidence: [029](screenshots/029-dashboard-storage-calculators.png).
- Observed: Corpus Size, Chunk Size, and Embedding Dimension appear independently in both panels, while other values are inherited from the left panel; the explanatory paragraph must be read to know which fields are coupled.
- User impact: two visually similar scenarios can silently diverge and produce comparisons the user did not intend.
- Desired correction: use one shared scenario model or visibly link/synchronize duplicated inputs with an explicit “independent copy” control.

## Dashboard / Help

### GUI-041 — P2 — Switching Dashboard subtabs preserves an unrelated scroll offset
- Location: Dashboard / Storage bottom → Help.
- Evidence: [031](screenshots/031-dashboard-help.png) followed by the manually reset top state in [032](screenshots/032-dashboard-help-top.png).
- Observed: clicking Help while Storage was scrolled to the bottom landed near the bottom of Help at Common Tasks / External Resources instead of at the Help heading.
- User impact: the new page appears to begin mid-document, so users can miss its introduction, quick start, and key concepts.
- Desired correction: reset scroll to the top on subtab navigation, or preserve a separate scroll position per subtab only when returning to that same subtab.

### GUI-042 — P2 — Help describes internal destinations but does not link to them
- Location: Dashboard / Help → Quick Start and Common Tasks.
- Evidence: [032](screenshots/032-dashboard-help-top.png), [031](screenshots/031-dashboard-help.png), and the live accessibility tree.
- Observed: instructions repeatedly say “Go to” Get Started, RAG, Chat, Eval Analysis, Benchmark, and Monitoring, but those destinations are plain text; only external resources are links.
- User impact: users must memorize multi-step paths and manually navigate away from the guide.
- Desired correction: deep-link every named product destination and preserve a return-to-help affordance.

## Chat / Interface (initial observation)

### GUI-043 — P2 — A collapsed model selector exposes hundreds of options to assistive technology
- Location: Chat / Interface model selector after Dock Current moved the main page to Chat.
- Evidence: [026](screenshots/026-dock-current-moves-main-to-chat.png) and the current-run accessibility snapshot, which enumerated provider groups and hundreds of models while the selector was visually collapsed.
- Observed: the native/select-style control is visually one row, but all 395 enabled options across 51 provider groups appear in the page accessibility tree. The selector itself has no accessible name and offers no search or recent/favorite grouping.
- User impact: screen-reader navigation is overwhelmed before reaching chat history or the composer, and the control is impractical without search/filtering.
- Desired correction: use a searchable, virtualized combobox whose accessibility tree contains only the active option and currently rendered results.

## Dashboard / System Status drilldowns

### GUI-044 — P2 — Expanded run accounting breaks the table’s column alignment
- Location: Dashboard / System Status → Recent Index Runs → NASA Apollo 11 → Details.
- Evidence: [034](screenshots/034-system-failed-run-accounting-details.png) and [035](screenshots/035-system-accounting-notes.png).
- Observed: at the live split-pane width, header labels run together (`CHUNKSFIGURESRUN ACCOUNTING`), and the corpus/status/completion cells become vertically centered beside a very tall accounting cell instead of remaining aligned to its top.
- User impact: row identity disappears while reading the expanded material; users can attribute cost or status details to the wrong run.
- Desired correction: switch expanded details to a full-width child row or drawer and preserve fixed, readable header spacing.

### GUI-045 — P2 — Accounting details are an unstructured implementation wall
- Location: the same expanded failed-run Details panel.
- Evidence: [034](screenshots/034-system-failed-run-accounting-details.png) and [035](screenshots/035-system-accounting-notes.png).
- Observed: the panel leads with a long monospaced paragraph containing byte scaling, pypdfium2/Docling factors, CPU/provider values, heuristic multipliers, and formulas before the user-level totals.
- User impact: users must reverse-engineer methodology to find whether accounting is trustworthy and what action is needed.
- Desired correction: lead with recorded/estimated/unknown totals and confidence, then place methodology in a separately expandable diagnostics section.

### GUI-046 — P2 — Error details explain cost but not why the run failed
- Location: NASA Apollo 11 row marked `error` → Details.
- Evidence: [034](screenshots/034-system-failed-run-accounting-details.png) and the live expanded state.
- Observed: Details expands frozen estimates and request accounting; it does not show the indexing error, failed stage, log link, or retry guidance.
- User impact: the most obvious drilldown on a failed row cannot answer the operator’s primary question.
- Desired correction: provide a row-level failure summary and logs/retry route before accounting details.

### GUI-047 — P3 — Run accounting contains raw grammar and policy fragments
- Location: failed-run Details → estimate and Accounting notes.
- Evidence: [035](screenshots/035-system-accounting-notes.png).
- Observed: copy includes “chunking 1 sampled files” and bare fragments such as “missing native requests” and “unverified gateway attempt policy.”
- User impact: terse implementation phrases do not explain severity, effect, or remediation.
- Desired correction: use grammatical sentences that state what is missing, how totals are affected, and how to resolve it.

### GUI-048 — P2 — Visible “Refresh” buttons hide that they refresh cost accounting
- Location: Recent Index Runs → Run Accounting.
- Evidence: [034](screenshots/034-system-failed-run-accounting-details.png) and [035](screenshots/035-system-accounting-notes.png).
- Observed: the visual label is simply “Refresh,” while the accessibility name is “Refresh cost”; no last-updated scope is adjacent to the button until details are opened.
- User impact: the action can be mistaken for rerunning or refreshing the entire index row.
- Desired correction: show the full label “Refresh cost accounting” and its last-checked/result status.

### GUI-049 — P2 — Evaluation presets omit workload and cost before instant execution
- Location: Dashboard Quick Actions → Run Eval.
- Evidence: [036](screenshots/036-dashboard-run-eval-menu.png).
- Observed: the menu explicitly says a preset will “run instantly,” but Baseline and Multi-Query show no dataset, sample count, estimated requests/tokens, expected duration, or cost; choosing a row is the execution action.
- User impact: a rushed user cannot compare operational consequences or review the final scope before starting an evaluation.
- Desired correction: show the complete workload and cost estimate and require a separate confirm/start action.

## Chat / Interface layout

### GUI-050 — P1 — The actual conversation viewport is only 16.6% of screen height
- Location: Chat / Interface, current conversation.
- Evidence: [037](screenshots/037-chat-interface-current.png) and measured rendered geometry: 266px-tall message scroller in a 1,600px-tall viewport.
- Observed: stacked shell chrome, workbench controls, active-corpus notice, sticky composer, retrieval toggles, and a large Routing Trace section leave only 266px for reading the conversation; that scroller contains 654px of message content.
- Dock matrix: with System Prompts retained in the main pane, docked Chat at 348, 544, and 800 CSS px gets message viewports of 248×231, 444×307, and 700×355px respectively ([196](screenshots/196-dock-chat-narrow.png), [197](screenshots/197-dock-chat-medium.png), [198](screenshots/198-dock-chat-wide.png)). The Dock content height is 1,435–1,481px; the populated narrow message scroller contains 21,054px of content. Widening improves line wrapping but never makes the conversation the dominant vertical region. The narrow composer is only 160px wide. This is broader evidence for the same Chat allocation defect, not a new count for each width.
- User impact: Chat—the primary task—feels like a small embedded widget, constantly requiring scrolling while large secondary regions remain empty or show diagnostics.
- Desired correction: make conversation history the dominant flexible region, move diagnostics behind a drawer/tab, compact secondary controls, and enforce a minimum message-area height.

### GUI-051 — P2 — Chat controls wrap into an irregular second row at the live width
- Location: Chat / Interface toolbar.
- Evidence: [037](screenshots/037-chat-interface-current.png).
- Observed: Sources, model, Export, History, and New chat occupy the first row while Delete and Settings wrap alone below, despite the adjacent 628px rail being empty.
- User impact: related conversation actions are visually separated and the destructive Delete action becomes more prominent than intended.
- Desired correction: make the existing split control discoverable and keyboard accessible, define deliberate responsive groups for Chat at every Dock width, and keep destructive actions in an overflow menu or conversation-management area.

### GUI-052 — P1 — Opening History creates three competing scroll regions around a 496px message column
- Location: Chat / Interface → History.
- Evidence: [038](screenshots/038-chat-history.png) and rendered geometry measured in the live state.
- Observed: the fixed 628px side rail remains open while History adds a 258px-wide, 310px-tall list scroller and reduces the message scroller to 496×239px with 739px of content. The page itself still scrolls independently.
- User impact: a user trying to find a conversation must manage page, history, and message scrollbars while the empty rail remains the largest single content region.
- Desired correction: preserve the Dock as a parallel workspace but negotiate a user-controlled split, use compact dock-aware layouts, keep one primary vertical scroll owner per pane, and guarantee a readable minimum width and height for the conversation.

### GUI-053 — P2 — History controls obscure the bottom of the conversation list
- Location: Chat / Interface → History panel.
- Evidence: [038](screenshots/038-chat-history.png) and live element geometry.
- Observed: four conversation cards occupy a 310px internal scroller, while full-width “New chat” and destructive “Delete chat” controls are pinned over its lower edge; the fourth card continues behind the control area.
- User impact: the last conversation looks partially hidden, and a user scrolling toward it can land on a destructive control instead.
- Desired correction: reserve non-overlapping space for list actions, move destructive management into a selected-conversation menu, and keep the entire focused card visible.

### GUI-054 — P1 — Expanding Sources breaks the Chat toolbar into unrelated columns and rows
- Location: Chat / Interface → Sources disclosure.
- Evidence: [039](screenshots/039-chat-sources-panel.png).
- Observed: the disclosure expands into a tall configuration panel inside the first toolbar cell; the model selector is stranded to its right, while Export, History, New chat, Delete, and Settings fall into a separate row below.
- User impact: opening a basic context summary visually restructures the whole workbench and makes the relationship between source selection, model choice, and conversation actions unclear.
- Desired correction: open source configuration in a dedicated drawer/popover with stable dimensions and keep the conversation toolbar in a fixed, deliberate layout.

### GUI-055 — P1 — The active corpus conflicts with the conversation’s Sources and offers two ambiguous recovery actions
- Location: Chat / Interface, active-corpus notice and Sources disclosure.
- Evidence: [037](screenshots/037-chat-interface-current.png) and [039](screenshots/039-chat-sources-panel.png).
- Observed: the shell says NASA Apollo 11 Mission Report is active, the conversation’s Sources count is one, and the expanded source list shows Native Embedding Acceptance selected instead. The notice offers both “Add NASA Apollo 11 Mission Report” and “New chat about NASA Apollo 11 Mission Report” without explaining how retrieval scope, history, or current answers will differ.
- User impact: a user can easily ask a question believing it targets the active corpus while the current conversation remains grounded in another corpus.
- Desired correction: make the effective retrieval scope the dominant label, explain the mismatch in plain language, and present one recommended action with a clear description of whether it changes this conversation or starts a new one.

### GUI-056 — P1 — Routing diagnostics unrelated to the conversation are expanded beneath Chat by default
- Location: Chat / Interface → Routing Trace.
- Evidence: [037](screenshots/037-chat-interface-current.png), [041](screenshots/041-chat-routing-trace-collapsed.png), [042](screenshots/042-chat-routing-trace-fully-collapsed.png), and measured DOM geometry.
- Observed: the expanded section initially states that it is the most recent run on another corpus and “not an answer from this conversation,” yet displays raw hashes, IDs, routes, cost, JSON events, and a 350px terminal whose internal log content is 10,440px tall. Collapsing only the terminal reduces the Chat page from 2,008px to 1,846px; collapsing the entire trace reduces it to 1,335px.
- User impact: unrelated operator diagnostics dominate the primary conversation, create another nested scrollbar, and can be mistaken for evidence about the visible answer.
- Desired correction: keep routing diagnostics collapsed by default in a separate inspector, scope them explicitly to the selected message/run, and never surface a different tab’s latest run as part of the conversation body.

### GUI-057 — P2 — Citation navigation consumes the fixed rail for a two-line source with no close action
- Location: Chat answer → citation 1 → Source rail.
- Evidence: [040](screenshots/040-chat-citation-source-rail.png) and [042](screenshots/042-chat-routing-trace-fully-collapsed.png).
- Observed: opening `calibration.txt:1-2` replaces the empty rail with two lines of source text but preserves the full 628px width and leaves most of the panel blank. The rail provides mode switches and “Open original,” but no visible close/collapse control.
- User impact: citation verification materially shrinks Chat and the user cannot dismiss the source without understanding the Dock mode controls.
- Desired correction: use a closable, resizable citation inspector sized to its content, preserve the originating citation focus, and provide an explicit return-to-answer action.

### GUI-058 — P2 — Per-message Trace exposes raw IDs without communicating its toggle state
- Location: Chat answer → Trace.
- Evidence: [043](screenshots/043-chat-message-trace-toggle.png) and live accessibility attributes.
- Observed: the tiny text action expands run ID, provider response ID, trace ID, correlation ID, model-use, and graph fields; it exposes neither `aria-expanded` nor `aria-pressed`. Activating it also changes the separate Routing Trace from the unrelated two-event search run to a three-event chat run and reopens the global diagnostics section.
- User impact: users cannot tell whether Trace is open, what region it controls, or why a message-level action replaces and expands a second diagnostic region elsewhere on the page.
- Desired correction: give the control an explicit expanded state and target relationship, keep message metadata local to the message, and require a deliberate action to open the full run inspector.

### GUI-059 — P1 — Quick Settings compresses the already-small conversation into a narrow side-by-side editor
- Location: Chat / Interface → toolbar Settings.
- Evidence: [045](screenshots/045-chat-toolbar-settings.png).
- Observed: Quick Settings opens as another fixed column inside Chat while the external Source rail remains open. The message card and composer become visibly narrower, even though the settings contain only Temperature, Max Tokens, and Top-K.
- User impact: the user must edit generation controls while losing the readable conversation context needed to judge them.
- Desired correction: use a temporary closable popover/drawer, preserve minimum widths for both main and Dock workspaces, and let the splitter—not automatic removal of the Dock—resolve competing space.

### GUI-060 — P2 — Quick Settings Temperature and Max Tokens inputs are not programmatically labeled
- Location: Chat / Interface → Quick Settings.
- Evidence: [045](screenshots/045-chat-toolbar-settings.png) and live control inspection.
- Observed: the temperature range and Max Tokens number input have no associated label, ID, name, or ARIA label; only the Top-K field is associated with its visible label. The panel presents no explicit Apply/Cancel boundary.
- User impact: assistive technology cannot identify two of the three controls, and all users cannot tell whether edits are immediate, conversation-local, or awaiting the page-level save bar.
- Desired correction: associate every control with its label and help text, state the scope of each override, and provide explicit apply/reset behavior.

## Chat / Settings

### GUI-061 — Withdrawn — Source persistence across navigation is not itself a defect
- Location: Chat / Settings after opening a citation in Chat / Interface.
- Evidence: [046](screenshots/046-chat-settings-subtab-top.png) through [052](screenshots/052-chat-settings-ui.png).
- Observed: the citation Source rail remains open and continues consuming the fixed side area while the user edits unrelated model, Recall, Multimodal, Provider, and UI settings. There is still no close control.
- Correction: retaining source material while navigating the main pane is a legitimate parallel-workspace use case. The original recommendation to auto-dismiss Source on unrelated navigation would remove useful context and is withdrawn. No automatic dismissal or removal of the Dock is recommended.
- Remaining distinct problems: missing explicit close/return control is covered by GUI-057; source readability and header clipping by GUI-172–174; pane allocation and compact reflow by GUI-154/159/163. Persistence itself is not counted as an open defect.

### GUI-062 — P2 — Model settings are a 2,304px page containing four independently scrolling prompt editors
- Location: Chat / Settings → Model.
- Evidence: [046](screenshots/046-chat-settings-subtab-top.png) and [047](screenshots/047-chat-settings-model-bottom.png), plus rendered measurements.
- Observed: four system-prompt textareas contain 441–1,001 characters and each has its own internal scroll area (252–486px of content), inside a 2,304px settings page. The same page then continues into temperature, token, gateway, and vLLM infrastructure controls.
- User impact: users face five vertical scroll contexts and can easily edit the wrong prompt state or lose their position before reaching generation settings.
- Desired correction: separate prompt states into named tabs/cards with preview, reset, diff, and validation; move gateway infrastructure to its own administrative surface.

### GUI-063 — P2 — Chat Settings mixes user conversation controls with deployment infrastructure
- Location: Chat / Settings → Model and Providers.
- Evidence: [047](screenshots/047-chat-settings-model-bottom.png) and [051](screenshots/051-chat-settings-providers-ready.png).
- Observed: the general Chat settings expose LiteLLM/vLLM enable switches, loopback base URLs, default alias, expected served model, backend-secret status, and catalog alias counts beside temperature and system prompts.
- User impact: a user looking for chat behavior can accidentally change generation routing and must interpret host-local infrastructure concepts unrelated to the conversation task.
- Desired correction: separate role-gated provider administration from end-user Chat preferences and show task-level model selection without raw endpoints.

### GUI-064 — P2 — Provider readiness briefly contradicts the page’s global “Ready” and “OK” states
- Location: Chat / Settings → Providers during initial load.
- Evidence: [050](screenshots/050-chat-settings-providers.png), followed by the settled state in [051](screenshots/051-chat-settings-providers-ready.png).
- Observed: the first rendered state says “No gateway route is ready” and “Unavailable” while the same page says “Ready” and the shell says “HEALTH OK.” About 1.5 seconds later it changes to an active LiteLLM route and “Authenticated and reachable,” without a loading indicator.
- User impact: a user can treat a normal asynchronous load as an outage or trust the global OK status while the detailed panel appears unavailable.
- Desired correction: show an explicit checking/loading state, delay readiness claims until provider checks settle, and timestamp the final result.

### GUI-065 — P2 — Recall settings present an unlabeled expert-tuning matrix as ordinary Chat preferences
- Location: Chat / Settings → Recall.
- Evidence: [048](screenshots/048-chat-settings-recall-top.png) and live form inspection.
- Observed: the page exposes smart gating, raw signals, skip heuristics, Top-K values, and recency weights in a dense matrix. Numeric fields and the Default Intensity select have no associated programmatic labels; repeated question marks are label text rather than focusable help controls.
- User impact: non-experts cannot predict the effect of changes, and keyboard/screen-reader users cannot reliably identify or open the explanations.
- Desired correction: group controls by user outcome, provide presets and plain-language consequences, and implement named focusable help buttons with properly associated labels.

### GUI-066 — P3 — Multimodal and UI settings each waste an entire panel on one toggle
- Location: Chat / Settings → Multimodal and UI.
- Evidence: [049](screenshots/049-chat-settings-multimodal.png) and [052](screenshots/052-chat-settings-ui.png).
- Observed: Multimodal contains only “Vision enabled,” and UI contains only “Streaming responses”; each is placed at the top of a large bordered panel with most of the screen blank.
- User impact: navigation and panel chrome outweigh the available choices, making the settings architecture feel unfinished and forcing needless tab switching.
- Desired correction: consolidate small preference groups into one compact General tab and reserve dedicated tabs for settings sets with meaningful depth.

## Chat / Interface conversation switching and composer

### GUI-067 — P1 — An unsent draft leaks unchanged across different conversations
- Location: Chat / Interface → composer → History → select another conversation.
- Evidence: [053](screenshots/053-chat-composer-typed.png), [054](screenshots/054-chat-existing-empty-conversation.png), and [055](screenshots/055-chat-draft-cross-conversation.png).
- Observed: text entered in one conversation remained in the composer after selecting a different existing conversation. A second audit marker was then entered in the empty NASA conversation, and the exact marker appeared after switching to the separate PDF conversation and again after returning to the empty conversation. Nothing was sent; the marker was cleared through the current input state after verification.
- User impact: a user can unknowingly send a draft under the wrong conversation history, corpus, model, and retrieval configuration.
- Desired correction: scope drafts by conversation ID, visibly restore the correct draft on selection, warn before carrying text into a different scope, and add a regression matrix across conversation/corpus switches.

### GUI-068 — P2 — History silently changes its result count and omits the previously active conversation
- Location: Chat / Interface → History before and after selecting the existing empty NASA conversation.
- Evidence: [038](screenshots/038-chat-history.png) and [054](screenshots/054-chat-existing-empty-conversation.png).
- Observed: History initially reports `Chats (4)` and includes the active Aurora conversation. After selecting the empty NASA conversation it reports `Chats (3)` and the Aurora conversation is absent, but no corpus filter, hidden-results count, or explanation appears.
- User impact: users can believe a conversation was deleted or lost when the visible history set changes with context.
- Desired correction: show the active history filter and total result count, provide an All conversations view, and never silently remove the conversation the user just left.

### GUI-069 — P1 — The empty-conversation state exposes internal migration notes as product copy
- Location: Chat / Interface → existing conversation with zero messages.
- Evidence: [054](screenshots/054-chat-existing-empty-conversation.png), [150](screenshots/150-chat-layout-recheck.png), [151](screenshots/151-chat-layout-emulation-cleared.png), `web/src/components/Chat/ChatInterface.tsx:912-925`, and `web/tests/e2e/exhaustive/chat_reliability.spec.ts:273-282`.
- Observed: the hero literally hard-codes the eyebrow `assistant-ui rebuild`, then tells end users that the surface “now runs on assistant-ui” while preserving corpus controls, recall gate, citations, and trace-linked metadata. This is an implementation migration note and developer acceptance rationale, not product help. The E2E suite also asserts that this exact internal copy is visible, so the leakage is deliberately locked in rather than accidental fallback text. Git blame attributes both the copy and assertion to backup snapshot commit `68bf5611` under the `DMontgomery40` repository identity; the snapshot does not establish whether a person or an agent authored it before capture.
- User impact: the first empty-chat screen reads like a changelog/code review, exposes implementation terminology, wastes the most valuable onboarding space, and still does not answer the user’s immediate questions: what can I ask, what will be searched, and what will be retained?
- Desired correction: remove the migration/framework commentary and the test assertion requiring it. Keep useful source controls, starter prompts, and the send shortcut without adding replacement explanatory prose.
- Resolution update, 2026-09-12: the user explicitly authorized this removal during the audit. Removed the welcome banner, framework subtitle, and metadata commentary beneath the composer; changed the existing reset test to assert the first starter prompt. Applied the exact two-file patch to LXC100's deployed source and published the rebuilt frontend. Live populated and empty conversations verified in [159](screenshots/159-chat-copy-removed-live.png) and [160](screenshots/160-chat-empty-dev-copy-removed.png): no migration/framework copy, all three starter prompts and enabled composer remain. This resolves this copy finding only; Chat sizing, Dock clipping, and Jump to latest remain open.

### GUI-070 — P2 — The composer provides no visible attachment constraints before opening the picker
- Location: Chat / Interface composer → Attach.
- Evidence: [053](screenshots/053-chat-composer-typed.png) and current DOM inspection.
- Observed: the only visible label is “Attach.” The hidden file input accepts multiple `image/*` files, but the UI provides no supported type, file-size, count, preview, privacy, or processing guidance before selection.
- User impact: users must experiment with a system file picker and may choose unsupported or sensitive images without knowing what will happen.
- Desired correction: label the action “Attach images,” disclose accepted limits and handling, and show an explicit preview/removal state before upload.

### GUI-071 — P3 — Composer send guidance is visually detached from the enabled Send action
- Location: Chat / Interface typed composer state.
- Evidence: [053](screenshots/053-chat-composer-typed.png).
- Observed: after text is entered, Send enables, but the only keyboard instruction—“Press Ctrl+Enter to send”—sits in tiny low-contrast text below the retrieval-leg controls. There is no visible draft scope, character/attachment status, or current source summary adjacent to Send.
- User impact: a hurried user can send under the wrong scope without seeing the active conversation/corpus context at the decision point.
- Desired correction: place concise scope and shortcut feedback next to the composer actions and announce state changes accessibly.

## Get Started

### GUI-072 — P1 — A stale Chat citation rail remains open throughout the onboarding wizard
- Location: navigate from Chat citation detail to Get Started, steps 1–4.
- Evidence: [056](screenshots/056-get-started-top.png) through [060](screenshots/060-get-started-ask-question.png).
- Observed: `calibration.txt:1-2` from the prior Chat remains in the fixed Source rail on every onboarding step, consumes the entire side region, and has no relationship to the corpus-registration/indexing workflow.
- User impact: onboarding is compressed by stale content and the source can be mistaken for evidence or instructions for the selected NASA corpus.
- Desired correction: close task-specific inspectors on route changes, preserve them only when returning to the originating task, and provide a deliberate pin option for the exceptional case.

### GUI-073 — P2 — Entering Get Started resumes at step 2 without explaining saved progress
- Location: first navigation to Get Started during this audit.
- Evidence: [056](screenshots/056-get-started-top.png), followed by step 1 after Back in [057](screenshots/057-get-started-step-1.png).
- Observed: the route initially opens “Your corpus” with step 2 highlighted. There is no “resuming,” completion state, last-used corpus, or explanation of why step 1 was skipped.
- User impact: users can think the first step is missing or that the wizard is malfunctioning.
- Desired correction: show a resumable-progress banner with the saved step/corpus and explicit Restart or Continue actions.

### GUI-074 — P1 — Consecutive onboarding steps contradict each other about index status
- Location: Get Started → step 2 existing corpus → step 3 Build indexes.
- Evidence: [058](screenshots/058-get-started-existing-corpus-selected.png) and [059](screenshots/059-get-started-build-index.png).
- Observed: after selecting NASA Apollo 11 Mission Report, step 2 says `not indexed yet`. The very next step says the corpus already has 1,002 chunks from one file and was last indexed on 9/1/2026 at 7:02:16 PM.
- User impact: users cannot know whether it is safe to continue, whether search is usable, or whether a rebuild is necessary.
- Desired correction: derive both steps from one authoritative readiness object and distinguish “indexed,” “stale,” “partial,” and “never indexed” with the same timestamp and counts.

### GUI-075 — P1 — “Rebuild indexes” is an immediate operational action with no confirmation or consequence summary
- Location: Get Started → step 3 Build indexes.
- Evidence: [059](screenshots/059-get-started-build-index.png).
- Observed: the dominant action is “Rebuild indexes.” The page says a fresh generation will be staged and promoted automatically but provides no file/chunk scope, estimated embeddings, duration, compute/cost, replacement behavior, or confirmation step. The neutral progress state below says only “Ready to index.”
- User impact: an impatient user can start a potentially long and expensive rebuild without understanding what will change.
- Desired correction: show a dry-run scope and estimate, explain promotion/rollback, and require a separate confirmation before execution.

### GUI-076 — P2 — Onboarding teaches infrastructure vocabulary before user outcomes
- Location: Get Started → step 1 Welcome and step 3 Build indexes.
- Evidence: [057](screenshots/057-get-started-step-1.png) and [059](screenshots/059-get-started-build-index.png).
- Observed: the first explanation leads with API-first workflows, Postgres chunk rows, Qdrant dense/sparse vectors, Neo4j graph, configured LiteLLM aliases, fresh generations, and automatic promotion.
- User impact: a first-time user must understand the architecture before learning the simple workflow of adding documents and asking grounded questions.
- Desired correction: lead with the user task and expected result; move storage engines, aliases, and generation mechanics into optional technical details.

### GUI-077 — P2 — The first-question step discloses training use without consent or retention controls
- Location: Get Started → step 4 Ask your first question.
- Evidence: [060](screenshots/060-get-started-ask-question.png).
- Observed: the page states that “every real question also feeds the reranker training signal,” but provides no opt-out, definition of what is retained, retention period, visibility, deletion path, or link to a privacy explanation.
- User impact: users must either abandon the primary onboarding task or submit text to an unexplained training pipeline.
- Desired correction: explain the exact data use and retention before input, provide a clear consent/opt-out control, and separate product-improvement telemetry from the required question flow.

### GUI-078 — P2 — Wizard progress controls are numbered but have no accessible step names
- Location: Get Started progress row, steps 1–4.
- Evidence: [057](screenshots/057-get-started-step-1.png) through [060](screenshots/060-get-started-ask-question.png), plus live DOM inspection.
- Observed: each circle is a focusable `span` with `role="button"` and only the text `1`, `2`, `3`, or `4`. The active step correctly uses `aria-current="step"`, but none has an accessible name such as “Step 3, Build indexes.”
- User impact: screen-reader and voice-control users cannot identify the destination before activating it.
- Desired correction: use real buttons or links with full step names, current/completed state, and disabled-state semantics where direct navigation is unavailable.

## Grafana

### GUI-079 — P1 — Grafana Overview is a 4,528px command-center dump with no navigation hierarchy
- Location: Grafana / Overview.
- Evidence: [061](screenshots/061-grafana-entry.png), [062](screenshots/062-grafana-overview-middle.png), [063](screenshots/063-grafana-overview-bottom.png), and measured rendered scroll height.
- Observed: incident banners, external-surface launchers, in-app links, eight status cards, a large integration matrix, latest request/workflow/retrieval evidence, ML-quality summaries, and incident deep links are stacked into one 4,528px page. There is no table of contents, sticky section navigation, filtering, or collapse-all control.
- User impact: operators must scan and scroll through several different jobs before finding the relevant evidence, while the stale Source rail continues shrinking the workspace.
- Desired correction: lead with a compact health/incident summary, group evidence by task, add section navigation and filters, and move raw cross-stack details into drilldowns.

### GUI-080 — P1 — Choosing a dashboard stages two unrelated global configuration changes
- Location: Grafana / Dashboards → Dashboard selector or family card.
- Evidence: [065](screenshots/065-grafana-dashboard-oncall.png) through [070](screenshots/070-grafana-dashboard-cost.png).
- Observed: merely selecting another dashboard changes the global sticky bar from disabled “No changes to apply” to “Apply 2 changes,” even though the control is presented as navigation. Restoring Frontend/RUM returns the bar to no changes; no changes were applied during the audit.
- User impact: a user exploring dashboards can accidentally save view navigation as application configuration, or avoid the save bar because its scope is incomprehensible.
- Desired correction: keep view state out of the configuration dirty store, persist dashboard preference separately if desired, and identify every staged key before enabling Apply.

### GUI-081 — P1 — Embedded dashboard metrics are visibly clipped at the live split-pane width
- Location: Grafana / Dashboards → Retrieval/Indexing/Graph.
- Evidence: [067](screenshots/067-grafana-dashboard-retrieval.png) and the same corpus’s 1,002-chunk count in [059](screenshots/059-get-started-build-index.png).
- Observed: oversized Grafana stat text is cropped inside the compressed cards: “Indexed Chunks” shows only `2` where the onboarding flow reports 1,002 chunks, and “Graph Relationships” shows a clipped `00`. The fixed Source rail remains open beside the iframe.
- User impact: core operational counts are read as entirely different values.
- Desired correction: make dashboards explicitly Dock-aware, improve access to the existing draggable split, provide compact dashboard composition, use responsive stat typography, and add screenshot regression tests for four-digit and larger values at supported Dock widths.

### GUI-082 — P1 — Blank panels, zeroes, and NaN are not distinguished across dashboards
- Location: Grafana / Dashboards across On-call, Gateway, Training, Eval, Cost, and Frontend/RUM.
- Evidence: [064](screenshots/064-grafana-dashboards.png) through [070](screenshots/070-grafana-dashboard-cost.png).
- Observed: multiple dashboards render completely blank panels without “No data,” loading, error, or time-range explanations. Other cards show green `NaN`, `0`, `00`, or `$0.000000` values, making missing telemetry visually indistinguishable from healthy zero activity.
- User impact: operators can interpret telemetry failure as a healthy system and miss incidents or cost exposure.
- Desired correction: enforce explicit Loading, No data, Error, and Zero states with neutral/error colors, data-source status, and last-successful sample time.

### GUI-083 — P2 — On-call Overview presents green NaN as a primary health metric
- Location: Grafana / Dashboards → On-call Overview.
- Evidence: [065](screenshots/065-grafana-dashboard-oncall.png).
- Observed: “Search Latency (p95)” renders a huge green `NaN` beside a green 0% error rate, while “Training Failures (24h)” is blank and the traffic chart has no visible series.
- User impact: the landing dashboard suggests health precisely when its latency and training evidence are absent.
- Desired correction: treat NaN as unavailable/error, suppress success coloring until a valid sample exists, and make the dashboard summary fail closed.

### GUI-084 — P2 — Dashboard navigation is duplicated and consumes most of the page header
- Location: Grafana / Dashboards.
- Evidence: [064](screenshots/064-grafana-dashboards.png) through [070](screenshots/070-grafana-dashboard-cost.png).
- Observed: seven large dashboard-family cards occupy two rows, while the same choices appear again in the Dashboard select immediately below. Additional context-link pills change per family.
- User impact: repeated navigation pushes the actual monitoring surface down and makes it unclear which control is canonical.
- Desired correction: use one compact, searchable dashboard switcher with recent/favorite views and keep contextual links inside the selected dashboard header.

### GUI-085 — P2 — Grafana Overview exposes raw infrastructure state as the primary operator summary
- Location: Grafana / Overview integration matrix and Live Evidence.
- Evidence: [062](screenshots/062-grafana-overview-middle.png) and [063](screenshots/063-grafana-overview-bottom.png).
- Observed: the page foregrounds loopback URLs, raw request/trace hashes, workflow identifiers, generation IDs, HTTP 405 probe details, “not probeable,” `mlx_qwen3`, and other implementation labels inside dozens of cards.
- User impact: the operator must translate transport-level data into user impact and cannot quickly tell which items require action.
- Desired correction: summarize task impact and required action first, then place endpoints, probes, and IDs in copyable diagnostics.

### GUI-086 — P2 — The incident feed has no owner, start time, acknowledgement, or resolution workflow
- Location: Grafana / Incidents.
- Evidence: [071](screenshots/071-grafana-incidents.png).
- Observed: the single prompt-regression incident is labeled FIRING, warning, and `slot=at_risk`, but shows no first-seen/updated time, assignee, acknowledgement, notes, silence, or resolved state. Three buttons only navigate to other product areas.
- User impact: an operator cannot tell whether the incident is new, already handled, or safe to defer.
- Desired correction: add lifecycle, ownership, timestamps, acknowledgement, and a guided investigation/resolution path.

### GUI-087 — P2 — Grafana Config mixes editable backend endpoints with ordinary viewing controls
- Location: Grafana / Config.
- Evidence: [072](screenshots/072-grafana-config.png).
- Observed: dashboard preset, embedded-frame enablement, Grafana base URL, org ID, dashboard UID/slug, refresh interval, kiosk mode, and Alertmanager/Mimir/Prometheus/Pyroscope/Faro/OpenCost URLs are editable in the same area that launches dashboards. The page says Grafana anonymous access is enabled by default and relies on the global bottom save bar.
- User impact: a user trying to open monitoring can inadvertently stage routing/security changes and has no local preview, validation, or risk summary.
- Desired correction: role-gate and separate configuration from viewing, validate endpoints in place, explain anonymous-access scope, and show an explicit configuration diff before Apply.

## Benchmark

### GUI-088 — P1 — Benchmark renders all 395 model choices inside a 38,520px internal list
- Location: Benchmark → Models.
- Evidence: [073](screenshots/073-benchmark-entry.png), [074](screenshots/074-benchmark-filtered-models.png), and measured DOM geometry.
- Observed: the model pane is 736px tall but contains 38,520px of scroll content and 395 checkboxes. Every model remains present in the DOM/accessibility tree; only a filter makes the catalog tractable.
- User impact: browsing and assistive navigation are extremely slow and users cannot compare distant models without losing context.
- Desired correction: use a searchable virtualized picker with provider/model facets, sort, recent/favorite models, and a persistent selected-model tray.

### GUI-089 — P1 — Filtering hides the selected models while Run still targets them
- Location: Benchmark → selected models → filter `gpt-5.6` → prompt ready state.
- Evidence: [074](screenshots/074-benchmark-filtered-models.png) and [075](screenshots/075-benchmark-prompt-ready.png).
- Observed: the two selected models are AionLabs Aion-2.0 and Z.ai GLM 5.3 Flash, but filtering for `gpt-5.6` hides both and displays only unchecked OpenAI models. The header continues to say `2/4`, and entering a prompt enables Run with an estimate for two models without naming them.
- User impact: a user can run and pay for a benchmark against models that are completely absent from the current view.
- Desired correction: keep selected models visible as named removable chips above filtered results and repeat their names in the final run summary.

### GUI-090 — P2 — Benchmark corpus scope is implied rather than selected in the run form
- Location: Benchmark page and “What a benchmark produces.”
- Evidence: [073](screenshots/073-benchmark-entry.png) and [075](screenshots/075-benchmark-prompt-ready.png).
- Observed: explanatory copy says grounding is included “when a corpus is scoped,” but the run form has no corpus field or explicit “No corpus” state. The only clue is the global active-corpus button in the shell, while a stale citation Source rail from another conversation remains visible.
- User impact: users cannot verify whether model answers will use NASA, another source, or no retrieval before spending requests.
- Desired correction: put corpus/retrieval scope in the run form and final confirmation, independently of stale shell or side-rail state.

### GUI-091 — P2 — The multi-model Run action has no separate confirmation step
- Location: Benchmark → prompt entered with two selected models.
- Evidence: [075](screenshots/075-benchmark-prompt-ready.png).
- Observed: entering text immediately enables the small Run button. A compact estimate appears for two models (about eight prompt tokens and 500 output tokens per model), but there is no final review of model names, corpus scope, retrieval mode, timeout, or maximum cost.
- User impact: an impatient user can start multiple provider requests while only seeing a model count and approximate cost.
- Desired correction: open a run-summary confirmation that names every model and scope, shows worst-case cost/duration, and requires a separate Start action.

### GUI-092 — P3 — Recent runs reserves a large empty region without a useful first-run state
- Location: Benchmark → Recent runs.
- Evidence: [073](screenshots/073-benchmark-entry.png) and [075](screenshots/075-benchmark-prompt-ready.png).
- Observed: most of the lower page is a bordered empty panel containing only “No past runs yet. Your saved runs will appear here.” There is no example, link to documentation, saved-run retention explanation, or connection to the ready prompt above.
- User impact: the page feels incomplete and provides no help interpreting the comparison output before the first paid/operational run.
- Desired correction: show a compact empty state with an annotated sample result and link it to the run form.

### GUI-093 — P2 — Benchmark’s disabled local lane is mixed into the selectable provider catalog
- Location: Benchmark → Models → `ragweld local (self-hosted)`.
- Evidence: [073](screenshots/073-benchmark-entry.png).
- Observed: the local model appears as the first catalog row with a checkbox-style control and alias/pricing metadata, followed by the warning `VLLM LANE DISABLED ON THIS HOST`.
- User impact: users must inspect warning text to understand why the first apparent choice cannot participate, and may interpret the disabled host as a temporary model error.
- Desired correction: separate unavailable lanes into a clearly disabled section with reason, remediation, and host identity; exclude them from ordinary selection order.

## RAG

### GUI-094 — P2 — Synthetic Lab status and launch actions repeat above every RAG task
- Location: RAG / Data Quality, Retrieval, Graph, Reranker, Learning Reranker, Learning Agent Studio, and Indexing.
- Evidence: [076](screenshots/076-rag-entry.png), [078](screenshots/078-rag-retrieval-top.png), [092](screenshots/092-rag-graph-top.png), [096](screenshots/096-rag-reranker-top.png), [097](screenshots/097-rag-learning-reranker-top.png), [098](screenshots/098-rag-learning-agent-studio.png), and [100](screenshots/100-rag-indexing-reloaded.png).
- Observed: each subtab starts with the same raw `status=completed run=nasa-apollo-11__20260829_144625` strip and one or more full-width Synthetic Lab actions, pushing the subtab’s actual controls down.
- User impact: navigation feels repetitive and users cannot tell whether the run is relevant to the current task.
- Desired correction: place one compact, timestamped Synthetic Lab status in shared RAG navigation and show task-specific handoffs only when they are relevant.

### GUI-095 — P2 — Data Quality mixes deterministic local work and gateway generation without a clear execution boundary
- Location: RAG / Data Quality.
- Evidence: [076](screenshots/076-rag-entry.png) and [077](screenshots/077-rag-data-quality-bottom.png).
- Observed: Refresh Chunk Summaries, Generate Keywords, Save Filters, Build Chunk Summaries, Auto-generate, and two separate Synthetic Lab generation actions share the same visual treatment. Only a small note explains that one chunk-summary build is deterministic and incurs no gateway billing.
- User impact: users cannot tell which controls are local/config-only versus billable or long-running generation.
- Desired correction: group actions by execution type, show cost/runtime and current state before starting, and separate configuration saving from jobs.

### GUI-096 — P2 — Indexed-corpus quality outputs have no actionable empty-state reconciliation
- Location: RAG / Data Quality → Chunk summaries and Corpus keywords.
- Evidence: [077](screenshots/077-rag-data-quality-bottom.png) and the same corpus’s indexed state in [059](screenshots/059-get-started-build-index.png).
- Observed: the page says no summary build and no stored keywords exist and instructs the user to index the corpus first, even though the corpus already has 1,002 indexed chunks. It does not identify the actual missing post-index jobs or their last attempts.
- User impact: users can repeatedly re-index instead of running the missing quality steps.
- Desired correction: detect indexed readiness, name the exact missing artifact/job, and offer one guided action with last-run status.

### GUI-097 — P1 — Retrieval is a nested configuration maze up to 2,967px tall
- Location: RAG / Retrieval across Search Paths, Fusion & Scoring, Generation, and Ops & Tracing.
- Evidence: [078](screenshots/078-rag-retrieval-top.png) through [091](screenshots/091-rag-retrieval-integrations-bottom.png).
- Observed: a shared control block sits above four card-style modes; Ops adds a second mode switch. Individual modes contain up to 25 controls and scroll heights from 2,059px to 2,967px, with no sticky mode header, summary of effective behavior, or local change diff.
- User impact: users lose which retrieval layer they are editing and cannot predict the effective pipeline from scattered values.
- Desired correction: provide an effective-pipeline summary, sticky section navigation, task presets, per-section validation, and a consolidated diff before Apply.

### GUI-098 — P2 — Disabled or unused retrieval values remain visually editable
- Location: RAG / Retrieval → Fusion & Scoring and Ops & Tracing → Runtime Compatibility.
- Evidence: [080](screenshots/080-rag-retrieval-fusion.png), [081](screenshots/081-rag-retrieval-fusion-bottom.png), and [087](screenshots/087-rag-retrieval-ops-bottom.png).
- Observed: vector/sparse/graph weights are shown as normal inputs even while RRF ignores them; MMR lambda remains visible while MMR is off; a full Semantic Cache configuration remains active-looking while Cache Enabled is off.
- User impact: users can edit values that have no effect and later believe the system ignored or lost their changes.
- Desired correction: disable and visually subordinate inactive fields, state the activation dependency beside each group, and show the effective values only.

### GUI-099 — P2 — Intent weighting requires editing raw JSON beside destructive reset/apply controls
- Location: RAG / Retrieval → Fusion & Scoring → Intent Overrides.
- Evidence: [081](screenshots/081-rag-retrieval-fusion-bottom.png).
- Observed: the advanced matrix is a raw JSON editor with `Reset to Default` and `Apply Changes` directly above it. It exposes internal layer names and numeric multipliers without structured validation, preview, or a clear relation to the global save bar.
- User impact: a small syntax or value mistake can change retrieval behavior across intents, and users cannot tell whether Apply is immediate or staged.
- Desired correction: use a validated matrix editor with named intents/layers, inline ranges, preview, undo, and one consistent save model.

### GUI-100 — P2 — Retrieval model routing exposes overlapping aliases without an effective-route explanation
- Location: RAG / Retrieval → Generation and Model Assignments Overview.
- Evidence: [082](screenshots/082-rag-retrieval-generation.png) through [085](screenshots/085-rag-model-assignments-table.png).
- Observed: the user sees a non-chat alias, separate HTTP/MCP/CLI overrides, enrichment alias, a note that Chat has its own picker, and a later table assigning Chat Answer, Enrichment, Graph Extraction, Query Expansion, Query Rewrite, Embedding, and Reranker to different providers/models.
- User impact: users cannot answer which model a specific request will use without reconciling multiple controls and a distant table.
- Desired correction: show a request-type-to-effective-model map first, then expose overrides inline with precedence and fallback behavior.

### GUI-101 — P2 — Latest Trace preview is task-ambiguous and omits key context
- Location: RAG / Retrieval → Ops & Tracing → Observability & Integrations.
- Evidence: [088](screenshots/088-rag-retrieval-observability.png) and [089](screenshots/089-rag-retrieval-trace-loaded.png).
- Observed: `Load Latest Trace` loads whichever local run is newest. The preview shows timestamps and event names but displays Policy, Intent, and Final K as dashes and does not identify the conversation, user action, or originating tab.
- User impact: operators can diagnose the wrong request while believing it belongs to the current corpus/task.
- Desired correction: require trace selection by request/message, show origin and correlation context, and avoid a context-free global “latest.”

### GUI-102 — P2 — Retrieval tracing configuration is raw infrastructure administration inside the task editor
- Location: RAG / Retrieval → Ops & Tracing → Observability & Integrations.
- Evidence: [090](screenshots/090-rag-retrieval-observability-bottom.png) and [091](screenshots/091-rag-retrieval-integrations-bottom.png).
- Observed: trace retention/sampling, OTLP export endpoint and headers, log path, service name, alert severities/timeouts, Langfuse/Tempo/Alloy URLs, project, secret-key status, metrics, cost tracking, and log level are editable inside Retrieval.
- User impact: retrieval tuning and observability deployment changes share one save surface, increasing accidental blast radius.
- Desired correction: move role-gated infrastructure settings to Admin and leave only trace-view preferences in Retrieval.

### GUI-103 — P1 — Graph table view collapses into a 285px column while half the workspace is blank
- Location: RAG / Graph → Table.
- Evidence: [094](screenshots/094-rag-graph-table.png) and [095](screenshots/095-rag-graph-table-bottom.png).
- Observed: Entities and Relationships tables render in a narrow left column with horizontal scrollbars and character-by-character wrapping, while a large region to their right is unused and the Dock rail is empty.
- User impact: names, types, relations, and source fields are effectively unreadable.
- Desired correction: use a splitter with documented minimums and provide responsive main/Dock table-card fallbacks without horizontal-plus-vertical nested scrolling.

### GUI-104 — P2 — Graph Explorer contains two enormous nested lists before the graph
- Location: RAG / Graph → Communities and Entities.
- Evidence: [092](screenshots/092-rag-graph-top.png), [093](screenshots/093-rag-graph-visualization.png), and measured geometry.
- Observed: the 420px Communities and Entities panes contain 6,847px and 10,245px of scroll content, respectively, inside a separately scrolling 1,920px page. The actual graph appears below both lists.
- User impact: users juggle three scrollbars and must traverse list-heavy controls before reaching the visualization.
- Desired correction: virtualize lists, keep the graph visible beside a single searchable inspector, and synchronize selection/focus.

### GUI-105 — P2 — Graph visualization is too small and under-labeled to explain 162 entities
- Location: RAG / Graph → Visualization.
- Evidence: [093](screenshots/093-rag-graph-visualization.png).
- Observed: the graph is squeezed into a short panel at 44% zoom; most of 162 nodes are unlabeled colored dots, seven legend categories compete for space, and only a few cluster labels are visible.
- User impact: the visualization communicates neither overall structure nor a clear path to a specific entity.
- Desired correction: make the graph the primary full-height surface, add searchable focus and progressive labels, and move details to a collapsible inspector.

### GUI-106 — P2 — Cloud reranking configuration omits per-query consequence and cost
- Location: RAG / Reranker → Cloud.
- Evidence: [096](screenshots/096-rag-reranker-top.png).
- Observed: Cloud is active with LiteLLM, OpenAI GPT-5.6 Luna, Cloud Top-N 50, and 700-character snippets, but there is no estimated tokens/cost/latency or explanation of when the reranker runs.
- User impact: users can increase retrieval cost or latency without understanding the request multiplier.
- Desired correction: show effective invocation conditions, token estimate, latency/cost range, and a comparison with Disabled/Learning modes.

### GUI-107 — P1 — Learning Reranker Studio exposes 29 controls without a guided run lifecycle
- Location: RAG / Learning Reranker.
- Evidence: [097](screenshots/097-rag-learning-reranker-top.png) and live control inventory.
- Observed: the screen exposes run scope, Start Run, Mine Triplets, Train, Evaluate, Promote, visualization/log layouts, pop-outs, inspector modes, timeline/log/gradient tabs, download, and clear in one dense workbench. Start Run and Mine Triplets are direct actions; training is currently blocked because triplets are zero.
- User impact: users cannot tell the required sequence, which actions create cost/artifacts, or what can safely be undone.
- Desired correction: use a staged Mine → Train → Evaluate → Promote workflow with prerequisites, estimates, state, confirmation, and rollback.

### GUI-108 — P1 — Learning Agent’s Start Run control is rendered outside the visible workspace
- Location: RAG / Learning Agent Studio with the live split-pane width.
- Evidence: [098](screenshots/098-rag-learning-agent-studio.png) and measured button geometry.
- Observed: the main RAG content ends at x=1,283 CSS px, but `All corpora` extends to x=1,309 and `Start Run` is entirely outside it at x=1,315–1,405 under the Dock region. The command row does not wrap or scroll visibly.
- User impact: the primary action is inaccessible even though a large empty Dock consumes the right side.
- Desired correction: improve access to the existing resizable split, give Learning Agent a supported compact layout, wrap controls, and keep the primary action visible at every valid Dock width.

### GUI-109 — P2 — Learning Agent failure prerequisites are a dense warning paragraph above a disabled studio
- Location: RAG / Learning Agent Studio.
- Evidence: [098](screenshots/098-rag-learning-agent-studio.png).
- Observed: a small yellow paragraph combines unavailable backend, fail-closed behavior, configured base model, promotion path, and artifact compatibility. Most run actions are disabled, but no guided remediation or backend-status action is provided.
- User impact: operators must parse deployment policy to understand why no run can start.
- Desired correction: convert prerequisites into a checklist with current/required values and direct remediation links.

### GUI-110 — P1 — Clicking Indexing changes the URL but can leave Learning Agent active until reload
- Location: RAG subtab navigation → Indexing.
- Evidence: [099](screenshots/099-rag-indexing-top.png) and the subsequently reloaded correct state in [100](screenshots/100-rag-indexing-reloaded.png).
- Observed: the click updated the URL to `?subtab=indexing`, but `Learning Agent Studio` and `tab-rag-learning-agent` remained active. A direct reload of the same Indexing URL was required before the Indexing view and breadcrumb appeared.
- User impact: URL, highlighted task, and rendered content can disagree, making navigation and browser history unreliable.
- Desired correction: drive route and content from one state transition, add a navigation regression test across all RAG subtabs, and fail visibly if content loading fails.

### GUI-111 — P1 — Indexing failure states contradict each other across summary, details, and live output
- Location: RAG / Indexing → last run, Graph details, Run details, and Indexing Output.
- Evidence: [100](screenshots/100-rag-indexing-reloaded.png), [101](screenshots/101-rag-indexing-failed-details.png), and [103](screenshots/103-rag-indexing-run-controls.png).
- Observed: the summary says `Failed — Request timed out`; Graph details show 1,002/1,002 extraction failures and `extraction_failure`; the output says the PDF is “still running (960s elapsed)” before reporting the semantic write timeout. No single authoritative terminal state or failed stage is presented.
- User impact: users cannot know whether work is still active, safely retryable, or failed because of extraction versus timeout.
- Desired correction: use one run-state machine with stage status, terminal reason, last event time, and explicit Retry/Resume/Cancel actions.

### GUI-112 — P1 — Destructive index controls sit beside ambiguous recovery actions
- Location: RAG / Indexing run controls.
- Evidence: [103](screenshots/103-rag-indexing-run-controls.png) and [106](screenshots/106-rag-indexing-tokenization-bottom.png).
- Observed: `Force reindex`, disabled `Generate schema first`, `Hide Logs`, and red `Delete index` share one row below collapsed Index Stats. The Force Reindex warning says changed settings can make searches unavailable until rebuild succeeds, but no rollback or recovery snapshot is shown.
- User impact: a user troubleshooting a failed run can delete or invalidate the active index without a clear recovery path.
- Desired correction: isolate destructive actions, require typed confirmation, show the active/staged generation and rollback target, and offer the correct retry path first.

### GUI-113 — P2 — Indexing configuration is spread across pages up to 3,888px with repeated run controls
- Location: RAG / Indexing → Embedding, Chunking, Tokenization, Graph & Enrichment, Figures & Vision.
- Evidence: [102](screenshots/102-rag-indexing-embedding.png) through [109](screenshots/109-rag-indexing-figures-vision.png).
- Observed: every mode repeats the locked-contract banner, corpus/path, mode cards, Index Stats, Force Reindex/Delete row, and output terminal around a different configuration section; Graph & Enrichment reaches 3,888px.
- User impact: users must repeatedly traverse the same operational chrome and lose where configuration ends and execution begins.
- Desired correction: keep corpus/run status in a sticky summary, make configuration modes independent short panels, and put execution in one dedicated review/run step.

### GUI-114 — P2 — Indexing fields expose raw limits and implementation choices without outcome previews
- Location: RAG / Indexing configuration modes.
- Evidence: [102](screenshots/102-rag-indexing-embedding.png), [104](screenshots/104-rag-indexing-chunking.png), [105](screenshots/105-rag-indexing-tokenization.png), [106](screenshots/106-rag-indexing-tokenization-bottom.png), and [108](screenshots/108-rag-indexing-graph-enrichment-bottom.png).
- Observed: users edit provider backends, model IDs, dimensions, truncation, token ceilings, byte limits, stream blocks, BM25 stemming, Parquet row/cell limits, semantic chunk ceilings, timeouts, reasoning effort, and token limits without a projected chunk count, coverage change, cost, or compatibility result.
- User impact: expert-only parameters can silently degrade retrieval or trigger an expensive rebuild.
- Desired correction: provide presets, unit-formatted values, impact estimates, compatibility validation, and an expert-mode boundary.

### GUI-115 — P2 — Figures & Vision receives a full configuration mode for one unexplained checkbox
- Location: RAG / Indexing → Figures & Vision.
- Evidence: [109](screenshots/109-rag-indexing-figures-vision.png).
- Observed: the mode contains one checkbox to describe charts/diagrams/drawings and a sentence saying gateway calls will occur and prices will be shown before the run. No model, supported format, page/image limit, privacy behavior, or estimate is visible in the mode itself.
- User impact: users cannot judge what enabling vision will process or cost.
- Desired correction: show supported inputs, selected vision model, limits, privacy, and a concrete estimate before enabling.

### GUI-116 — P1 — Synthetic Lab horizontally overflows the already compressed workspace
- Location: RAG / Synthetic Lab.
- Evidence: [110](screenshots/110-rag-synthetic-lab-top.png), [111](screenshots/111-rag-synthetic-lab-bottom.png), and measured geometry.
- Observed: the content is 1,185px wide inside a 1,091px viewport, producing a persistent horizontal scrollbar. The recipe builder’s Judge Model field and later artifact content extend beyond the visible area while the empty Dock remains open.
- User impact: users must scroll horizontally to inspect or operate a run and can miss right-side values/actions.
- Desired correction: preserve the Dock while allowing a resizable split, use a responsive one-column fallback in the main pane, and eliminate page-level horizontal overflow at every supported split.

### GUI-117 — P1 — Synthetic Lab run and publication actions lack a final review/confirmation
- Location: RAG / Synthetic Lab → Recipe Builder and Artifacts + Publish.
- Evidence: [110](screenshots/110-rag-synthetic-lab-top.png) and [111](screenshots/111-rag-synthetic-lab-bottom.png).
- Observed: Start Run, Start Full Stack, Set Baseline, Set Canary, Set Current, Set Promoted, and artifact Publish buttons are presented as immediate full-width actions. The generator/judge pair can create up to 150 pairs, but no request/token/cost estimate, promotion diff, rollback target, or confirmation is shown.
- User impact: users can start billable generation or change active corpus artifacts with one click.
- Desired correction: require a run/promotion review that shows scope, models, worst-case cost, gates, target slot, current value, and rollback.

### GUI-118 — P1 — A green perfect Quality Gate is based on only six self-generated questions
- Location: RAG / Synthetic Lab → Quality Gate.
- Evidence: [111](screenshots/111-rag-synthetic-lab-bottom.png).
- Observed: the gate displays top-1=1.00, top-k=1.00, MRR=1.00 and `passed on 6 sample questions` in green. The paragraph below admits this is a self-consistency check on a small self-generated sample and is not evidence of retrieval quality by itself.
- User impact: the dominant success signal contradicts its own caveat and can justify an unsafe promotion.
- Desired correction: label the result “self-consistency only,” use neutral styling, block promotion until independent validation passes, and show sample provenance.

### GUI-119 — P2 — Synthetic artifacts expose absolute server paths and raw JSON as the primary preview
- Location: RAG / Synthetic Lab → Eval Dataset, Run Report, Quality Eval, Preview.
- Evidence: [111](screenshots/111-rag-synthetic-lab-bottom.png) and [112](screenshots/112-rag-synthetic-preview.png).
- Observed: the page foregrounds `/opt/ragweld/data/...` paths, repeated Copy Path/Preview/Publish buttons, and an inline raw JSON preview with its own scrollbar. Run Report uniquely has no Publish action, explained only in small prose.
- User impact: users must interpret host filesystem artifacts and can lose the publication distinction among three nearly identical sections.
- Desired correction: use named artifacts with size/status/provenance, a human-readable preview, one consistent publication workflow, and keep paths in optional diagnostics.

## Eval Analysis

### GUI-120 — P1 — Eval’s perfect headline metrics are based on only six questions
- Location: Eval Analysis / Analysis.
- Evidence: [113](screenshots/113-eval-analysis-entry.png), [115](screenshots/115-eval-analysis-bottom.png), and [116](screenshots/116-eval-question-detail.png).
- Observed: the dashboard leads with Top-1 100%, Top-K 100%, and MRR 1.0000, but the denominator is 6/6 questions. The compared configurations changed three parameters yet show 0.0% performance change, zero regressions, and zero improvements.
- User impact: a perfect score on a tiny set can be mistaken for broad retrieval quality and justify promotion.
- Desired correction: foreground sample size/coverage and confidence, use neutral styling for underpowered results, and require independent/representative gates before promotion.

### GUI-121 — P2 — Eval run selectors use truncated IDs instead of readable run identity
- Location: Eval Analysis / Analysis → Primary Run and Compare With.
- Evidence: [113](screenshots/113-eval-analysis-entry.png) and [114](screenshots/114-eval-run-settings.png).
- Observed: run labels are long `nasa-apollo-11__20260829_...` strings clipped inside selects, followed by a score and partially visible count. No human title, relative date, configuration summary, baseline/current badge, or status appears in the closed control.
- User impact: users can compare the wrong runs and cannot verify chronology at a glance.
- Desired correction: display human-readable timestamp, status, corpus, metric, config-change count, and baseline/current markers.

### GUI-122 — P1 — Run Eval, Promptfoo regression, and AI Analysis start without a final scope/cost review
- Location: Eval Analysis / Analysis.
- Evidence: [113](screenshots/113-eval-analysis-entry.png), [114](screenshots/114-eval-run-settings.png), and [115](screenshots/115-eval-analysis-bottom.png).
- Observed: Run Eval, Run Promptfoo Regression, and Generate AI Analysis are direct buttons. The page provides no request/model/token/cost estimate, timeout, output destination, or separate confirmation immediately before execution.
- User impact: users can start billable or long-running evaluation/generation while believing they are opening a configuration step.
- Desired correction: show a run-summary dialog with exact dataset size, retrieval/model settings, provider requests, maximum cost/duration, and a separate Start action.

### GUI-123 — P2 — Eval Run Settings duplicates Retrieval configuration and preserves inactive-looking values
- Location: Eval Analysis / Analysis → Run Settings.
- Evidence: [114](screenshots/114-eval-run-settings.png).
- Observed: the panel repeats corpus, sample size, Final K, Multi-Q, M, fusion method, RRF K, weights, retrieval legs, and three Top-K values. Multi-Q is disabled while M remains editable-looking; RRF is selected while weights remain editable-looking.
- User impact: users cannot tell whether Eval inherits live Retrieval settings, overrides them, or snapshots a separate configuration.
- Desired correction: show inherited effective values first, require an explicit “Override for this run,” and disable parameters that the current mode ignores.

### GUI-124 — P2 — Promptfoo sample-size control conflicts with the displayed latest result
- Location: Eval Analysis / Analysis → Promptfoo regression.
- Evidence: [114](screenshots/114-eval-run-settings.png).
- Observed: Sample Size is set to `25 entries`, while the latest run directly below reports passed 6/6, failed 0, skipped 0. No explanation says only six eligible entries existed or that the setting is a maximum.
- User impact: users can believe 25 examples were graded when only six appear in the result.
- Desired correction: label the value as requested maximum and show requested, eligible, executed, skipped, and failed counts together.

### GUI-125 — P2 — Question detail creates another nested scroll inside the results table
- Location: Eval Analysis / Analysis → Question Results → first row.
- Evidence: [116](screenshots/116-eval-question-detail.png).
- Observed: clicking a row expands expected/returned paths and six retrieved chunks inside the table’s own vertical scrollbar, while the page remains separately scrollable. The status column still shows `--` despite successful path matches.
- User impact: evidence is hard to scan and the missing status contradicts the checkmarks.
- Desired correction: open a full-width question detail drawer/page with a clear verdict, expected answer/path, retrieved evidence, and trace linkage.

### GUI-126 — P1 — System Prompt edits take effect immediately with ambiguous corpus/global scope
- Location: Eval Analysis / System Prompts.
- Evidence: [119](screenshots/119-eval-system-prompts.png), [120](screenshots/120-eval-prompt-editor.png), and [121](screenshots/121-eval-prompt-edit-mode.png).
- Observed: the page states that changes save to the active corpus when one is selected, otherwise to the global default, and “take effect immediately for every new answer.” Each prompt exposes Edit, Reset, and Save Changes without a version draft, diff, test, approval, or rollback step.
- User impact: a user can silently change production answer behavior for one corpus or globally without being certain which scope is active.
- Desired correction: require explicit scope, create a versioned draft, show diff/test impact, and promote with rollback rather than saving directly to the active prompt.

### GUI-127 — P2 — Prompt configuration is duplicated across three different product areas
- Location: Chat / Settings → Model, RAG / Retrieval → Generation/Prompt buttons, and Eval Analysis / System Prompts.
- Evidence: [046](screenshots/046-chat-settings-subtab-top.png), [081](screenshots/081-rag-retrieval-fusion-bottom.png), [085](screenshots/085-rag-model-assignments-table.png), and [119](screenshots/119-eval-system-prompts.png).
- Observed: overlapping Chat, Direct, RAG-only, Recall-only, RAG+Recall, Query Expansion, Query Rewrite, and indexing prompts appear in different editors with different save/reset language.
- User impact: users cannot identify the authoritative editor or predict which prompt a request will use.
- Desired correction: provide one versioned Prompt Registry with usage mapping, scope, precedence, and deep links from read-only consumers.

### GUI-128 — P2 — Eval Dataset uses fragile free-text path syntax and unlabeled inline editing
- Location: Eval Analysis / Eval Dataset.
- Evidence: [117](screenshots/117-eval-dataset-top.png) and [118](screenshots/118-eval-dataset-edit.png).
- Observed: expected paths are entered as a comma-separated free-text field; expected answer is optional but controls Promptfoo eligibility. Inline Edit replaces one row with three unlabeled inputs and small Save/Cancel controls inside a separately scrolling list.
- User impact: malformed separators or ambiguous paths can corrupt evaluation expectations, and edited fields are difficult to identify accessibly.
- Desired correction: use structured path chips/file selection, validate eligibility, label every edit field, and open editing in a stable form with provenance.

### GUI-129 — P2 — Tiny Edit/Delete controls are repeated on every evaluation row
- Location: Eval Analysis / Eval Dataset list.
- Evidence: [117](screenshots/117-eval-dataset-top.png) and [118](screenshots/118-eval-dataset-edit.png).
- Observed: six dense entries each end with small adjacent Edit and red Delete buttons. There is no selection model, bulk review, version history, or visible deletion consequence.
- User impact: users can mis-click Delete while scanning long questions and lose synthetic/manual provenance context.
- Desired correction: move row actions into a menu, require a clear confirmation with recoverability, and support versioned/bulk dataset management.

### GUI-130 — P2 — Trace Viewer repeats a context-free global latest trace
- Location: Eval Analysis / Trace Viewer.
- Evidence: [122](screenshots/122-eval-trace-viewer.png).
- Observed: the page defaults to `LATEST TRACE` across All corpora and shows the same recent Chat request seen elsewhere, with Policy, Intent, and Final K as dashes. It does not link the trace to an eval run, question, or current task.
- User impact: an evaluator can mistake ordinary Chat telemetry for evidence about the selected evaluation.
- Desired correction: require selection from an eval run/question or explicit trace ID and show origin, corpus, request type, and complete policy context.

### GUI-131 — P3 — Eval Trace Viewer wastes most of the workspace after one small trace card
- Location: Eval Analysis / Trace Viewer.
- Evidence: [122](screenshots/122-eval-trace-viewer.png).
- Observed: one compact latest-trace card sits at the top while the rest of the main workspace is empty and an empty Dock remains open.
- User impact: the page provides neither trace history nor a useful large-format visualization despite consuming a full route.
- Desired correction: add searchable trace history, a timeline/waterfall, request details, and a collapsible inspector using the available space.

## Infrastructure

### GUI-132 — P1 — Global HEALTH reports OK while the operator deck shows two firing alerts
- Location: Shared shell HEALTH indicator and Infrastructure / Monitoring → Alert Rules.
- Evidence: [130](screenshots/130-infrastructure-monitoring.png) and [132](screenshots/132-infrastructure-monitoring-bottom.png).
- Observed: the global header remains green `HEALTH OK`, while Monitoring reports `5 rules · 2 firing`: `RagweldWatchdog` is firing immediately and `RagweldLocalModelDown` is firing at warning severity. The same deck also says the learning backend is unavailable and learning runs will fail closed.
- User impact: the product's most prominent health signal tells an operator everything is fine while the dedicated operator surface says action is required.
- Desired correction: derive the global state from the same alert/readiness model, distinguish healthy/degraded/action-required, and make the header open the exact failing conditions.

### GUI-133 — P1 — Docker repeats Restart and Stop across 26 services as undifferentiated one-click actions
- Location: Infrastructure / Docker.
- Evidence: [125](screenshots/125-infrastructure-docker.png) and [127](screenshots/127-infrastructure-docker-bottom.png).
- Observed: 26 service cards repeat `Logs`, `Restart`, and `Stop`, producing roughly 52 destructive operational controls in one long page. Database, auth, ingress, observability, model, and application services receive the same visual weight; no dependency order, blast radius, maintenance state, or recovery guidance is shown.
- User impact: an impatient operator can stop a critical dependency while scanning repetitive controls and has no indication of what else will fail.
- Desired correction: group services by dependency/criticality, move destructive actions into a service menu, show dependents and recovery consequences, and require explicit confirmation for restart/stop.

### GUI-134 — P2 — Services is a 3,152px implementation inventory without task-level summary or filtering
- Location: Infrastructure / Services.
- Evidence: [123](screenshots/123-infrastructure-entry.png) and [124](screenshots/124-infrastructure-services-bottom.png), plus measured scroll height.
- Observed: the page enumerates host API, databases, application containers, ingress, session storage, retrieval, MLOps, observability, and the full Langfuse stack in one 3,152px status dump. Raw names such as host-internal endpoints and container roles dominate; there is no search, filter, failed-only view, dependency map, or task summary.
- User impact: a user must manually scan dozens of green rows to find what matters and cannot answer “what is broken for my task?”
- Desired correction: lead with user-facing capabilities and incidents, provide failed/degraded filters and search, and keep the complete implementation inventory behind drill-down.

### GUI-135 — P2 — Service logs open in an oversized, mostly empty modal with duplicate Close controls
- Location: Infrastructure / Docker → PostgreSQL → Logs.
- Evidence: [126](screenshots/126-infrastructure-docker-logs.png).
- Observed: the modal consumes nearly the full viewport for a few lines at the top, leaving most of the body blank. It provides a full-width `Close` button plus a separate icon labeled `Close logs`, but no search, severity filter, time range, follow, wrap, copy, or download controls.
- User impact: the modal interrupts the entire workflow yet is less useful than a compact log drawer, and duplicate dismissal controls compete for attention.
- Desired correction: use a resizable log drawer with one standard close affordance, meaningful height behavior, search/filter/time/follow controls, and copy/download.

### GUI-136 — P1 — Paths & Stores mixes production connection settings and corpus metadata behind one direct Save
- Location: Infrastructure / Paths & Stores.
- Evidence: [129](screenshots/129-infrastructure-paths-stores.png) and live control inventory.
- Observed: editable PostgreSQL DSN, Neo4j URI/user/database/mode, corpus name/path, and corpus description share one form and one `SAVE CONFIGURATION` button. The DSN visibly contains a `[redacted]` token inside an editable connection string, while the Neo4j password is separately described as environment-only; no staged diff, connection test, scope summary, restart impact, or final review is shown.
- User impact: users can mistake the redaction marker for a real value, overwrite a working credential reference, or change database and corpus identity together without knowing the blast radius.
- Desired correction: separate connection, tenancy, and corpus metadata workflows; preserve secrets outside editable strings; show validation/diff/restart impact; and require an explicit review before apply.

### GUI-137 — P2 — Disabled per-corpus database controls still read as current configuration
- Location: Infrastructure / Paths & Stores → Database Mode.
- Evidence: [129](screenshots/129-infrastructure-paths-stores.png) and live field-state inventory.
- Observed: Shared mode is selected, yet `PER-CORPUS DB PREFIX` remains visibly populated with `tribrid_` and `AUTO-CREATE PER-CORPUS DATABASES` remains visibly checked. Both controls are disabled, but the page does not say they are ignored in Shared mode.
- User impact: operators cannot tell which displayed values are effective and may believe per-corpus databases are still being created.
- Desired correction: hide inactive fields or group them under an explicit inactive Per-corpus section with an effective-configuration summary.

### GUI-138 — P2 — MCP probe gives the question one quarter of the row and the disabled action the rest
- Location: Infrastructure / MCP Servers → Probe the search tool.
- Evidence: [128](screenshots/128-infrastructure-mcp.png) and measured field geometry.
- Observed: the only text field is about 190px wide while the disabled `RUN SEARCH` button stretches across roughly 528px. The long example placeholder is clipped before the user can understand it, and the disabled button visually dominates the task.
- User impact: the input needed to enable the action is difficult to read and use, while the unavailable action looks like the primary content.
- Desired correction: give the question field the full row, place a normally sized action beside/below it, and show validation/help without relying on clipped placeholder text.

### GUI-139 — P2 — Monitoring is 5,636px tall and wastes half of the workbench inside its longest section
- Location: Infrastructure / Monitoring.
- Evidence: [130](screenshots/130-infrastructure-monitoring.png), [131](screenshots/131-infrastructure-monitoring-middle.png), and [132](screenshots/132-infrastructure-monitoring-bottom.png), plus measured scroll height.
- Observed: the operator deck reaches 5,636px. In the long surface-health area, fixed narrow cards occupy only the left half of the main workbench while a large right column remains blank; the permanently open empty Dock consumes still more width.
- User impact: users scroll through thousands of pixels even though the viewport has enough horizontal space to show substantially more status at once.
- Desired correction: preserve the Dock as a parallel operator workspace, improve access to the existing draggable split, make the main monitoring grid responsive to its allocated width, add failed/degraded filters, and make secondary diagnostic groups collapsible.

### GUI-140 — P1 — Many Monitoring “Open surface” links point to browser-local loopback addresses
- Location: Infrastructure / Monitoring → External surfaces and health cards.
- Evidence: [130](screenshots/130-infrastructure-monitoring.png), [131](screenshots/131-infrastructure-monitoring-middle.png), and live link inventory.
- Observed: OTLP, Alloy, Tempo, Mimir, Pyroscope, Alertmanager, LiteLLM, vLLM, and Qdrant links target `127.0.0.1` URLs. In a remote browser session, those addresses resolve to the user's own computer rather than the Ragweld host, even while cards label several destinations `reachable` and present `Open surface` actions.
- User impact: controls that look operationally ready open the wrong machine or fail, undermining the deck's core promise.
- Desired correction: advertise only deployment-reachable public/proxied URLs, disable unavailable destinations with an explanation, and keep host-local endpoints as copyable diagnostics rather than navigation.

### GUI-141 — P2 — Monitoring presents three overlapping navigation systems in one deck
- Location: Infrastructure / Monitoring.
- Evidence: [130](screenshots/130-infrastructure-monitoring.png) and live link inventory.
- Observed: the top contains external-surface pills, a second `IN THIS APP` shortcut row, and each health card repeats another `Open surface` action. Labels alternate among tool names, user tasks, and generic `Open surface`, so the same destination can appear two or three times without explaining which path is preferred.
- User impact: users cannot form a stable mental model of where observability work belongs and repeatedly leave their current context.
- Desired correction: use one task-oriented navigation layer, keep service-specific links inside details, and label every destination by purpose and availability.

### GUI-142 — P2 — Alert rows use contradictory state language and implementation-first expressions
- Location: Infrastructure / Monitoring → Alert Rules.
- Evidence: [132](screenshots/132-infrastructure-monitoring-bottom.png).
- Observed: multiple rows are marked green `OK` while their descriptions say the API, gateway, or exporter “is not being scraped”; the table then exposes PromQL-like expressions such as `up{job=...} == 0` without a plain-language evaluated value. `RagweldWatchdog` fires with severity `none`.
- User impact: a non-specialist cannot tell whether “not being scraped” is the alert condition, a description of the rule, or the current state, and a firing rule with no severity looks like a data error.
- Desired correction: separate current observation from alert definition, show last value/last evaluation, use plain-language consequences, and require a meaningful severity taxonomy.

## Admin

### GUI-143 — P1 — Admin Basic is a 39,177px wall of configuration cards
- Location: Admin / Basic.
- Evidence: [133](screenshots/133-admin-entry.png) through [141](screenshots/141-admin-basic-bottom.png), plus measured scroll height and visible-control inventory.
- Observed: one route stacks Runtime, Retrieval, Observability, Training, Eval, Graph, and Shell into a 39,177px page. It renders 131 visible fields and 314 visible buttons; some individual groups are 5,162px, 7,052px, 9,450px, and 8,694px tall. Once scrolling, the group heading and Configuration Center context disappear.
- User impact: no person can maintain orientation, compare related values, or confidently return to a setting across a page roughly 28 desktop viewports long.
- Desired correction: make each domain a navigable route/accordion with search, sticky context, changed-only filtering, task presets, and concise summaries before field-level drill-down.

### GUI-144 — P1 — Admin Advanced renders all 454 settings into a 96,367px page
- Location: Admin / Advanced.
- Evidence: [142](screenshots/142-admin-advanced-top.png), [143](screenshots/143-admin-advanced-sidebar-filter.png), [144](screenshots/144-admin-advanced-dock-filter.png), and live DOM measurements.
- Observed: the page announces `Showing 454 of 454 registered fields` and renders a 96,367px document with 369 visible inputs and 818 visible buttons before filtering. That is roughly 70 desktop viewports of controls in one DOM-backed list.
- User impact: the “complete registry” becomes practically unnavigable, expensive to render, and hostile to keyboard/screen-reader use even before a user understands any setting.
- Desired correction: virtualize the result list, require a domain/task or search selection before showing fields, persist filters, expose result grouping, and provide a compact table mode.

### GUI-145 — Withdrawn — Missing Admin registry entries do not establish that Dock resizing is unavailable
- Location: Admin / Advanced search and Admin / Raw → `ui`.
- Evidence: [143](screenshots/143-admin-advanced-sidebar-filter.png), [144](screenshots/144-admin-advanced-dock-filter.png), and [147](screenshots/147-admin-raw-ui-section.png).
- Observed: searching `sidebar` returns 0 of 454 settings. Searching `dock` returns 13 Docker settings rather than a width, collapse, split, or responsive layout control. The raw `ui` section foregrounds chat history, streaming, citations, debug, model, timeout, and Grafana values, while no rail-width/collapse setting is visible.
- Correction: the search observation is accurate, but the claimed inability to resize was not. Dock allocation is local UI state, stored outside the backend configuration registry; the existing desktop drag control works and persists width. Absence from Admin is not independently a product defect. Actual resizing discoverability/accessibility and content reflow failures are recorded separately, and this ID is excluded from open-finding counts.

### GUI-146 — P2 — Every scalar setting becomes a full bordered card with repeated controls
- Location: Admin / Basic and Advanced.
- Evidence: [134](screenshots/134-admin-basic-runtime-middle.png) through [141](screenshots/141-admin-basic-bottom.png), and [142](screenshots/142-admin-advanced-top.png).
- Observed: each boolean, number, URL, path, or model receives its own large bordered card, often with one field, an `Open Raw` button, and another `Stage` control. The pattern consumes roughly 120–150px per value and repeats hundreds of times.
- User impact: borders and chrome dominate the data, related values cannot be compared side by side, and scanning cost grows linearly with every setting.
- Desired correction: use compact grouped forms or a table with aligned labels/values, reserve cards for coherent tasks, and move raw/stage actions to row menus or batch review.

### GUI-147 — P2 — Hundreds of repeated `Open Raw` and `Stage` names are ambiguous to assistive technology
- Location: Admin / Basic and Advanced.
- Evidence: [133](screenshots/133-admin-entry.png), [142](screenshots/142-admin-advanced-top.png), and live button inventory.
- Observed: Admin Basic has hundreds of buttons whose visible/accessibility text is only `Open Raw` or `Stage`; Advanced expands this to 818 visible buttons. The control name does not include the associated setting, and repeated cards have no unique action wording.
- User impact: screen-reader button lists and voice control produce hundreds of indistinguishable targets; keyboard users must traverse enormous sequences to identify context.
- Desired correction: include the setting name in accessible labels, use one row-level action menu, support direct searchable navigation, and skip inactive/redundant actions in tab order.

### GUI-148 — P1 — Disabled integrations leave their underlying settings fully editable-looking
- Location: Admin / Basic → Runtime and Training.
- Evidence: [133](screenshots/133-admin-entry.png), [134](screenshots/134-admin-basic-runtime-middle.png), and [137](screenshots/137-admin-basic-training.png).
- Observed: vLLM, Flyte, Unsloth, and MLflow are labeled disabled, yet their base URLs, models, training backends, LoRA values, timeouts, and paths continue as normal editable fields with active `Stage` buttons. Other disabled feature toggles similarly leave related model/value cards visually active.
- User impact: users cannot tell which settings are effective, staged for future enablement, or stale, and may spend time “fixing” values that runtime ignores.
- Desired correction: group settings under the feature state, visibly disable ignored controls, allow an explicit “configure before enabling” mode, and show the effective configuration separately.

### GUI-149 — P1 — Raw editor can replace any of 31 whole configuration sections without visible version recovery
- Location: Admin / Raw.
- Evidence: [145](screenshots/145-admin-raw-top.png), [146](screenshots/146-admin-raw-edit-mode.png), [147](screenshots/147-admin-raw-ui-section.png), and live section inventory.
- Observed: a selector exposes 31 top-level sections and states that the chosen section “will be replaced exactly as parsed JSON.” Edit mode reveals `Cancel` and `Save Section`, but no before/after diff, schema documentation, validation result, version identity, backup, rollback target, restart/reindex impact, or affected-surface list is visible beside the action.
- User impact: one syntactically valid but incomplete object can erase nested defaults or change broad production behavior without an understandable recovery path.
- Desired correction: stage a schema-validated patch rather than replacement, show a structured diff and impact analysis, create a recoverable version, and require explicit review before apply.

### GUI-150 — P2 — Raw editor is a small code viewport surrounded by mostly unused screen
- Location: Admin / Raw.
- Evidence: [145](screenshots/145-admin-raw-top.png) through [147](screenshots/147-admin-raw-ui-section.png).
- Observed: the Monaco area is only about 258px tall and shows roughly 20 lines while the rest of the route is blank. Long system-prompt lines extend horizontally beyond the visible area, so reviewing a complete section requires nested vertical and horizontal scrolling.
- User impact: the highest-risk editor gets less usable space than the empty Dock and unused page area around it.
- Desired correction: let the user allocate the split while giving Raw a viewport-height editor, enable wrapping/search/formatting, and keep diff/validation panels alongside it; the Dock should remain usable rather than merely consuming a fixed allocation.

### GUI-151 — P2 — Basic loses domain context thousands of pixels before the user reaches a field
- Location: Admin / Basic while scrolled within Runtime, Observability, Training, Eval, Graph, and Shell.
- Evidence: [134](screenshots/134-admin-basic-runtime-middle.png) through [141](screenshots/141-admin-basic-bottom.png).
- Observed: only the global breadcrumb `Admin / Basic` and tab strip remain visible; the current domain heading, description, readiness state, and position within the group scroll away. Mid-page screenshots become indistinguishable chains of setting cards.
- User impact: users cannot tell whether an `Enabled`, URL, timeout, or model belongs to runtime, training, graph, or shell without parsing raw config paths.
- Desired correction: add sticky domain breadcrumbs/section navigation and show setting ancestry in a compact persistent header.

### GUI-152 — P2 — Dependencies is another 3,841px status dump with no remediation workflow
- Location: Admin / Dependencies.
- Evidence: [148](screenshots/148-admin-dependencies-top.png), [149](screenshots/149-admin-dependencies-secrets.png), and measured scroll height.
- Observed: readiness cards and environment-variable status cards are stacked into a 3,841px page. Missing Flyte/Unsloth config, Grafana API key, Slack/Discord webhooks, Netlify key, and MCP key are named, but there is no owner, importance, affected user task, setup link, test action, or distinction between optional and blocking issues beyond prose.
- User impact: the page tells operators what identifiers are missing but not what must be fixed first or how to verify resolution.
- Desired correction: separate blockers from optional integrations, map each to affected tasks, provide safe setup/test guidance, and show ownership and last verification.

### GUI-153 — P2 — Dependency Refresh is a tall vertical block rather than a normal action
- Location: Admin / Dependencies header.
- Evidence: [148](screenshots/148-admin-dependencies-top.png).
- Observed: `Refresh` is rendered as a narrow button roughly the full height of the header copy, visually resembling a side panel instead of a standard action aligned with the title.
- User impact: the action looks broken or unusually consequential and wastes header space.
- Desired correction: use a standard compact refresh action with last-checked time and in-place progress/status feedback.

## Shared split-workspace behavior

### GUI-154 — P1 — Docked Dashboard is squeezed as a desktop page instead of adapting to the Dock
- Location: Chat main workspace + Dock: Dashboard — System Status.
- Evidence: [153](screenshots/153-chat-keyboard-focus-last-control.png), [154](screenshots/154-dock-chooser-live.png), and measured Dock overflow.
- Observed: the Dock is correctly acting as a persistent parallel workspace, but the docked Dashboard keeps a 521px internal grid inside a content column measured at about 182px. Text wraps into single-character columns, values are clipped, borders extend beyond their cards, and child scroll width is hidden by ancestors. Initial allocation was roughly 348 CSS px. Correction after direct drag testing: a desktop splitter exists and persists its width; widening the Dock to 546px still leaves a 522px grid overflowing a 375px content area ([164](screenshots/164-dock-drag-widened.png)). The failure is missing container-aware reflow, not a total absence of resizing.
- User impact: the product's most powerful multitasking feature becomes unreadable exactly when it is used for its intended comparison workflow.
- Desired correction: define a Dock component contract and compact variants for every dockable route, make the existing splitter discoverable and keyboard accessible, support task-specific allocations, enforce minimums for both workspaces, and test every route/subtab at narrow, medium, and wide Dock allocations.

### GUI-155 — P1 — Keyboard navigation skips the entire Dock and lower Chat diagnostics
- Location: Chat / Interface with Dashboard docked and Routing Trace expanded.
- Evidence: [152](screenshots/152-chat-keyboard-focus-corpus.png), [153](screenshots/153-chat-keyboard-focus-last-control.png), and a current 53-stop keyboard trace.
- Observed: focus moves through header, global navigation, Chat toolbar, welcome prompts, composer, Attach, On Vector, and On Sparse. The next Tab lands on `BODY` and then cycles back to Glossary. It never reaches the Routing Trace disclosure, trace links, log filter/refresh/clear controls, or any Dock controls/content, even though those controls are clickable and exposed in the accessibility tree.
- User impact: keyboard-only users cannot operate the parallel Dock workspace or most diagnostic actions, and there is no visible indication that the focus loop has abandoned the rest of the screen.
- Desired correction: establish one logical focus order across main and Dock panes, make all interactive disclosures/actions keyboard reachable, add a skip-to-Dock shortcut and pane focus indicator, and regression-test the full loop in empty and populated Dock states.

### GUI-156 — P1 — `Jump to latest` stays disabled after the message viewport is scrolled to the top
- Location: Chat / Interface → populated 10-message conversation.
- Evidence: [155](screenshots/155-chat-history-for-jump-test.png), [156](screenshots/156-chat-populated-before-jump.png), [157](screenshots/157-chat-scrolled-top-jump-enabled.png), live DOM state, and `web/src/components/Chat/ChatInterface.tsx:2346-2374`.
- Observed: the populated message viewport measured 8,517px of content in a 378px viewport and initially sat at scrollTop 8,139. After scrolling it to 0, the sticky `Jump to latest` control remained `disabled=true`, had no `aria-disabled` explanation, and retained fully opaque active-button styling. On an empty thread the same always-rendered control is also visible and disabled. Source renders `ThreadPrimitive.ScrollToBottom` unconditionally and supplies no product-level visibility/state fallback.
- User impact: the promised escape from an 8,500px conversation does nothing, looks clickable, and occupies message space even when no message exists.
- Desired correction: show the control only when the message viewport is meaningfully away from the bottom, keep its enabled state synchronized with the actual scroll container, provide correct disabled/hidden semantics, and add E2E coverage for empty, bottom, middle, and top scroll positions.

### GUI-157 — P1 — Dock chooser and fullscreen Graph let keyboard focus remain behind their modal and lose the opener on close
- Location: shared Dock → Choose… → Search tabs and subtabs; RAG / Graph → Visualization → Expand.
- Evidence: [161](screenshots/161-dock-chooser-focus.png), [162](screenshots/162-dock-dialog-focus-escape.png), [193](screenshots/193-graph-fullscreen-reopen.png), [194](screenshots/194-graph-fullscreen-background-focus.png), and current DOM focus observations.
- Reproduction: open Choose…, press Tab from the initially focused search input, then press Tab again. Refocus the search input and press Escape.
- Observed: the first Tab moves focus to BODY while the modal remains open; the second focuses the obscured global Glossary button. Escape from search closes the modal but leaves focus on BODY instead of Choose…. The dialog advertises aria-modal while background controls remain keyboard reachable.
- Broader reproduction: opening the fullscreen Graph leaves focus on the obscured Expand button outside the modal. One Tab then focuses the background Dock Settings button (`dock-mode-settings`), still outside the visible dialog. Escape successfully closes Graph after its dismissal transition, but focus ends on BODY rather than Expand. This is a second independently rendered modal with the same broken focus lifecycle; it is not counted as a duplicate new finding.
- User impact: keyboard users leave the dock-selection task without seeing where focus went, can operate background controls under an open modal, and must retraverse the interface after cancelling.
- Desired correction: contain Tab and Shift+Tab within the dialog, make the background inert while open, preserve arrow-key selection in the list, and restore focus to the invoking Choose… button on every dismissal path.

### GUI-158 — P2 — Dock keyboard selection disappears below the list without scrolling into view
- Location: Dock → Choose… → search input, unfiltered list.
- Evidence: [163](screenshots/163-dock-picker-offscreen-selection.png), DOM geometry, and DockPickerModal keyboard handler.
- Reproduction: open the chooser and press End in its focused search input.
- Observed: Admin / Raw becomes aria-selected and the active descendant, but its top is at 3,078 CSS px while the dialog viewport ends at 1,360px. The dialog stays at scrollTop 0; no selected row is visible. The same handler changes the index on arrow navigation without scrolling the selected option into view.
- User impact: users can select an invisible destination and press Enter without knowing which view will replace the Dock.
- Desired correction: scroll each newly active option into the chooser's visible region while retaining focus in search; cover arrow navigation, Home/End, filtering, and mouse-to-keyboard transitions.

### GUI-159 — P2 — The working desktop Dock splitter has no keyboard or assistive-technology interface
- Location: shared main/Dock boundary, with Dashboard / System Status docked.
- Evidence: [164](screenshots/164-dock-drag-widened.png), live splitter DOM attributes, `web/src/App.tsx` and `web/src/utils/uiHelpers.ts`.
- Observed: the roughly 10px-wide resize hit area is a plain div with no role, accessible name, focusability, orientation, or current/minimum/maximum value. Actual mouse dragging changes the width from 348px to 546px, and the value survives reload. There is no equivalent keyboard control. The compact-breakpoint loss of this control is separately reproduced in GUI-163.
- User impact: a keyboard or screen-reader user cannot discover or change the allocation of two powerful workspaces; mouse users receive very little indication that the boundary is interactive.
- Desired correction: expose an accessible, focusable vertical separator with a useful name, current/min/max values, arrow-key and Home/End resizing, visible focus/hover feedback, and a deliberate compact-width allocation strategy. Preserve the existing persisted width behavior.

## Source-discovered routes outside the main navigation

### GUI-160 — P2 — A production same-origin dashboard route serves a synthetic demonstration beside live operational status
- Location: `/web/d/ragweld-oncall-overview/on-call-overview`, the app's `/d/:uid/:slug` route.
- Evidence: [165](screenshots/165-live-synthetic-dashboard.png), [166](screenshots/166-second-dashboard-same-metrics.png), current rendered text, and `web/src/pages/GrafanaEmbed.tsx`.
- Observed: the authenticated production shell renders fixed demo metrics (MRR 0.73, latency 241ms, 2.3% error rate, seven corpora) and a synthetic healthy-alert panel. The adjacent live Dock reports five corpora. A sentence explicitly discloses simulated data, so this is not an undisclosed-data finding; nevertheless the demo occupies a real dashboard-shaped route within the live operator shell. Opening the source-listed Cost & Capacity destination renders the same metrics with only the title changed. The implementation ignores the dashboard UID and uses the slug only as its title.
- User impact: bookmarked or same-origin dashboard destinations can deliver a demonstration instead of the requested operational board, and the current corpus/global health context visually surrounds data unrelated to either.
- Desired correction: isolate demonstrations in an explicitly selected demo environment. On production dashboard destinations, resolve the requested real board or show an honest unavailable/not-found state with a reachable operational destination.

### GUI-161 — P2 — Demo dashboard says “Refresh 10s” and “Updated” without refreshing or measuring freshness
- Location: same-origin dashboard header.
- Evidence: [165](screenshots/165-live-synthetic-dashboard.png), repeated live DOM snapshots, and `GrafanaEmbed.tsx`.
- Observed: `Updated 11:58:30 PM` remained unchanged through the 12:01–12:02 AM observations while the adjacent pill advertised `Refresh 10s`. The source takes the refresh label from a query parameter but implements no polling; Updated is just the render time, not a data timestamp. Last 1h is also a label over fixed constants, not a query window.
- User impact: time and refresh affordances imply recent observations in a surface styled as an operational dashboard, even though waiting cannot update it.
- Desired correction: remove time/freshness claims from static examples, or implement the actual selected query interval, refresh mechanism, last successful data timestamp, and stale/error states for real data.

### GUI-162 — P2 — An entire Grafana card explains internal demo implementation instead of helping the operator
- Location: same-origin dashboard → Ops Notes.
- Evidence: [165](screenshots/165-live-synthetic-dashboard.png).
- Observed: the visible card discusses “same-origin embed compatibility,” the local `/web/grafana` route, and editing `ui.grafana_base_url` to switch back to live Grafana. Other panel descriptions explain where future production signals “would” appear.
- User impact: a user seeking monitoring receives implementation/migration notes and hypothetical capabilities instead of current information or an actionable connection workflow. This is another dev-copy surface outside the now-cleaned Chat UI.
- Desired correction: keep implementation/migration notes in developer documentation. If setup is actually required, show a concise unavailable state with a labeled configuration action and explicit scope, not a demo dashboard full of future-tense descriptions.

## Responsive shell and parallel workspaces

### GUI-163 — P1 — Compact desktop widths remove the splitter and force a clipped 320px Dock
- Location: Chat plus Dashboard / System Status Dock, measured viewport 1,179 × 1,000 CSS px.
- Evidence: [169](screenshots/169-chat-css1179-splitter-hidden.png), measured geometry and computed styles.
- Observed: the same working desktop splitter changes to display:none and the Dock is forced to 320px rather than the saved 348px allocation. Dashboard labels again wrap into narrow fragments and values are cut off. Choose/Swap/Clear wrap across rows, but there is no usable resize alternative at this width.
- User impact: making the app window moderately narrower removes the user's means of trading space between panes precisely when either task needs that control most.
- Desired correction: keep an accessible allocation mechanism at compact widths, retain minimum usable pane widths, and provide deliberate reflow or pane switching when simultaneous display is no longer usable. Do not force the full Dashboard into an unsupported rail width.

### GUI-164 — P1 — At 880px the main navigation disappears without its replacement menu button
- Location: deployed shared shell, measured viewport 880 × 1,000 CSS px.
- Evidence: [170](screenshots/170-chat-css880-dock-below.png), live DOM geometry, and served CSS rule inspection.
- Observed: the main navigation is positioned from x=-200 to x=0, entirely off-screen. Toggle navigation is display:none with a zero-size rectangle. The media query for max-width:900px is active, but the served CSS only enables the menu button at max-width:768px. The button reappears at the tested 716px viewport. Thus the 769–900px band has neither visible primary links nor their normal opener.
- User impact: resizing a window or increasing zoom can strand the user on the current page with no primary navigation. The Dock chooser is not a discoverable substitute for the main menu.
- Desired correction: use the same breakpoint for hiding primary navigation and showing its replacement; test just below, at, and above both boundaries, including browser zoom. Note: the local source already contains a 900px toggle rule, but it is absent from the deployed CSS; source presence is not deployment proof.

### GUI-165 — P1 — Mobile stacking leaves Chat a clipped upper pane instead of a usable conversation workspace
- Location: Chat / Interface with populated Dashboard Dock, measured viewport 716 × 1,000 CSS px.
- Evidence: [171](screenshots/171-chat-css716-stacked.png), [176](screenshots/176-mobile-chat-composer-visible.png), and measured ancestor geometry.
- Observed: the wrapped header occupies 163px, then the main pane ends at y=500 while the Dock consumes the lower 500px. Main content is only about 337px tall, including breadcrumb/tab chrome. Initially the toolbar fills the usable Chat area; the composer is at y=803 and is covered by the Dock. A carefully positioned scroll can recover the composer at y=385, so it is not permanently unreachable, but only a sliver of conversation remains above it and supporting controls are cut off below.
- User impact: the user must alternate between reading and composing in a tiny scrolling slot, while the secondary workspace has a hard-coded half-screen allocation. There is no vertical splitter or full-pane switch to give either task adequate space.
- Desired correction: provide intentional compact-screen main/Dock switching or an accessible vertical allocation control, account for actual wrapped-header height, and keep composer plus a useful message region available together.

### GUI-166 — P2 — Mobile main-pane clipping hides the shared Save bar under the Dock
- Location: shared main content footer in the 716 × 1,000 CSS px stacked layout.
- Evidence: [171](screenshots/171-chat-css716-stacked.png), [176](screenshots/176-mobile-chat-composer-visible.png), and live Save/main-pane rectangles.
- Observed: the Save control occupies y=657–694, but its overflow-hidden main ancestor ends at y=500 and the Dock begins there. Scrolling the inner Chat content does not move that footer into view. The control was disabled because the audit had no staged settings; enabled/staged submission was deliberately not exercised.
- User impact: the shared status/apply area is absent from the visible mobile workspace. Settings users would have no visible footer review affordance in this same layout; enabled-state behavior remains to be verified safely.
- Desired correction: size the main content and footer within their actual allocated pane, keep the footer reachable without scrolling another pane, and test clean, dirty, saving, error, and success footer states at compact widths.

### GUI-167 — P3 — The mobile navigation drawer does not respond to Escape
- Location: Chat at 716px viewport → Toggle navigation.
- Evidence: [172](screenshots/172-mobile-navigation-open.png) and live expanded-state observation after Escape.
- Reproduction: open the navigation drawer with its menu button and press Escape while the opener is focused.
- Observed: the drawer remains open and the opener retains aria-expanded=true. Clicking the toggle closes it. No destination was selected or configuration changed.
- User impact: a conventional keyboard dismissal does nothing and leaves the page obstructed until the user finds or returns to the toggle.
- Desired correction: support Escape dismissal with focus returned to the opener, and define/test the drawer's focus and background-interaction model alongside click/touch dismissal.

### GUI-168 — P2 — The phone header uses 30% of the screen before the user reaches any task
- Location: shared top bar at a measured 391 × 838 CSS px viewport.
- Evidence: [178](screenshots/178-chat-css391-phone-ready.png) and live header/main geometry.
- Observed: menu/brand, Glossary, corpus/theme, Health, and search wrap into five rows. The header is 251px high (30% of the viewport). Combined with the fixed lower-half Dock, only 168px remains for the entire main pane, including breadcrumb and subtabs; the only initial Chat content visible is its heading.
- User impact: persistent utility controls displace the task almost completely. The user must scroll a tiny pane before even seeing conversation controls.
- Desired correction: create a deliberate compact header hierarchy with essential context and navigation visible, move secondary utilities into an accessible menu, and allocate both workspaces from remaining height rather than total viewport height.

### GUI-169 — P2 — Global search presents an inert Escape label as its only explicit dismissal cue on touch layouts
- Location: global search dialog at phone width.
- Evidence: [179](screenshots/179-phone-global-search.png), [180](screenshots/180-phone-global-search-results.png), and live click/control checks.
- Observed: the dialog has zero buttons. The top-right ESC box looks like a small close control, but clicking it leaves the dialog open. The footer also says ESC close. A real Escape key dismisses the dialog; there is no equivalent explicit touch close button. Background dismissal was not used to infer a blocking dead end.
- User impact: a touch user receives keyboard-only instructions and a control-shaped label that does nothing, unlike the Dock chooser's working Esc button.
- Desired correction: provide a real Close button with a useful accessible name and adequate touch target, retain Escape as an additional shortcut, and apply the same dismissal pattern to shared dialogs.

### GUI-170 — P2 — Search highlighting splits words into separated flex items
- Location: global search → query `model` → Benchmark / Max Concurrent Models result, phone width.
- Evidence: [180](screenshots/180-phone-global-search-results.png) and the live result-title DOM.
- Observed: the title is a flex container with an 8px gap; its plain text, highlighted Model span, trailing s text, and config badge are separate flex items. The result visibly breaks “Models” into “Model” and a detached “s”, with preceding words wrapping separately. This is structural text fragmentation, not merely a narrow line wrap.
- User impact: users scanning results see distorted setting names and cannot read a normal phrase across the line breaks.
- Desired correction: keep the entire highlighted title in one inline text-flow child and place the badge beside that child; test partial-word, multiple-match, long-title, no-match, and narrow-width cases.

### GUI-171 — P2 — The phone corpus registry introduces horizontal scrolling inside its vertical modal
- Location: global corpus registry at 391px viewport, list and lower Create corpus form.
- Evidence: [181](screenshots/181-phone-corpus-registry.png), [182](screenshots/182-phone-corpus-registry-bottom.png), and inner-container measurements.
- Observed: the modal's scrollable panel has a 318px client width but 346px scroll width; corpus rows overflow their 270px content column by up to 52px. Active/runtime badges, long corpus identities, and adjacent full-height Delete controls compress the selection text and extend content to the right. A horizontal scrollbar remains visible while scrolling down to the create form and Close button.
- User impact: choosing a corpus requires navigating two scroll directions in a small overlay, and row actions/identity cannot be read together without panning. The only Close button is below the list and create form rather than remaining visible.
- Desired correction: make corpus rows a single-width responsive layout with wrapped identity text, compact secondary actions/badges, no horizontal modal overflow, and persistent access to dismissal.

## Graph provenance and PDF source verification

### GUI-172 — P1 — PDF evidence shrinks to an unreadable page thumbnail with no in-pane magnification
- Location: RAG / Graph → Fuel community → Fuel entity → source mention p. 155 or p. 180 → Source pane.
- Evidence: [188](screenshots/188-graph-source-pdf155.png), [189](screenshots/189-graph-source-pdf180.png), and rendered PDF image/control measurements.
- Observed: the real mission-report page and orange evidence highlights load correctly, but a 1,228 × 1,750px page image is rendered at approximately 321 × 459 CSS px inside the 348px Source pane. The viewer offers Prev/Next and cited-page chips but no zoom, fit-width/actual-size choice, fullscreen, or readable enlargement within the pane. Dense engineering text and table cells are too small to inspect at this allocation. The working workspace splitter can enlarge the whole pane, but the document itself has no magnification control.
- User impact: the source opens successfully without making the evidence readable enough to verify; users must renegotiate the entire main/Dock split or leave the viewer to inspect a citation.
- Desired correction: provide document zoom and fit-width controls, a readable expanded document mode, and a return path that retains the selected citation, page, and main-workspace context. Preserve the real PDF page and evidence highlights.

### GUI-173 — P2 — PDF cited text renders table markup as a narrow raw-text block
- Location: the same PDF Source pane → Cited text, p. 155 and p. 180.
- Evidence: [188](screenshots/188-graph-source-pdf155.png), [189](screenshots/189-graph-source-pdf180.png), and the rendered `document-cited-text` content; local `PdfPageView.tsx` uses a preformatted text block.
- Observed: extracted Markdown table pipes, headings, and row values are displayed literally in the already narrow pane. Lines wrap into many fragments instead of retaining row/column relationships. The excerpt is open beneath the thumbnail by default; it is not a readable alternative to the small PDF table.
- User impact: users cannot reliably match values to their headers or compare the cited passage with the highlighted page, undermining the purpose of the evidence inspector.
- Desired correction: render supported table/Markdown structure with safe formatting and an appropriate horizontal table viewport, retain an optional raw-text view, and keep source-page highlighting and excerpt selection synchronized.

### GUI-174 — P2 — The Source header clips its Open original escape route beyond the right edge
- Location: Graph citation → Source header for `A11_MissionReport.pdf`.
- Evidence: [188](screenshots/188-graph-source-pdf155.png), [189](screenshots/189-graph-source-pdf180.png), and measured header/link bounds.
- Observed: the Source pane ends at x≈1,631 CSS px, while the Open original link spans x≈1,584–1,677; approximately 46px extends beyond the pane. The screenshot shows the label cut off at the right edge. The document title and page context do not negotiate space with the action at the supported 348px pane allocation.
- User impact: the action needed to escape an unreadable PDF thumbnail is itself partially hidden and cannot be read as a complete control.
- Desired correction: reserve space for source actions, allow the title/context to truncate or wrap deliberately, and keep the complete labeled Open original control within the pane at every supported width.

## Dock-specific configuration layouts

### GUI-175 — P1 — Docked Chat Settings shrinks prompt editors and gateway controls into word fragments
- Location: System Prompts in main; Dock → Chat → Settings → Model, 348px Dock allocation.
- Evidence: [199](screenshots/199-dock-chat-settings.png), [200](screenshots/200-dock-chat-settings-narrow.png), [202](screenshots/202-dock-chat-settings-lower.png), and rendered field measurements.
- Observed: the docked page retains nested outer padding, card padding, and inner form sizing. Each of four prompt textareas measures only 88.8 CSS px wide; words such as “helpful” and “agentic” break over multiple lines. The five settings-mode buttons wrap into a three-row cluster above them. At an 800px Dock allocation the same editors remain substantially narrower than their card, as shown in 199. Subtab navigation itself works correctly and does not replace the main prompt editor.
- Lower-page reproduction: the same 348px Dock creates a 6,072px settings page; Current route wraps a model/endpoint string into tiny fragments and the LiteLLM enable/status columns become one-character-wide vertical runs. The 14px input-group width is smaller than the toggle's own 41px scroll width. No setting was changed.
- User impact: side-by-side prompt review—the useful reason to dock this page—becomes practically unreadable at the saved narrow width, even though both workspaces remain present.
- Desired correction: provide a container-aware compact settings layout, remove redundant inset layers in the Dock, let a selected prompt editor use the pane's readable width, and keep mode navigation deliberate. Preserve independent Dock navigation and user-controlled resizing.

### GUI-176 — P1 — Embedded Benchmark keeps its prompt and Run area offscreen in a narrow Dock
- Location: Dock → Benchmark, 348px and 800px allocations.
- Evidence: [203](screenshots/203-dock-benchmark-embedded.png), [204](screenshots/204-dock-benchmark-wide.png), live iframe bounds/source, and local Benchmark grid definition.
- Observed: at 348px the embedded page shows the model catalog but its adjacent prompt/Run card lies beyond the pane's right edge. Both the model list and embedded page expose horizontal scrollbars. The lower explanatory/result card is clipped horizontally as well. Widening to 800px reveals the prompt card, but the catalog still dominates the row. Local source defines the form as `minmax(320px, 520px) 1fr` without a compact stacked variant.
- User impact: the user can select models in the Dock while the field needed to start the comparison is out of sight. Reaching related inputs requires horizontal panning or surrendering much more main-workspace width.
- Desired correction: stack model selection and prompt review when the container cannot support both, expose selected models compactly, keep prompt and primary action visible, and eliminate horizontal page overflow. Preserve the ability to run Benchmark beside another task; no benchmark was started for this inspection.

### GUI-177 — P1 — Swap loses navigation performed inside an embedded Dock workspace
- Location: main Eval / System Prompts; Dock → Eval Analysis / Analysis → in-frame Trace Viewer → shared Swap.
- Evidence: [205](screenshots/205-dock-eval-analysis-wide.png), [206](screenshots/206-dock-eval-trace-stale-title.png), [207](screenshots/207-dock-eval-swap-wrong-subtab.png), and observed outer URL/iframe source.
- Reproduction: choose Eval Analysis / Analysis in the Dock. Click Trace Viewer inside the embedded page. Verify Latest Trace is visible. Click the shared Dock Swap button.
- Observed: in-frame navigation successfully displays Trace Viewer while the main prompt page remains intact, but the outer Dock title remains `Eval Analysis — Analysis`. Swap then opens `/web/eval?subtab=analysis` in the main pane, replacing the visible Trace Viewer with the originally docked Analysis page. The former main System Prompts page moves into the Dock correctly. Native docked Chat subtab navigation updates its outer Dock title, so the behavior differs between native and embedded targets.
- User impact: promoting a workspace to the main pane discards the user's current destination, makes the title unreliable, and forces them to find the desired tool again. This breaks the purpose of swapping independently navigable workspaces.
- Desired correction: keep the parent Dock target synchronized with the embedded page's actual route/subtab and relevant view context through a validated same-origin navigation contract. Swap and reload must retain the currently displayed workspace, not only its initial URL. Cover native and embedded navigation → Swap → reload as one state-transition family.
