# Orynth v2 — developer command wrapper.
#
# Thin wrapper over the reproducible Phase 0 + Phase 1 commands documented in
# COMMANDS.md. Every container step here is an ephemeral `docker run --rm` or a
# compose service — Phase 0/1 never drop you into a long-lived container.
# `make shell` is the one interactive entry point.
#
# Run `make` (or `make help`) for the target list.

COMPOSE := docker compose -f docker/compose.dev.yaml
BASE    := orynth-base:dev
RUN_WS  := docker run --rm -v "$(CURDIR)":/workspace -w /workspace/ros2_ws $(BASE)
PC_VENV := /tmp/orynth-pc-venv

.DEFAULT_GOAL := help
.PHONY: help base build test lint sitl-up sitl-smoke sitl-accept sitl-down shell clean

help: ## List available targets
	@grep -hE '^[a-z][a-z-]*:.*## ' $(MAKEFILE_LIST) | \
	  awk -F':.*## ' '{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

base: ## Build the orynth-base image (amd64)
	docker buildx build --load -f docker/base.Dockerfile -t $(BASE) .

build: base ## colcon build the workspace inside orynth-base
	$(RUN_WS) bash -c 'colcon build --packages-skip swarm_hardware'

test: base ## Unit gate: colcon build + test inside orynth-base
	$(RUN_WS) bash -c 'set -e; \
	  colcon build --packages-skip swarm_hardware; \
	  colcon test --packages-skip swarm_hardware --return-code-on-test-failure; \
	  colcon test-result --verbose'

lint: ## Run pre-commit on all files (PEP 668-safe venv)
	@test -d $(PC_VENV) || python3 -m venv $(PC_VENV)
	@$(PC_VENV)/bin/pip -q install pre-commit==3.7.1
	$(PC_VENV)/bin/pre-commit run --all-files

sitl-up: ## Cold-start the Phase 1 SITL stack (SITL + MAVROS + Foxglove)
	$(COMPOSE) up -d --wait --wait-timeout 300
	@echo "Foxglove bridge ready — connect Studio to ws://localhost:8765"

sitl-smoke: ## Run the Phase 1 SITL smoke test (arm/takeoff/waypoint/land)
	bash scripts/ci/run_sitl_smoke.sh

sitl-accept: ## Run the smoke test and record accept/phase1.mcap
	SMOKE_RECORD=1 bash scripts/ci/run_sitl_smoke.sh

sitl-down: ## Tear down the SITL stack
	$(COMPOSE) down -v --remove-orphans

shell: ## Interactive shell inside orynth-base (workspace mounted)
	docker run --rm -it -v "$(CURDIR)":/workspace -w /workspace/ros2_ws $(BASE) bash

clean: ## Remove colcon build artefacts (via container — no host sudo)
	$(RUN_WS) bash -c 'rm -rf /workspace/ros2_ws/build /workspace/ros2_ws/install /workspace/ros2_ws/log'
