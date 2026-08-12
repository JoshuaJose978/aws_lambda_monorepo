# Build Specification

Build a private-document RAG chatbot. This document is the implementation contract. Do not add product features, service alternatives, compatibility layers, or infrastructure not listed here.

## Fixed Decisions

| Area | Choice |
| --- | --- |
| Frontend | React, TypeScript, Vite, AWS Amplify Hosting |
| Authentication | Cognito User Pool and Hosted UI; email/password plus Google OIDC federation |
| API | API Gateway HTTP API with Cognito JWT authorizer; Python 3.12 Lambda zip functions |
| Chat model and embeddings | Amazon Bedrock behind internal provider interfaces; deterministic fakes in tests/local mode |
| Documents | Direct browser-to-S3 presigned uploads; PDF, DOCX, Markdown, and text only |
| Ingestion | S3 event to SQS to a Python Lambda worker; SQS DLQ; idempotent processing |
| Chat state | DynamoDB |
| Retrieval | DynamoDB native vector search, owner-partitioned on the document table |
| Infrastructure | AWS CDK v2 in Python |
| Local services | Compose specification compatible with Docker Compose and Podman Compose: LocalStack, API, Vite frontend, Keycloak, optional Jenkins profile |
| Tooling | `pnpm` for web, `uv` for Python, `make` as the common command interface |
| CI | Jenkins pipeline executes the same `make` targets as developers |

Version one is single-owner: every document and conversation belongs only to the authenticated Cognito `sub`. Chat answers are non-streaming and include source citations. Do not implement organization sharing, OCR, virus scanning, WebSockets, or token streaming.

## Repository Layout

```text
.
|-- apps/web/                    # Vite application
|-- services/api/                # HTTP Lambda handlers and domain code
|-- services/ingestion/          # SQS worker and document processing
|-- packages/contracts/          # OpenAPI document and shared generated types, if needed
|-- infrastructure/cdk/          # CDK app, stacks, and Lambda/layer build definitions
|-- infrastructure/localstack/   # LocalStack initialization scripts
|-- database/migrations/         # Ordered PostgreSQL migrations
|-- tests/integration/           # DynamoDB vector, S3, and API boundary tests
|-- tests/e2e/                   # Playwright browser tests
|-- ops/jenkins/                 # Jenkinsfile and agent image definitions
|-- compose.yaml
|-- Makefile
|-- .env.example
`-- BUILD_SPEC.md
```

Use a root `Makefile`; it is the only supported developer and CI interface. Required targets are `bootstrap`, `up`, `down`, `format`, `lint`, `typecheck`, `test`, `test-integration`, `test-e2e`, `build`, `infra-synth`, `infra-local`, `infra-deploy`, and `ci`.

## Application Design

### Request Flow

```text
React SPA -> Cognito Hosted UI -> API Gateway JWT authorizer -> API Lambda
React SPA -> API Lambda -> scoped presigned S3 PUT -> private S3 object
S3 object-created event -> SQS -> ingestion Lambda -> DynamoDB vector index
React SPA -> chat API -> retrieve owner-filtered chunks -> Bedrock -> DynamoDB message + citations
```

The SPA uses OIDC Authorization Code Flow with PKCE. It receives an access token, sends it as `Authorization: Bearer <token>`, and never receives AWS access keys, database credentials, Google client secrets, or Bedrock credentials.

All API handlers derive `owner_id` from the verified JWT `sub`; they never accept an owner ID in a request body or path. Validate every payload at the boundary and return a stable JSON error shape: `{"code": "...", "message": "...", "request_id": "..."}`.

### API Contract

| Method and path | Purpose |
| --- | --- |
| `GET /me` | Return authenticated user identity used by the UI. |
| `GET /conversations` | List the caller's conversations. |
| `POST /conversations` | Create an empty conversation. |
| `GET /conversations/{id}/messages` | Return ordered messages for a caller-owned conversation. |
| `POST /conversations/{id}/messages` | Save user message, retrieve chunks, create answer, persist answer and citations. |
| `POST /documents/upload-url` | Validate filename/type/size, create pending document, return short-lived PUT URL and document ID. |
| `GET /documents` | List the caller's documents and statuses. |
| `GET /documents/{id}` | Return caller-owned document status/error metadata. |

Reject unsupported types, keys outside the generated document prefix, and uploads above the configured maximum. The generated S3 key is `private/{owner_id}/{document_id}/source/{safe_filename}`. The API does not proxy file bytes.

### Persistence

| Store | Required records |
| --- | --- |
| DynamoDB `chat` table | `PK=USER#{owner_id}`. Conversation header: `SK=CONVERSATION#{conversation_id}`. Message: `SK=MESSAGE#{conversation_id}#{created_at}#{message_id}`. Store role, text, citation IDs, model metadata, and timestamps. |
| DynamoDB `documents` table | `PK=USER#{owner_id}`, `SK=DOCUMENT#{document_id}`. Store generated S3 key, filename, content type, size, SHA-256, status (`pending`, `processing`, `ready`, `failed`), error code, chunk count, and timestamps. |
| S3 | Private encrypted source documents only. Block public access. |
| Aurora `document_chunks` | `id`, `owner_id`, `document_id`, `chunk_index`, `content`, `content_hash`, `embedding vector(embedding_dimension)`, `metadata jsonb`, timestamps. Add a unique constraint on `(document_id, chunk_index)` and a vector index appropriate for the selected embedding dimension. |

