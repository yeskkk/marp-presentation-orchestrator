# Security note

`start.sh` and `start.ps1` use `codex --dangerously-bypass-approvals-and-sandbox` because that is the selected operating mode. Run it only inside an external containment boundary: disposable VM/container, dedicated unprivileged account, project-only mounts, and minimal credentials. Read-only review snapshots and role directories prevent ordinary workflow drift but do not constrain a malicious unrestricted process.
