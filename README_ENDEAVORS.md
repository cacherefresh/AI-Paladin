# Endeavors

**This repository is my entry to work for NVIDIA.** It is not affiliated with
or endorsed by NVIDIA.

## The goal

AI-Paladin today enforces its rules inside one process. That proves the
design: protected IP is pinned on-prem, every outbound byte is disclosed or
refused, and an AI agent's web access is limited by HTTP method, not by
asking it nicely. A process can be bypassed by the rest of the machine.

The endeavor is to rebuild the same functionality **at the layers an agent
cannot step around**:

| Layer | Platform | Enforcement point |
|---|---|---|
| Operating system | Ubuntu and other Linux | eBPF - cgroup socket hooks and BPF-LSM - with nftables as the backstop |
| Operating system | BSD and other \*nix | pf / ipfw, with a kernel module where hooks are missing |
| Operating system | Windows | Windows Filtering Platform callout driver plus a service |
| Operating system | macOS | Network Extension content filter plus Endpoint Security |
| Driver / hardware | NIC and DPU | Policy enforced on the network card - e.g. NVIDIA BlueField - outside the host's trust boundary, so a compromised host cannot switch it off |

One policy file, the same everywhere: the keyword and path rules, the four
postures (`sovereign`, `slow`, `fast`, `superfast`), the three internet
settings (LLM, RAG, bot), and the HTTP method classes and switches.

## The principle

A prompt is a suggestion. A hook is a guardrail: advisory today, a tripwire
rather than a boundary. A driver is the foundation a real wall would stand on. Each layer down removes one more thing an agent - or the
person driving it - can talk its way past.

## The prompt

Paste this to an AI coding agent to start the work:

```text
Build an AI firewall that enforces the AI-Paladin policy
(ai-paladin/router/policy.yaml and router/keywords.yaml) below the
application layer. along with all AI-Paladin's intended features and settings.
make it easy for the user to use, understand based on this code base.
we want it as efficient and robust as possible without compromising anything.
ask questions when in doubt, such as programming language to be used, and what
(if any) third party libraries are used. 
and whether 3rd party libraries can be used at all.
if there are components already built that handles a subsection of this program. ask if we should use it, and give your recommendation
as this way we know your thought process while building it. we want to document your decisions, my decisions and at the end we want a report of what we learned should we redo this. that way we can grow.  

Per AI agent process (identified by cgroup, PID tree, or code signature):
1. Pin protected IP on-prem: refuse any connection that would carry a
   protected term or a file under a protected path.
2. Enforce the posture: sovereign = loopback only, DNS included;
   slow/fast/superfast = egress only after a human approves.
3. Enforce internet access: off = no external network; read = HTTP read
   methods only; readwrite = read and write methods. TRACE, CONNECT and
   PRI are never allowed. Use the method classes in
   ai-paladin/ai_paladin/nodes/web_tools.py.
4. Log every allow and deny to an append-only audit log.

HTTPS hides methods and content from a packet filter. Steps 1 and 3 need
the agent's traffic forced through a local proxy that sees the request;
the kernel or driver layer enforces that the agent can reach nothing
else. Say which layer enforces what.

Targets, one at a time, each with tests that prove a blocked connection
never leaves the machine:
- Linux (Ubuntu first): eBPF cgroup/connect hooks plus BPF-LSM, and a
  userspace daemon that loads policy.yaml.
- Windows: a Windows Filtering Platform callout driver.
- macOS: a Network Extension content filter.
- NVIDIA BlueField DPU: the same policy enforced off-host with DOCA.

State each layer's limits plainly. Never call a layer an air gap unless
it is one. Fail closed: if the policy cannot be loaded or verified,
block.
```