Filter by `owner_id` and ready document status in the SQL retrieval query before limiting nearest results. Citation objects returned to the client include document ID, filename, chunk index, and an excerpt, never an S3 URL.

### Ingestion

1. `POST /documents/upload-url` creates a `pending` document record and a short-lived, exact-key presigned PUT URL.
2. S3 object creation sends an event to SQS. The event body carries the S3 object key/version and document ID.
3. The worker loads the document record, verifies that the key belongs to its `owner_id`, and atomically claims processing. Duplicate events must exit successfully when the document is already `ready`.
4. Extract text, normalize it, create bounded overlapping chunks, generate embeddings in batches, and insert chunks idempotently.
5. Mark `ready` only after every chunk is committed. On error mark `failed` with a safe error code, raise for retryable errors, and allow exhausted messages to reach the DLQ.

Keep parser and embedding functions separate from AWS adapters. Do not call an external model when `MODEL_PROVIDER=fake`.

## Infrastructure and Packaging

Create CDK stacks in dependency order: foundation (KMS/logging if needed), auth, data, API/ingestion, and frontend hosting. Support `dev`, `integration`, and `prod` CDK environments with account, region, and domain settings passed through CDK context or deployment configuration, not source edits.

Provision:

- Cognito User Pool, hosted UI domain, callback/logout URLs, email/password configuration, and Google identity provider. Store the Google client secret in Secrets Manager; reference it from CDK without committing it.
- Private S3 document bucket with encryption, versioning, public-access block, lifecycle policy, and event routing to SQS.
- SQS ingestion queue and DLQ with visibility timeout greater than worker timeout.
- DynamoDB tables using on-demand capacity and point-in-time recovery in production.
- DynamoDB on-demand document table with a 1,024-dimension native vector index, `DOT_PRODUCT` distance, an `owner_id` partition key, and retrieval-only projected fields.
- HTTP API, Cognito authorizer, Python Lambdas, least-privilege IAM roles, structured CloudWatch logs, and alarms for API errors, DLQ messages, failed ingestions, and Lambda errors.
- Amplify application/branch build configuration pointing at `apps/web` and only public frontend environment variables.

Package handlers as zip assets. Use Lambda layers only for genuinely shared or native dependencies. Build function and layer artifacts in a Linux image compatible with the chosen Lambda architecture. Use `arm64` for all Lambdas and layers unless a dependency forces `x86_64`; do not mix architectures. CDK owns all artifact hashes and layer versions. Never upload zip files manually.

No database migration job is required. DynamoDB manages vector-index creation and backfill.

## Local Containers and Environments

`compose.yaml` must run with both `docker compose` and `podman compose`. Define `localstack`, `api`, `web`, and `keycloak` as the default profile; put `jenkins` behind a `jenkins` profile. The API container requires a real AWS IAM key because DynamoDB vector search and Bedrock are not emulated locally.

LocalStack provides Lambda/API Gateway experimentation only. Keycloak is the local OIDC issuer. DynamoDB vector search, S3, and Bedrock use the developer's AWS account, so local behavior exercises the same storage and model APIs as deployment.

All configuration is environment based. Commit `.env.example` with variable names and safe defaults only. Put developer values in ignored `.env.local`. Compose loads `.env.local`; application commands load it explicitly through the Makefile. Do not commit `.env`, `.env.local`, secrets, tokens, generated AWS credentials, or Terraform/CDK outputs.

