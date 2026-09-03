#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import compileall
import json
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

import yaml

PLACEHOLDER_RE = re.compile(r"\[\[[A-Z0-9_]+\]\]")
EXPECTED_VERSION = "0.6.6"
EXPECTED_MARP_VERSION = "4.5.0"


class UniqueKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping(
    loader: UniqueKeyLoader, node: yaml.MappingNode, deep: bool = False
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in mapping:
            raise ValueError(
                f"duplicate YAML key {key!r} at line {key_node.start_mark.line + 1}"
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping,
)


def _filled_template_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        "[[CONTENT_UNITS_YAML]]",
        '  - id: "u01"\n    title: "Example unit"\n    meeting_number: 1\n'
        '    global_meeting_number: 1\n    deck_local_ordinal: 1\n'
        '    meeting_label: "第 1 节课"\n    organization_basis: "course_meeting"\n'
        '    source: "sections/u01/section.md"',
    )
    text = text.replace("[[MCQ_ENABLED]]", "true")
    return PLACEHOLDER_RE.sub("example", text)


def _require_paths(root: Path, paths: list[str], errors: list[str]) -> None:
    for relative in paths:
        if not (root / relative).exists():
            errors.append(f"required path is missing: {relative}")


def _expect(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def _semantic_checks(root: Path, errors: list[str]) -> None:
    pyproject = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    project_version = str(pyproject.get("project", {}).get("version"))
    _expect(
        project_version == EXPECTED_VERSION,
        f"pyproject version is {project_version!r}, expected {EXPECTED_VERSION!r}",
        errors,
    )

    package = json.loads((root / "package.json").read_text(encoding="utf-8"))
    _expect(
        str(package.get("version")) == EXPECTED_VERSION,
        f"package.json version does not match v{EXPECTED_VERSION}",
        errors,
    )
    marp_version = package.get("devDependencies", {}).get("@marp-team/marp-cli")
    _expect(
        marp_version == EXPECTED_MARP_VERSION,
        f"Marp CLI must be exactly pinned to {EXPECTED_MARP_VERSION}",
        errors,
    )

    toolchain = yaml.safe_load((root / "TOOLCHAIN-LOCK.yaml").read_text(encoding="utf-8"))
    _expect(
        toolchain.get("marp")
        == {
            "package": "@marp-team/marp-cli",
            "version": EXPECTED_MARP_VERSION,
            "install_policy": "exact_pinned_version",
        },
        "TOOLCHAIN-LOCK.yaml does not contain the exact Marp 4.5.0 policy",
        errors,
    )
    _expect(
        toolchain.get("inspection", {}).get("smoke_fixture_slides") == 3
        and toolchain.get("inspection", {}).get("require_success_before_production") is True,
        "TOOLCHAIN-LOCK.yaml must require a three-slide pre-production smoke test",
        errors,
    )

    model_policy = yaml.safe_load((root / "MODEL-POLICY.yaml").read_text(encoding="utf-8"))
    _expect(
        model_policy.get("selection_scope") == "task"
        and model_policy.get("task_runtime_profile") == "TASK-RUNTIME-PROFILE.yaml"
        and model_policy.get("agent_may_select_or_modify_runtime") is False,
        "MODEL-POLICY.yaml must be validation-only and delegate selection to the task profile",
        errors,
    )

    runtime_template = yaml.safe_load(
        (root / "templates/policies/TASK-RUNTIME-PROFILE.template.yaml").read_text(
            encoding="utf-8"
        )
    )
    _expect(
        runtime_template.get("defaults")
        == {
            "planner": {"model": "gpt-5.6-sol", "reasoning_effort": "high"},
            "author": {"model": "gpt-5.6-sol", "reasoning_effort": "medium"},
            "reviewer": {"model": "gpt-5.6-sol", "reasoning_effort": "low"},
        },
        "task runtime template defaults must be planner high, author medium, reviewer low",
        errors,
    )
    _expect(
        runtime_template.get("selection_scope") == "task"
        and runtime_template.get("immutable_after_task_confirmation") is True
        and runtime_template.get("runtime_changes_during_task") == "forbidden",
        "task runtime template must be task-scoped and immutable after confirmation",
        errors,
    )

    collector_template = yaml.safe_load(
        (root / "templates/policies/TOKEN-COLLECTOR-POLICY.template.yaml").read_text(
            encoding="utf-8"
        )
    )
    _expect(
        collector_template.get("required_before_production") is True
        and collector_template.get("unknown_values_remain_null") is True,
        "token collector must be a production gate and preserve unknown values as null",
        errors,
    )

    codex = tomllib.loads((root / ".codex/config.toml").read_text(encoding="utf-8"))
    _expect(
        "model" not in codex and "model_reasoning_effort" not in codex,
        ".codex/config.toml must not hard-code planner runtime",
        errors,
    )
    agents = codex.get("agents", {})
    _expect(
        "default_subagent_model" not in agents
        and "default_subagent_reasoning_effort" not in agents,
        ".codex/config.toml must not hard-code subagent runtime",
        errors,
    )

    for path in sorted((root / ".codex/agents").glob("*.toml")):
        value = tomllib.loads(path.read_text(encoding="utf-8"))
        _expect(
            "model" not in value and "model_reasoning_effort" not in value,
            f"runtime must be task-local rather than hard-coded in {path.relative_to(root)}",
            errors,
        )

    required = [
        # Core v0.6.0 control plane plus the v0.6.1 runtime/token increment.
        "src/mpres/runtime_profile.py",
        "src/mpres/production_profiles.py",
        "src/mpres/control_jobs.py",
        "src/mpres/transactions.py",
        "src/mpres/scheduling.py",
        "src/mpres/assignments.py",
        "src/mpres/context_packets.py",
        "src/mpres/toolchain.py",
        "src/mpres/engine_incidents.py",
        "src/mpres/log_daemon.py",
        "src/mpres/review.py",
        "src/mpres/revision_routing.py",
        "src/mpres/maintenance.py",
        "src/mpres/diagnostics.py",
        # New roles.
        ".codex/agents/delegated-planner.toml",
        ".codex/agents/deck-revision-author.toml",
        ".codex/agents/diagnostic-reviewer.toml",
        # New skills.
        ".agents/skills/courseware-production-profiling/SKILL.md",
        ".agents/skills/legacy-presentation-migration/SKILL.md",
        ".agents/skills/critical-path-production-scheduling/SKILL.md",
        ".agents/skills/context-packet-compilation/SKILL.md",
        ".agents/skills/workflow-engine-maintenance/SKILL.md",
        ".agents/skills/deck-revision-authoring/SKILL.md",
        ".agents/skills/role-runtime-profiling/SKILL.md",
        ".agents/skills/transactional-workflow-state/SKILL.md",
        ".agents/skills/operational-incident-mitigation/SKILL.md",
        ".agents/skills/presentation-defect-triage/SKILL.md",
        # Canonical structured records.
        "templates/structured/PRODUCTION-PROFILE.template.yaml",
        "templates/structured/REVIEW-AGGREGATION-JOB.template.yaml",
        "templates/structured/RELEASE-JOB.template.yaml",
        "templates/structured/BATCH-ASSIGNMENT-PLAN.template.yaml",
        "templates/structured/PRESENTATION-WORK-PLAN.template.yaml",
        "templates/structured/UNIT-DELTA.template.yaml",
        "templates/structured/UNIT-CONTEXT-PACKET.template.yaml",
        "templates/structured/AUTHOR-CONTEXT-PACKET.template.yaml",
        "templates/structured/INTERACTION-RECORD.template.yaml",
        "templates/structured/REVIEW-PLAN.template.yaml",
        "templates/structured/ENGINE-INCIDENT.template.yaml",
        "templates/structured/INCIDENT-INDEX.template.yaml",
        "templates/structured/INCIDENT-OCCURRENCE.template.yaml",
        "templates/structured/OPERATIONAL-WORKAROUND.template.yaml",
        "templates/structured/DIAGNOSTIC-CASE.template.yaml",
        "templates/structured/DIAGNOSTIC-RESULT.template.yaml",
        "templates/structured/PATCH-SCOPE.template.yaml",
        "templates/structured/PERFORMANCE-BUDGET.template.yaml",
        "templates/structured/MILESTONE-CHECKPOINT.template.json",
        "templates/structured/TOOLCHAIN-LOCK.template.yaml",
        "templates/policies/TASK-RUNTIME-PROFILE.template.yaml",
        "docs/MIGRATION-v0.6.3-to-v0.6.4.md",
        "docs/MIGRATION-v0.6.4-to-v0.6.5.md",
        "docs/MIGRATION-v0.6.5-to-v0.6.6.md",
        "tests/test_v064_transactional_state.py",
        "tests/test_v065_incident_circuit.py",
        "tests/test_v066_slide_subset_diagnostics.py",
        # Profile-specific stages and assignments.
        "templates/stages/STAGE-M01-BASELINE-AUDIT.template.md",
        "templates/stages/STAGE-M02-DELTA-DESIGN-PATCH.template.md",
        "templates/stages/STAGE-M03-INTEGRATION-SEMANTIC-CHECK.template.md",
        "templates/assignments/TASK-deck-revision-author.template.md",
        "templates/assignments/TASK-diagnostic-reviewer.template.md",
        # Retained inspection and maintenance gates.
        ".agents/skills/mathematical-typesetting-inspection/SKILL.md",
        ".agents/skills/presentation-corrective-maintenance/SKILL.md",
        "templates/structured/COURSE-TERMINOLOGY.template.yaml",
        "templates/structured/COURSE-SEMANTIC-OBJECTS.template.yaml",
        "templates/structured/CROSS-DECK-HANDOFFS.template.yaml",
        "templates/structured/PRESENTATION-CONTINUITY-MAP.template.yaml",
        "templates/structured/SLIDE-DENSITY-AUDIT.template.yaml",
        "templates/structured/MATH-SOURCE-INVENTORY.template.json",
        "templates/structured/MATH-RENDERER-PROBE.template.json",
    ]
    _require_paths(root, required, errors)

    forbidden_paths = [
        ".codex/agents/review-coordinator.toml",
        ".codex/agents/release-coordinator.toml",
        "templates/assignments/TASK-review-coordinator.template.md",
        "templates/assignments/TASK-release-coordinator.template.md",
        "templates/structured/LEGACY-MARP-AUDIT.template.md",
        "templates/structured/LEGACY-REUSE-MAP.template.md",
        "templates/structured/UNIT-INTERACTION-MANIFEST.template.yaml",
        "templates/structured/UNIT-MCQ-AUDIT.template.yaml",
        "tests/test_v050_features.py",
    ]
    for relative in forbidden_paths:
        if (root / relative).exists():
            errors.append(f"obsolete or forbidden path must be removed: {relative}")

    production_source = (root / "src/mpres/production.py").read_text(encoding="utf-8")
    runtime_source = (root / "src/mpres/runtime_profile.py").read_text(encoding="utf-8")
    for role in ("review-coordinator", "release-coordinator"):
        _expect(
            f'"{role}"' not in production_source and f'"{role}"' not in runtime_source,
            f"{role} must not remain an executable model role",
            errors,
        )
    control_source = (root / "src/mpres/control_jobs.py").read_text(encoding="utf-8")
    _expect(
        'model_runtime": None' in control_source
        and "prepare_review_aggregation_job" in control_source
        and "prepare_release_job" in control_source,
        "review aggregation and release must be runtime-free control-plane jobs",
        errors,
    )

    # Exact direct dependency plus explicit repository lock is the selected npm policy.
    if (root / "package-lock.json").exists():
        errors.append("package-lock.json is excluded by this repository's explicit lock-file policy")
    if list((root / "templates").rglob("STAGE-ASSIGNMENT*")):
        errors.append("stage-specific assignment templates are forbidden")
    if list(root.rglob("MATH-PDF-EVIDENCE*")):
        errors.append("MATH-PDF-EVIDENCE artifacts/templates are forbidden")

    for filename in ("recovery.py", "engine_migration.py", "workflow_freeze.py"):
        if (root / "src/mpres" / filename).exists():
            errors.append(f"forbidden heavyweight subsystem module exists: src/mpres/{filename}")

    logs_source = (root / "src/mpres/logs.py").read_text(encoding="utf-8")
    daemon_source = (root / "src/mpres/log_daemon.py").read_text(encoding="utf-8")
    _expect(
        "project_log_path" in logs_source and "submit_log_record" in logs_source,
        "logs.py must submit production logs to the single project log daemon",
        errors,
    )
    _expect(
        '"daemon_sequence"' in daemon_source and "project_log_path" in daemon_source,
        "log daemon is missing serialized project-log sequencing",
        errors,
    )

    profile_source = (root / "src/mpres/production_profiles.py").read_text(encoding="utf-8")
    for stage_id in (
        "m01_baseline_audit",
        "m02_delta_design_patch",
        "m03_integration_semantic_check",
    ):
        _expect(stage_id in profile_source, f"migration profile is missing {stage_id}", errors)
    _expect(
        "MIGRATION_STAGES" in profile_source and "COURSE_FULL_STAGES" in profile_source,
        "production profile module does not separate migration and greenfield stage graphs",
        errors,
    )

    execution = yaml.safe_load(
        (root / "templates/policies/EXECUTION-POLICY.template.yaml").read_text(encoding="utf-8")
    )
    _expect(
        execution.get("planner_delegation", {}).get("main_agent_exclusive")
        == ["write_or_revise_TASK_md"]
        and execution.get("planner_delegation", {}).get(
            "all_other_planner_operations_may_be_delegated"
        )
        is True,
        "execution policy must reserve only TASK.md authorship to the main agent",
        errors,
    )
    _expect(
        execution.get("authoring", {}).get("one_fixed_author_per_lesson") is True
        and execution.get("authoring", {}).get("lazy_unit_initialization") is True
        and execution.get("authoring", {}).get("post_review_revision_role")
        == "deck-revision-author",
        "execution policy does not encode fixed lesson authors, lazy init, and deck-level revision",
        errors,
    )
    _expect(
        execution.get("review", {}).get("each_reviewer_reads_entire_frozen_deck") is True
        and execution.get("review", {}).get("launch_only_after_freeze") is True,
        "all five reviewers must launch after freeze and read the entire deck",
        errors,
    )
    _expect(
        execution.get("engine_changes", {}).get("in_task_hot_patch") == "forbidden"
        and execution.get("engine_changes", {}).get(
            "technical_bug_requires_task_policy_amendment"
        )
        is True,
        "workflow-engine technical bugs must require a task policy amendment",
        errors,
    )
    engine_policy = execution.get("engine_changes", {})
    _expect(
        engine_policy.get("incident_recurrence_key") == "incident_id"
        and engine_policy.get("deterministic_recurrence_threshold") == 2
        and engine_policy.get("circuit_breaker_scope") == "task_production",
        "execution policy must define stable incident recurrence and a task-production circuit",
        errors,
    )
    workaround_policy = engine_policy.get("operational_workaround", {})
    _expect(
        workaround_policy.get("approval") == "exact_plan_via_TASK_reconfirmation"
        and workaround_policy.get("agent_may_invent_or_modify") is False
        and workaround_policy.get("control_plane_executes_arbitrary_commands") is False,
        "operational workaround policy must be exact, user-confirmed, and non-dynamic",
        errors,
    )
    _expect(
        execution.get("marp", {}).get("version") == EXPECTED_MARP_VERSION
        and execution.get("marp", {}).get("version_policy") == "exact_pinned_version",
        "execution policy must use exact Marp 4.5.0",
        errors,
    )

    work_plan = yaml.safe_load(
        (root / "templates/structured/PRESENTATION-WORK-PLAN.template.yaml").read_text(
            encoding="utf-8"
        )
    )
    _expect(
        work_plan.get("policy", {}).get("priority_order")
        == [
            "finish_current_review_revision_or_release",
            "finish_current_presentation",
            "start_next_ready_presentation",
            "prepare_future_metadata_without_model_workers",
        ],
        "PRESENTATION-WORK-PLAN priority order is inconsistent with scheduling.py",
        errors,
    )
    _expect(
        work_plan.get("policy", {}).get("next_authoring_overlap_current_statuses")
        == [
            "authoring",
            "review_requested",
            "reviewing",
            "author_revision",
            "release_ready",
        ],
        "PRESENTATION-WORK-PLAN must preserve the next lane through review/revision/release",
        errors,
    )
    transaction_source = (root / "src/mpres/transactions.py").read_text(encoding="utf-8")
    state_source = (root / "src/mpres/state.py").read_text(encoding="utf-8")
    thread_source = (root / "src/mpres/threads.py").read_text(encoding="utf-8")
    _expect(
        "BEGIN IMMEDIATE" in transaction_source
        and "mutable_documents" in transaction_source
        and "ConcurrentStateUpdateError" in transaction_source
        and "_flush_projections" in transaction_source,
        "v0.6.4 transactional store is missing writer serialization, revisions, or projections",
        errors,
    )
    _expect(
        "STATE_REVISION_FIELD" in state_source
        and "initialize_document" in state_source
        and "save_document" in state_source,
        "task state is not connected to the v0.6.4 transactional document store",
        errors,
    )
    registry_template = yaml.safe_load(
        (root / "templates/structured/THREAD-REGISTRY.template.yaml").read_text(
            encoding="utf-8"
        )
    )
    _expect(
        registry_template.get("registry_revision") == 0
        and "REGISTRY_REVISION_FIELD" in thread_source
        and "transactional_task_mutation" in thread_source,
        "thread registry is not revisioned and transaction-protected",
        errors,
    )

    # Every source-level call that commits canonical task state must be owned by
    # a transaction boundary. State.py contains the implementation itself and is
    # intentionally excluded from this caller scan.
    for source_path in sorted((root / "src/mpres").glob("*.py")):
        if source_path.name == "state.py":
            continue
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        parents: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            called = node.func.id if isinstance(node.func, ast.Name) else None
            if called != "save_state":
                continue
            current: ast.AST | None = node
            owner: ast.FunctionDef | ast.AsyncFunctionDef | None = None
            while current in parents:
                current = parents[current]
                if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    owner = current
                    break
            decorators = {
                decorator.id
                for decorator in (owner.decorator_list if owner else [])
                if isinstance(decorator, ast.Name)
            }
            _expect(
                owner is not None and "transactional_task_mutation" in decorators,
                f"{source_path.relative_to(root)}:{node.lineno} saves task state outside the transaction boundary",
                errors,
            )

    scheduling_source = (root / "src/mpres/scheduling.py").read_text(encoding="utf-8")
    review_source = (root / "src/mpres/review.py").read_text(encoding="utf-8")
    _expect(
        "current_allows_next_authoring" in scheduling_source
        and "refresh_active_presentation_window" in scheduling_source
        and "refresh_active_presentation_window(root, slug, state)" in review_source,
        "v0.6.3 current-plus-next transition refresh is missing",
        errors,
    )

    diagnostic_source = (root / "src/mpres/diagnostics.py").read_text(encoding="utf-8")
    diagnostic_assignment = (root / "templates/assignments/TASK-diagnostic-reviewer.template.md").read_text(encoding="utf-8")
    _expect(
        '"diagnostic-reviewer": "reviewer"' in runtime_source
        and 'agent_may_change": False' in diagnostic_source,
        "diagnostic reviewer must use the fixed reviewer-family task runtime",
        errors,
    )
    _expect(
        "MAX_TARGET_SLIDES = 8" in diagnostic_source
        and "MAX_NEIGHBOR_RADIUS = 2" in diagnostic_source
        and "MAX_INCLUDED_SLIDES = 20" in diagnostic_source
        and "source_modified" in diagnostic_source
        and "automatic_source_edit" in diagnostic_source,
        "bounded read-only diagnostic limits or no-edit controls are missing",
        errors,
    )
    _expect(
        "no PDF opening" in diagnostic_assignment
        or "Do not render or open any PDF" in diagnostic_assignment,
        "diagnostic assignment must explicitly forbid PDF access",
        errors,
    )
    _expect(
        '"diagnostic"' in logs_source,
        "diagnostic events must be accepted by the project log schema",
        errors,
    )

    cli_source = (root / "src/mpres/cli.py").read_text(encoding="utf-8")
    for command in (
        "log-daemon",
        "maintenance",
        "production",
        "toolchain",
        "engine",
        "diagnostic",
    ):
        _expect(
            f'commands.add_parser("{command}")' in cli_source
            or f'commands.add_parser(\n        "{command}"' in cli_source,
            f"CLI does not expose {command}",
            errors,
        )
    _expect(
        '"transaction-status"' in cli_source and "mutable_state_status" in cli_source,
        "CLI must expose task transaction-status for the v0.6.4 store",
        errors,
    )
    _expect('commands.add_parser("recover")' not in cli_source, "recovery CLI is out of scope", errors)

    for path in (root / ".codex/agents").glob("*.toml"):
        if path.stem in {"worker1", "worker2"}:
            errors.append(f"numbered worker role is forbidden: {path.name}")

    stale_files = [
        root / "AGENTS.md",
        root / "README.md",
        root / "docs/WORKFLOW.md",
        root / "docs/DESIGN-NOTES.md",
        root / "docs/VALIDATION.md",
        root / "templates/TASK.template.md",
        root / "templates/policies/WORKER-PROMPT-PREAMBLE.template.md",
    ]
    for path in stale_files:
        text = path.read_text(encoding="utf-8")
        lowered = text.lower()
        _expect(
            "v0.5.0" not in lowered and "0.5.0" not in lowered,
            f"stale v0.5.0 policy text remains in {path.relative_to(root)}",
            errors,
        )
        for phrase in (
            "planner personally writes every exact assignment",
            "every exact worker assignment is written by the main planner",
            "personally writes and approves every",
            "unpinned_latest_at_install_time",
            "latest-at-install",
        ):
            _expect(
                phrase not in lowered,
                f"stale policy phrase {phrase!r} remains in {path.relative_to(root)}",
                errors,
            )


def _run_command(command: list[str], *, root: Path, timeout: int = 180) -> tuple[int, str]:
    try:
        result = subprocess.run(
            command,
            cwd=root,
            env={
                **os.environ,
                "PYTHONPATH": str(root / "src"),
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            },
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return 124, f"timed out after {timeout}s\n{stdout}{stderr}"
    return result.returncode, result.stdout + result.stderr


def validate(root: Path, *, run_tests: bool) -> list[str]:
    errors: list[str] = []
    ignored_parts = {
        ".git",
        ".venv",
        "node_modules",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "tasks",
    }

    for path in sorted(root.rglob("*.toml")):
        if any(part in ignored_parts for part in path.parts):
            continue
        try:
            with path.open("rb") as handle:
                tomllib.load(handle)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"TOML {path.relative_to(root)}: {exc}")

    for path in sorted(root.rglob("*.json")):
        if any(part in ignored_parts for part in path.parts):
            continue
        try:
            json.loads(_filled_template_text(path))
        except Exception as exc:  # noqa: BLE001
            errors.append(f"JSON {path.relative_to(root)}: {exc}")

    for path in sorted(root.rglob("*.yaml")):
        if any(part in ignored_parts for part in path.parts):
            continue
        try:
            yaml.load(_filled_template_text(path), Loader=UniqueKeyLoader)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"YAML {path.relative_to(root)}: {exc}")

    for script in (root / "start.sh", root / "start-safe.sh"):
        result = subprocess.run(
            ["bash", "-n", str(script)], capture_output=True, text=True, check=False
        )
        if result.returncode:
            errors.append(f"Shell {script.name}: {result.stderr.strip()}")

    if not compileall.compile_dir(root / "src", quiet=1):
        errors.append("compileall failed for src")
    if not compileall.compile_dir(root / "scripts", quiet=1):
        errors.append("compileall failed for scripts")
    if not compileall.compile_dir(root / "tests", quiet=1):
        errors.append("compileall failed for tests")

    try:
        _semantic_checks(root, errors)
    except Exception as exc:  # noqa: BLE001
        errors.append(f"semantic checks failed: {type(exc).__name__}: {exc}")

    help_commands = [
        [sys.executable, "-m", "mpres", "--help"],
        [sys.executable, "-m", "mpres", "log-daemon", "--help"],
        [sys.executable, "-m", "mpres", "assignment", "--help"],
        [sys.executable, "-m", "mpres", "production", "--help"],
        [sys.executable, "-m", "mpres", "stage", "--help"],
        [sys.executable, "-m", "mpres", "review", "--help"],
        [sys.executable, "-m", "mpres", "maintenance", "--help"],
        [sys.executable, "-m", "mpres", "diagnostic", "--help"],
        [sys.executable, "-m", "mpres", "toolchain", "--help"],
        [sys.executable, "-m", "mpres", "engine", "--help"],
    ]
    for command in help_commands:
        returncode, output = _run_command(command, root=root, timeout=30)
        if returncode:
            errors.append(f"CLI help failed ({' '.join(command[3:]) or 'root'}):\n{output}")

    if run_tests:
        returncode, output = _run_command(
            [sys.executable, "-m", "pytest", "-q"], root=root, timeout=900
        )
        if returncode:
            errors.append("pytest failed:\n" + output)
        else:
            print(output.strip())
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate v0.6.6 configs, templates, policies, CLI, source, and tests."
    )
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    errors = validate(root, run_tests=not args.skip_tests)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print("Project validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
