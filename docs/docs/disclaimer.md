---
sidebar_position: 30
---

# Disclaimer & Liability

:::caution Important notice on security and liability
This project is in an **early stage / beta status**. The orchestrator requires access to the **Docker socket** to execute pipelines. With **improper configuration**, there is a **security risk** to the host system.
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
- **Always** use the recommended **Docker socket proxy** and **strong authentication** (OAuth, secure JWT and encryption keys).

Details: [Docker Socket Proxy](/docs/deployment/DOCKER_PROXY), [Setup Guide](/docs/setup) (production checklist), [Deployment](/docs/deployment/PRODUCTION).
