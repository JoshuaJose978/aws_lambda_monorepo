# AWS Lambda Chatbot Monorepo

Implementation requirements are in [`BUILD_SPEC.md`](BUILD_SPEC.md). It is the single source of truth for the application, local environment, AWS CDK deployment, tests, and CI.

## Private Document RAG

The application is a single-owner document chatbot: browser uploads go directly to private S3 keys, S3 routes events to SQS, the ingestion Lambda creates chunk embeddings in DynamoDB's native vector index, and the API retrieves only chunks in the verified Cognito subject's partition. The browser uses OIDC Authorization Code Flow with PKCE and receives no AWS credentials.

### Local development

1. Copy `.env.example` to the ignored `.env.local`. Set an AWS access key and secret that have the permissions in [`ops/local-developer-policy.json`](ops/local-developer-policy.json), then set `DYNAMODB_CHAT_TABLE`, `DYNAMODB_DOCUMENTS_TABLE`, and `DOCUMENT_BUCKET` from the deployed CDK stack outputs or the AWS Console.
2. Run `make bootstrap`.
3. Run `make configure-local-bucket` to allow browser uploads from `http://localhost:5173` (and `http://127.0.0.1:5173`).
4. Confirm `DYNAMODB_DOCUMENTS_TABLE` has the `ChunksByEmbedding` vector index before uploading documents.
5. Run `make up` to start LocalStack's Lambda/API emulation, the local API container, Vite frontend, and Keycloak.
6. Run `make ci` for formatting, linting, types, unit tests, frontend build, Lambda layer build, and CDK synthesis.

The Makefile automatically uses Podman when it is installed, otherwise Docker. It supplies LocalStack with Podman's VM-native API socket on macOS and Docker's standard socket otherwise. Override the selection when needed, for example `make up CONTAINER_RUNTIME=docker` or `make up CONTAINER_RUNTIME=podman`; set `CONTAINER_SOCKET` only for a non-standard runtime socket.

`make build` produces the Lambda dependency layer in an ARM64 Linux Lambda image. Podman or Docker with Compose support is therefore required for builds and local integration tests. Use `make down` to stop local services.

### AWS deployment

1. Create a Secrets Manager secret named `private-rag/<stage>/google-oidc` containing the Google OIDC client secret before deployment. Set `googleClientId`, `cognitoDomainPrefix`, callback/logout URLs, and allowed API/upload origins through CDK context.
2. Bootstrap the target account and region once with the CDK bootstrap permissions recommended by AWS.
3. Attach `ops/deploy-user-policy.json` to the human or CI deployment principal, then run `make infra-deploy STAGE=integration`.
4. In Amazon Bedrock, grant model access for the selected chat and embedding models in the deployment region. Override their IDs through `bedrockModelId` and `embeddingModelId` CDK context when required.

Open `http://localhost:5173` and sign in as `demo` / `demo`. The frontend calls `http://localhost:3000`; that API validates the Keycloak token and uses the AWS account configured in `.env.local`. DynamoDB vector search, S3, and Bedrock are intentionally real AWS services because local emulators do not implement DynamoDB vector search.

The deployment policy no longer requires VPC, NAT Gateway, Aurora, RDS Proxy, or database-secret permissions. It is still intended for a dedicated deployment account or permission boundary; runtime Lambda roles receive resource-scoped DynamoDB, S3, SQS, and Bedrock permissions from CDK.
