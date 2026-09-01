# Review and revision state machine

`authoring → frozen/review_requested → reviewing → author_revision → release_ready → finalized`

The only content-review round is `full`. Five isolated reviewers are created after freeze and each reads the entire frozen deck. Atomic aggregation creates one deck revision author; original lesson authors remain closed. No finding receives a resolved status. The revision author records one response per finding, revises the complete deck, completes the modification checklist, and reruns deterministic gates. Reviewers do not inspect the revision; release is mechanical and starts just in time at `release_ready`.
