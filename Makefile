SHELL := /bin/sh
ENV_FILE := .env.local
ENV = set -a; if [ -f "$(ENV_FILE)" ]; then . "./$(ENV_FILE)"; fi; set +a;
COMPOSE_ENV := $(if $(wildcard .env.local),--env-file .env.local,)
CONTAINER_RUNTIME ?= $(shell command -v podman 2>/dev/null || command -v docker 2>/dev/null)
PODMAN_SOCKET := $(patsubst unix://%,%,$(shell podman info --format '{{.Host.RemoteSocket.Path}}' 2>/dev/null))
CONTAINER_SOCKET ?= $(if $(findstring podman,$(notdir $(CONTAINER_RUNTIME))),$(PODMAN_SOCKET),/var/run/docker.sock)
COMPOSE := CONTAINER_SOCKET=$(CONTAINER_SOCKET) $(CONTAINER_RUNTIME) compose $(COMPOSE_ENV)
CDK := npx --yes aws-cdk@2.177.0 --app "uv run --with-requirements infrastructure/cdk/requirements.txt python infrastructure/cdk/app.py"

.PHONY: bootstrap container-runtime-check configure-local-bucket up down format lint typecheck test test-integration test-e2e build infra-synth infra-local infra-deploy ci

bootstrap:
	@$(ENV) uv sync --all-groups
	@$(ENV) pnpm --dir apps/web install --frozen-lockfile

container-runtime-check:
	@test -n "$(CONTAINER_RUNTIME)" || (echo "Neither Podman nor Docker is installed. Install one, or set CONTAINER_RUNTIME to its executable." >&2; exit 127)
	@$(CONTAINER_RUNTIME) compose version >/dev/null
	@test -n "$(CONTAINER_SOCKET)" || (echo "Could not determine the container API socket. Set CONTAINER_SOCKET explicitly." >&2; exit 127)
	@test -f "$(ENV_FILE)" || (echo "Create .env.local from .env.example and set AWS credentials before starting local services." >&2; exit 2)
	@$(ENV) test -n "$$AWS_ACCESS_KEY_ID" && test -n "$$AWS_SECRET_ACCESS_KEY" || (echo "AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are required in .env.local." >&2; exit 2)
	@$(ENV) test -n "$$DYNAMODB_CHAT_TABLE" && test -n "$$DYNAMODB_DOCUMENTS_TABLE" && test -n "$$DOCUMENT_BUCKET" || (echo "DYNAMODB_CHAT_TABLE, DYNAMODB_DOCUMENTS_TABLE, and DOCUMENT_BUCKET are required in .env.local." >&2; exit 2)

configure-local-bucket:
	@$(ENV) test -n "$$DOCUMENT_BUCKET" || (echo "DOCUMENT_BUCKET is required in .env.local." >&2; exit 2)
	@$(ENV) \
		aws s3api put-bucket-cors --bucket "$$DOCUMENT_BUCKET" --cors-configuration file://ops/local-bucket-cors.json \
		|| (echo "Failed to configure S3 CORS. Ensure your AWS principal allows s3:PutBucketCORS on arn:aws:s3:::\"$$DOCUMENT_BUCKET\" (see ops/local-developer-policy.json)." >&2; exit 2)

up: container-runtime-check
	@$(COMPOSE) up -d --build --force-recreate --remove-orphans

down: container-runtime-check
	@$(COMPOSE) down

format:
	@$(ENV) uv run ruff format services tests infrastructure/cdk
	@$(ENV) pnpm --dir apps/web format

lint:
	@$(ENV) uv run ruff check services tests infrastructure/cdk
	@$(ENV) pnpm --dir apps/web lint

typecheck:
	@$(ENV) uv run pyright
	@$(ENV) pnpm --dir apps/web exec tsc -b

test:
	@$(ENV) uv run pytest tests/unit
	@$(ENV) pnpm --dir apps/web test

test-integration:
	@$(ENV) uv run pytest tests/integration

test-e2e:
	@$(ENV) pnpm --dir apps/web exec playwright test

build: container-runtime-check
	@$(ENV) pnpm --dir apps/web build
	@rm -rf infrastructure/lambda-layer/python
	@mkdir -p infrastructure/lambda-layer/python
	@$(CONTAINER_RUNTIME) run --rm --platform linux/arm64 -v "$(CURDIR)/infrastructure/lambda-layer:/asset" public.ecr.aws/lambda/python:3.12 pip install --no-cache-dir -r /asset/requirements.txt -t /asset/python

infra-synth:
	@$(ENV) $(CDK) synth -c stage=$${CDK_STAGE:-dev}

infra-local:
	@$(ENV) $(CDK) synth -c stage=dev

infra-deploy:
	@test -n "$(STAGE)" || (echo "Set STAGE to dev, integration, or prod" >&2; exit 2)
	@$(MAKE) build
	@$(ENV) $(CDK) deploy --all --require-approval never -c stage=$(STAGE)

ci:
	@$(ENV) uv run ruff format --check services tests infrastructure/cdk
	@$(ENV) pnpm --dir apps/web format:check
	@$(MAKE) lint
	@$(MAKE) typecheck
	@$(MAKE) test
	@$(MAKE) build
	@$(MAKE) infra-synth
