# TV Federated Agency: The Attention Dividend

## Status And Claim Boundary

This document is a technology-opportunity hypothesis. It does not establish
patent scope, freedom to operate, product-market fit, or access to privileged
webOS/HbbTV interfaces. The user's patent is treated as an asserted capability
to detect and replace an advertising interval; its claims have not been
reviewed.

The earlier `tv_federated_agency.md` was invalid. It contrasted a TV query
against KnowledgeParser's mathematical Hyperion artifacts and therefore
returned equation, geometry, and residual language. That output was deleted.

This analysis instead uses a TV-specific sparse evidence graph.

## Sparse Evidence Graph

### Observed Or Implemented Capabilities

| Component | Evidence-bearing capability |
| --- | --- |
| LG ACR | Observes content presented at the television glass and feeds advertising analytics. |
| HbbTV Targeted Advertising | Provides a fast media-switch mechanism for bounded broadcast/broadband intervals. |
| User patent | Asserted to detect and replace an advertising interval. Exact scope is unverified. |
| PicoClaw | Interprets a human request and composes a tool plan. |
| nano-os-agent | Executes bounded tasks and validates or promotes executable skills. |
| Personalized model pattern | Maintains a local model that can adapt a global prior to one field or household. |

Sources:

- LG ACR: <https://lgads.tv/press_release/lg-ads-partners-with-akkio-to-unlock-real-time-intelligence/>
- LG Agentiv: <https://lgads.tv/press_release/lg-ad-solutions-introduces-agentiv/>
- HbbTV Targeted Advertising: <https://www.hbbtv.org/resource-library/specifications/>
- PicoClaw skill lifecycle: `README.md`

### Missing Composition

The patent can create a precisely bounded, replaceable interval. PicoClaw can
interpret a human goal. nano-os-agent can execute a physical or digital task.
A personalized model can select an action for the current operational state.

The sparse gap is the absent connection:

```text
replaceable advertising interval
  -> private human goal
  -> personalized action selection
  -> agent execution
  -> deterministic return to programme
```

That gap defines one concrete application.

## Concrete Application: Attention Dividend

Every detected advertising break becomes a short, user-owned agent session.
The interval is not sold to another advertiser. It is returned to the viewer
as useful time.

```text
detect ad start
  -> estimate the reliable replacement window
  -> classify the current operational human state
  -> select zero or one useful action
  -> let PicoClaw compose the interaction
  -> let nano-os-agent execute the task
  -> restore the programme with a deterministic guard
  -> update the private personalized model
```

### Example

```text
20:43:00  A 120-second advertising break begins.
20:43:01  The receiver switches to the local Attention Dividend session.
20:43:02  The board asks: "Tomorrow starts with rain. Move the garden task?"
20:43:07  The viewer confirms with the remote.
20:43:08  nano-os-agent updates the task and verifies the result.
20:43:10  A quiet programme countdown replaces further prompts.
20:44:59  The deterministic return guard prepares the original stream.
20:45:00  The programme resumes.
```

The application is not a dashboard displayed during advertisements. Its output
may be an executed action. The television becomes an interface to the viewer's
own agent at a moment that was previously claimed by the attention market.

## Operational Human States

The model must not claim to infer emotions, personality, identity, or private
intent. It estimates only measurable operational states:

```text
immersed: do not interrupt; show silence or a countdown
available: one short confirmation is acceptable
interrupted: prepare a programme recap
needs_assistance: offer an accessibility correction
urgent_local_event: show a time-critical household or safety event
inactive: perform an already authorized task without prompting
unknown: remain quiet
```

Signals can include remote-control events, volume or subtitle changes, explicit
voice commands, pending local tasks, break duration, device state, and optional
locally processed sensors. Camera and microphone inference must be opt-in and
must not export raw recordings.

## Personalized Model

The household model should be small and explicit, following the separation
used by personalized Goidanich models:

```text
global safe prior
  + private household feedback
  + local device capability profile
  = household attention policy
```

Example artifact:

```text
attention_policy_<household_uuid>.json
```

Inputs:

- break duration and confidence;
- time and programme context;
- recent remote, volume, subtitle, and dismissal events;
- pending user-authorized tasks;
- connected-sensor events;
- previous acceptance, completion, dismissal, and rollback outcomes.

Outputs:

```text
quiet
one_confirmation
execute_authorized_task
recap
accessibility_assist
urgent_local_alert
```

Optimization objective:

```text
maximize completed useful actions and uninterrupted viewing
minimize prompts, dismissals, false ad boundaries, and return failures
```

The default for an untrained household model is `quiet`, not a fabricated
personalized preference.

## What The Federation Learns

The federation learns transferable action rules, not household histories:

- which intervention class works for a measurable operational state;
- how much interaction fits reliably into each break duration;
- which prompts cause immediate dismissal;
- which hardware and firmware can execute a skill;
- switch timing, buffering, decoder compatibility, and return latency;
- failure signatures and mandatory rollback conditions;
- whether a new skill works on unseen boards and contexts.

The shared unit is an evidence-bearing skill package:

```json
{
  "skill": "attention_dividend_one_confirmation",
  "state": "available",
  "maximum_prompts": 1,
  "minimum_window_seconds": 30,
  "capability_requirements": ["receiver_switch", "remote_input"],
  "success_metrics": ["completed", "not_dismissed", "clean_return"],
  "rollback_timeout_ms": 500
}
```

Raw media, household event history, voice recordings, and personal task text
remain local. If model updates are shared, secure aggregation and leakage tests
are required; federated learning alone is not a privacy guarantee.

## Skill Promotion

```text
local draft
  -> local shadow execution
  -> explicit or behavioural outcome
  -> anonymous peer shadow validation
  -> signed canary skill
  -> compatible-board deployment
  -> drift monitoring and revocation
```

The LLM may interpret goals and compose language, but it must not control media
switch timing, safety thresholds, or programme restoration. Those remain
deterministic board functions.

## Relation To The Patent

The patent is not merely an ad classifier in this application. Subject to its
actual claims, it provides the temporal intervention primitive:

```text
identify a replaceable interval
  -> substitute a local presentation
  -> return at the correct boundary
```

Attention Dividend supplies the missing content and control policy for that
interval. The replacement is a private agent session rather than another ad.

The patent does not automatically cover personalized state models, federated
skill validation, or agent-executed actions. Those elements require a separate
claim analysis and may define additional patentable subject matter.

## Falsifiable Pilot

A first pilot should use consenting test households and three modes:

1. Shadow: detect breaks and propose actions without changing the display.
2. Quiet replacement: replace validated breaks with a countdown only.
3. Agent action: allow at most one user-authorized interaction per break.

Primary endpoints:

- ad start/end boundary error;
- false replacement seconds per viewing hour;
- clean programme-return rate;
- prompt dismissal rate;
- useful-task completion rate;
- improvement of personalized policy over the quiet baseline;
- transfer of promoted skills to unseen boards;
- raw personal media exported: zero.

The application is falsified as a useful agent system if personalized action
does not improve task completion over quiet replacement, if viewers dismiss it,
or if return failures cannot be reduced to an acceptable deterministic bound.
