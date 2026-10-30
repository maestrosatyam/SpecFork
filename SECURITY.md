# Security Policy

SpecFork runs code written by a language model from a spec written by an untrusted user. We take the
isolation of that code, and the protection of API keys and the inference budget, seriously. The design,
threat model and the automated checks behind each control are documented in
[`docs/SECURITY.md`](docs/SECURITY.md).

## Supported versions

| Version | Supported |
|---|---|
| `main` (latest commit) | Yes |
| Latest `0.x` release | Yes |
| Older releases | No; please upgrade |

Fixes are released as a new patch version and noted in [CHANGELOG.md](CHANGELOG.md).

## Reporting a vulnerability

**Please do not open a public issue, pull request or discussion for security problems.**

Report privately through GitHub's private vulnerability reporting:

**<https://github.com/maestrosatyam/SpecFork/security/advisories/new>**

If that is not possible for you, contact the maintainer, Satyam Dwivedi, via GitHub
([@maestrosatyam](https://github.com/maestrosatyam)) and ask for a private channel; do not include
details in a public message.

A useful report includes:

- the affected version or commit, and the deployment mode (local, Docker, hosted);
- a minimal spec, generated code snippet or HTTP request that reproduces the issue;
- what an attacker gains (for example: reads a file, reaches the network, reads `NEBIUS_API_KEY`,
  exhausts the spend cap, affects another user's run);
- any suggested fix.

Please test only against your own local instance. Do not run exploits against the public demo or
attempt to access other users' data; a local `make dev` or `docker build` reproduces the production
sandbox.

## What to expect

| Step | Target |
|---|---|
| Acknowledgement of your report | within 3 business days |
| Initial assessment (validity, severity) | within 7 days |
| Fix or mitigation for critical issues (sandbox escape, secret exposure) | within 14 days |
| Fix for other confirmed issues | within 90 days |

We will keep you informed of progress, coordinate the disclosure date with you, and credit you in the
advisory and changelog unless you prefer to stay anonymous. This is a volunteer-maintained project, so
targets are best effort; we do not run a paid bug bounty.

## Scope

In scope, and **highly valued**:

- **Sandbox escapes**: generated code that bypasses the static allow-list or the runtime isolation to
  read or write files, reach the network, spawn processes, inspect frames or the parent process, or
  otherwise act outside the sandbox.
- Exposure of secrets (API keys, environment variables) to generated code, logs, the UI or API responses.
- Bypassing the per-visitor rate limit or the global spend cap.
- Cross-user access to runs, results or answers.
- XSS or injection through model output or user input in the web UI.
- Denial of service against a single instance with a small number of requests (resource exhaustion that
  escapes the configured limits).

Out of scope:

- Prompt injection that only changes the *content* of model output (questions, explanations, the
  clarified spec) without escaping the sandbox or leaking data. Model output is treated as untrusted
  by design.
- Volumetric denial of service, or attacks requiring a compromised host or malicious dependencies
  outside this repository.
- Missing hardening that has no demonstrated impact (for example a header that is absent but not
  exploitable).
- Issues in third-party model providers or their APIs; please report those to the provider.

Security-sensitive changes to SpecFork must come with regression tests (see
[CONTRIBUTING.md](CONTRIBUTING.md#sandbox-and-security-sensitive-changes)).
