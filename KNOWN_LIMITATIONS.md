# Known Limitations

This repository is a demo harness only. It does not include the parsing kernel, model logic, production service implementation, or SDK source code. The demo can consume the published Python SDK package `chat-vision-sdk==0.1.0`.

- API result quality depends on the configured `CHAT_VISION_API_BASE` endpoint and the service behind it.
- Screen capture is a demo feature for local operator-driven testing, not a supported ingestion primitive for unattended production systems.
- Captured screenshots are temporarily written to the local temp directory for upload and UI preview, then cleared when a new demo starts or the process exits normally.
- Do not expose the local web server to the public internet. If you bind to `0.0.0.0`, use only a trusted LAN and do not configure router port forwarding.
- This harness is not suitable for unattended production automation. It has no production authentication layer, monitoring, persistence guarantees, queueing, retry policy, or operational hardening.
- Boundary statement: no hook, no injection, no protocol reverse engineering, no database reading, and no auto-send.
