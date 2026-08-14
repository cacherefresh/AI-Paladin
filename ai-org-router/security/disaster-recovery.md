# Disaster recovery & business continuity

Extends the backup line in `sandbox.md` ("periodic immutable append-only
backups on a machine agents cannot reach") into the multi-site posture
enterprise buyers actually ask for during diligence.

## Objective

| Target | Value |
|---|---|
| RPO — maximum tolerable data loss | **15 minutes** |
| Replication sites | **two**, in different grid and weather regions (e.g. Baltimore and Chicago) |
| Backup mutability | append-only; a compromised node cannot rewrite history |
| Verification | scheduled restore drills, not just successful-copy alerts |

Two sites roughly 700 miles apart is a deliberate choice, not a round number:
different power grids, different weather systems, different FEMA regions. A
correlated failure that takes both out is a national event, not an outage.

## What replicates

| Asset | Why it must survive |
|---|---|
| `brain/` — codebase memory & vault | The accumulated context that makes the local tier better than a hosted model. Most expensive thing to rebuild. |
| Audit sinks — `logs/*.jsonl` | The evidence trail. A containment guarantee you cannot *prove* after an incident is worth very little. |
| `router/keywords.yaml`, `policy.yaml` | The gate itself. Restoring compute without restoring the rules restores an *ungated* system. |
| Model artifacts & versions | So a restored node runs the same model that produced the logged decisions. |

Restore order matters and is the opposite of intuition: **rules first, then
audit, then memory, then compute.** A node that comes back before its gate does
is a node with no perimeter.

## The consequence specific to this product

**Replication is egress.** Shipping protected IP between Baltimore and Chicago
every fifteen minutes is, by definition, protected material crossing a network.
It would be incoherent to gate a 285-byte code snippet on its way to a model
and wave through a full repository copy on its way to a second site.

So replication is held to the same discipline as any other egress:

- Encrypted in transit and at rest, over private links — never the open internet.
- **Logged to the same audit topics** as every other decision, so a replication
  event is as visible as an approved BIG-AI call.
- Destination sites are declared infrastructure in policy, not ambient trust.
  An undeclared replication target is treated as exfiltration.

## Relationship to the ransomware rules

`monitors/behavioral_rules.yaml` already detects the attack (mass-file-touch,
extension-rewrite-spread, backup-tamper). Detection without recovery is half a
control. Immutable, off-node, multi-site copies are the other half: the reason
an operator can refuse to pay is that fifteen minutes ago there was a clean
copy in another state that the compromised node had no authority to alter.

## Provenance

This posture is not theoretical for us. The founder ran continuity and recovery
operations of exactly this shape for many years at **Euler Hermes**, a global
trade-credit insurer — an environment where the tolerance for lost financial
records is measured in minutes and the recovery plan is audited rather than
assumed.
