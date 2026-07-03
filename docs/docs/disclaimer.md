---
sidebar_position: 30
---

# Disclaimer & Liability

:::caution Important notice on security and liability
This project is in an **early stage / beta status**. In **`PIPELINE_EXECUTOR=docker`** mode, the orchestrator has indirect access to the Docker daemon (via the recommended socket proxy) – with **improper configuration**, there is a **security risk** to the host system. In **`kubernetes`** mode, runs are decoupled from host Docker; typical K8s concerns apply instead (RBAC, networking, secrets).
:::

## Use at your own risk

The software is provided **"as is"**. The author assumes **no liability** for:

- Hardware damage
- Data loss
- Security vulnerabilities
- Service interruptions

that may arise from the use of this software.

## No warranty

There is **no guarantee** for:

- the **correctness** of the software,
- its **functionality**, or
- its **continuous availability**.

## Security recommendation

- **Never** run this orchestrator **unprotected on the public internet**.
- In Docker mode: **always** use the recommended **Docker socket proxy**; in Kubernetes: grant the orchestrator ServiceAccount **minimal RBAC rights**.
- **Always** use **strong authentication** (OAuth, secure JWT and encryption keys).

Details: [Docker Socket Proxy](/docs/deployment/DOCKER_PROXY), [Setup Guide](/docs/setup) (production checklist), [Deployment](/docs/deployment/PRODUCTION).