| Variable | Local value | AWS value | Exposure |
| --- | --- | --- | --- |
| `APP_ENV` | `local` | `dev`, `integration`, or `prod` | Backend only |
| `AWS_REGION` | `us-east-1` | deployed region | Backend/CDK |
| `AWS_ENDPOINT_URL` | `http://localhost:4566` | unset | Backend only |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | developer IAM key with DynamoDB/S3/Bedrock access | unset; Lambda IAM role supplies credentials | Backend only |
| `DYNAMODB_CHAT_TABLE` / `DYNAMODB_DOCUMENTS_TABLE` | local resource names | CDK-generated names | Backend only |
| `DOCUMENT_BUCKET` / `INGESTION_QUEUE_URL` | LocalStack endpoints/names | CDK-generated values | Backend only |
| `DYNAMODB_VECTOR_INDEX_NAME` | `ChunksByEmbedding` | CDK-defined index name | Backend only |
| `OIDC_ISSUER` / `OIDC_CLIENT_ID` | Keycloak realm/client | Cognito issuer/app client ID | Browser-safe issuer/client ID only |
| `VITE_API_BASE_URL` | local API URL | deployed API URL | Browser-safe |
| `VITE_OIDC_ISSUER` / `VITE_OIDC_CLIENT_ID` | Keycloak values | Cognito values | Browser-safe |
| `MODEL_PROVIDER` | `fake` | `bedrock` | Backend only |
| `BEDROCK_MODEL_ID` / `EMBEDDING_MODEL_ID` | optional fake identifiers | approved regional model IDs | Backend only |
| `GOOGLE_CLIENT_SECRET` | unset or local Keycloak secret | Secrets Manager only | Secret; never environment-injected into frontend |

AWS SDK construction never sets an endpoint in local or deployed application code. Local containers use the supplied IAM key; deployed Lambdas use their role and runtime region. Validate configuration on startup and fail fast if a LocalStack endpoint is supplied to the application.

## Quality, Tests, and CI

Use strict TypeScript, ESLint, Prettier, and Vitest for the frontend. Use Ruff (format and lint), Pyright, and Pytest for Python. Pin tool versions and lock all dependencies. `make format` must modify files; `make lint`, `make typecheck`, and test targets must not.

| Test level | Required coverage |
| --- | --- |
| Unit | Pure chunking, parsing selection, JWT claim-to-owner mapping, authorization checks, DynamoDB key construction, prompt construction, provider interfaces, and configuration validation. Use fakes; no containers or AWS calls. |
| Integration | DynamoDB vector search against AWS, S3-to-SQS ingestion lifecycle, idempotent duplicate event behavior, and API authorization with Keycloak-issued test JWTs. |
| CDK | `cdk synth`, template assertions for encryption/IAM/auth/routing, and no wildcard resource permissions unless technically required and documented. |
| E2E | Playwright against local UI/API for private chat/upload status. Deployed integration tests cover real Cognito email authentication, Google SSO, Aurora through RDS Proxy, upload, ingestion, and grounded citations. |

The Jenkins pipeline stages are: checkout, bootstrap, format check, lint, typecheck, unit tests, frontend build, Lambda/layer build, CDK synth, local integration tests, then an approval-gated deployment to `integration` followed by deployed smoke/E2E tests. Jenkins obtains deploy credentials from its credential store; never from the repository. Pull-request validation requires no production credentials.

## Build Order and Completion Criteria

1. Create tool configuration, ignored local environment files, Compose services, Makefile targets, and CDK synth test.
2. Build Cognito/Keycloak authentication flow, API JWT validation, and private DynamoDB conversation CRUD.
3. Build direct S3 upload and observable document status lifecycle through LocalStack/SQS.
4. Build local PostgreSQL migrations, ingestion/chunking, fake embeddings, owner-filtered retrieval, and cited fake-chat responses.
5. Add Bedrock provider implementation, DynamoDB vector-index CDK resources, and deployed integration verification.
6. Add Amplify hosting configuration, Jenkins pipeline, alarms, budget alerts, and operating runbooks only when the preceding tests pass.

The build is complete when `make ci` passes on a clean checkout; `make up` plus local E2E permits two isolated test users to upload and query their own documents without cross-user results; `cdk synth` passes; and a deployed integration environment proves email login, Google login, DynamoDB vector retrieval, ingestion, and source citations.
