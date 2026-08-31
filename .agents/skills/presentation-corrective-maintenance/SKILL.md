---
name: presentation-corrective-maintenance
description: Reopen a published Marp presentation as a numbered corrective revision without overwriting the historical release.
---

# Corrective maintenance

The planner chooses `targeted_patch` or `full_corrective_review` and personally writes the maintenance assignment.

- `targeted_patch`: change only the approved defect, complete the maintenance checklist and mechanical checks, then publish the numbered revision without specialist review.
- `full_corrective_review`: run one isolated five-channel full review of the maintenance candidate, route findings to the author, complete author-owned revision, rerun all mechanical checks, and publish without reviewer recheck.

Historical deliverables remain unchanged. New output is stored under `deliverables/<id>/revisions/rNNNN/`; `CURRENT-REVISION.json` identifies the current revision. Screenshots, model vision, original-PDF access and finding-resolution fields remain forbidden.
