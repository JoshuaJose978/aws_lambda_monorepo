from __future__ import annotations

from pathlib import Path

from aws_cdk import (
    Aws,
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
)
from aws_cdk import (
    aws_amplify as amplify,
)
from aws_cdk import (
    aws_apigatewayv2 as apigwv2,
)
from aws_cdk import (
    aws_apigatewayv2_authorizers as authorizers,
)
from aws_cdk import (
    aws_apigatewayv2_integrations as integrations,
)
from aws_cdk import (
    aws_cognito as cognito,
)
from aws_cdk import (
    aws_dynamodb as dynamodb,
)
from aws_cdk import (
    aws_iam as iam,
)
from aws_cdk import (
    aws_kms as kms,
)
from aws_cdk import (
    aws_lambda as lambda_,
)
from aws_cdk import (
    aws_lambda_event_sources as event_sources,
)
from aws_cdk import (
    aws_logs as logs,
)
from aws_cdk import (
    aws_s3 as s3,
)
from aws_cdk import (
    aws_s3_notifications as s3_notifications,
)
from aws_cdk import (
    aws_secretsmanager as secretsmanager,
)
from aws_cdk import (
    aws_sqs as sqs,
)
from constructs import Construct

ROOT = Path(__file__).resolve().parents[2]
SERVICE_SOURCE = str(ROOT / "services")
AMPLIFY_BUILD_SPEC = """version: 1
applications:
  - appRoot: apps/web
    frontend:
      phases:
        build:
          commands: [pnpm build]
      artifacts:
        baseDirectory: dist
        files: ['**/*']
"""


class FoundationStack(Stack):
    def __init__(
        self, scope: Construct, construct_id: str, *, stage: str, **kwargs: object
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)


class AuthStack(Stack):
    def __init__(
        self, scope: Construct, construct_id: str, *, stage: str, **kwargs: object
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        google_secret = secretsmanager.Secret.from_secret_name_v2(
            self,
            "GoogleOidcSecret",
            self.node.try_get_context("googleSecretName") or f"private-rag/{stage}/google-oidc",
        )
        self.user_pool = cognito.UserPool(
            self,
            "UserPool",
            self_sign_up_enabled=True,
            sign_in_aliases=cognito.SignInAliases(email=True),
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            password_policy=cognito.PasswordPolicy(
                min_length=12,
                require_digits=True,
                require_lowercase=True,
                require_uppercase=True,
                require_symbols=True,
            ),
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            removal_policy=RemovalPolicy.RETAIN,
        )
        cognito.UserPoolIdentityProviderGoogle(
            self,
            "Google",
            user_pool=self.user_pool,
            client_id=self.node.try_get_context("googleClientId") or "configure-in-context",
            client_secret_value=google_secret.secret_value,
            scopes=["openid", "email", "profile"],
            attribute_mapping=cognito.AttributeMapping(
                email=cognito.ProviderAttribute.GOOGLE_EMAIL
            ),
        )
        callback_urls = self.node.try_get_context("callbackUrls") or ["http://localhost:5173"]
        logout_urls = self.node.try_get_context("logoutUrls") or ["http://localhost:5173"]
        self.user_pool_client = self.user_pool.add_client(
            "WebClient",
            generate_secret=False,
            auth_flows=cognito.AuthFlow(user_srp=True),
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(authorization_code_grant=True),
                scopes=[
                    cognito.OAuthScope.OPENID,
                    cognito.OAuthScope.EMAIL,
                    cognito.OAuthScope.PROFILE,
                ],
                callback_urls=callback_urls,
                logout_urls=logout_urls,
            ),
            supported_identity_providers=[
                cognito.UserPoolClientIdentityProvider.COGNITO,
                cognito.UserPoolClientIdentityProvider.GOOGLE,
            ],
        )
        self.user_pool.add_domain(
            "HostedUiDomain",
            cognito_domain=cognito.CognitoDomainOptions(
                domain_prefix=self.node.try_get_context("cognitoDomainPrefix")
                or f"private-rag-{stage}"
            ),
        )


class DataStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage: str,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        data_key = kms.Key(
            self, "DataKey", enable_key_rotation=True, removal_policy=RemovalPolicy.RETAIN
        )
        self.documents_bucket = s3.Bucket(
            self,
            "DocumentBucket",
            encryption=s3.BucketEncryption.KMS,
            encryption_key=data_key,
            versioned=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[s3.LifecycleRule(noncurrent_version_expiration=Duration.days(30))],
            cors=[
                s3.CorsRule(
                    allowed_methods=[s3.HttpMethods.PUT],
                    allowed_origins=self.node.try_get_context("uploadOrigins")
                    or ["http://localhost:5173"],
                    allowed_headers=["content-type"],
                    max_age=300,
                )
            ],
        )
        self.ingestion_dlq = sqs.Queue(
            self,
            "IngestionDlq",
            encryption=sqs.QueueEncryption.KMS,
            encryption_master_key=data_key,
            retention_period=Duration.days(14),
        )
        self.ingestion_queue = sqs.Queue(
            self,
            "IngestionQueue",
            encryption=sqs.QueueEncryption.KMS,
            encryption_master_key=data_key,
            visibility_timeout=Duration.minutes(6),
            dead_letter_queue=sqs.DeadLetterQueue(max_receive_count=3, queue=self.ingestion_dlq),
        )
        self.documents_bucket.add_event_notification(
            s3.EventType.OBJECT_CREATED,
            s3_notifications.SqsDestination(self.ingestion_queue),
            s3.NotificationKeyFilter(prefix="private/"),
        )
        point_in_time = stage == "prod"
        self.chat_table = self._table("Chat", "PK", "SK", point_in_time)
        self.documents_table = self._table("DocumentsTable", "PK", "SK", point_in_time)
        self._add_vector_index(self.documents_table)

    def _table(
        self, name: str, partition_key: str, sort_key: str, point_in_time: bool
    ) -> dynamodb.Table:
        return dynamodb.Table(
            self,
            name,
            partition_key=dynamodb.Attribute(
                name=partition_key, type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(name=sort_key, type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery=point_in_time,
            encryption=dynamodb.TableEncryption.AWS_MANAGED,
            removal_policy=RemovalPolicy.RETAIN,
        )

    def _add_vector_index(self, table: dynamodb.Table) -> None:
        table.node.default_child.add_property_override(  # type: ignore[union-attr]
            "VectorIndexes",
            [
                {
                    "IndexName": "ChunksByEmbedding",
                    "VectorAttribute": {"AttributeName": "embedding"},
                    "Dimensions": 1024,
                    "DistanceFunction": "DOT_PRODUCT",
                    "Projection": {
                        "ProjectionType": "INCLUDE",
                        "NonKeyAttributes": [
                            "owner_id",
                            "document_id",
                            "filename",
                            "chunk_index",
                            "content",
                        ],
                    },
                    "PartitionKey": {"AttributeName": "owner_id"},
                }
            ],
        )


class ApiIngestionStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage: str,
        user_pool: cognito.IUserPool,
        user_pool_client: cognito.IUserPoolClient,
        documents_bucket: s3.IBucket,
        chat_table: dynamodb.ITable,
        documents_table: dynamodb.ITable,
        ingestion_queue: sqs.IQueue,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        self.dependencies_layer = lambda_.LayerVersion(
            self,
            "PythonDependencies",
            code=lambda_.Code.from_asset(str(ROOT / "infrastructure" / "lambda-layer")),
            compatible_runtimes=[lambda_.Runtime.PYTHON_3_12],
            compatible_architectures=[lambda_.Architecture.ARM_64],
        )
        common = {
            "APP_ENV": stage,
            "DYNAMODB_CHAT_TABLE": chat_table.table_name,
            "DYNAMODB_DOCUMENTS_TABLE": documents_table.table_name,
            "DOCUMENT_BUCKET": documents_bucket.bucket_name,
            "DYNAMODB_VECTOR_INDEX_NAME": "ChunksByEmbedding",
            "MODEL_PROVIDER": self.node.try_get_context("modelProvider") or "bedrock",
            "BEDROCK_MODEL_ID": self.node.try_get_context("bedrockModelId")
            or "amazon.nova-lite-v1:0",
            "EMBEDDING_MODEL_ID": self.node.try_get_context("embeddingModelId")
            or "amazon.titan-embed-text-v2:0",
            "PYTHONPATH": "/var/task/api/src:/var/task/common/src:/var/task/ingestion/src",
        }
        self.api_function = self._function("ApiFunction", "rag_api.handler.lambda_handler", common)
        self.worker_function = self._function(
            "IngestionFunction",
            "rag_ingestion.worker.lambda_handler",
            common,
            timeout=Duration.minutes(5),
        )
        documents_bucket.grant_read_write(self.api_function, "private/*")
        documents_bucket.grant_read(self.worker_function, "private/*")
        chat_table.grant_read_write_data(self.api_function)
        documents_table.grant_read_write_data(self.api_function)
        documents_table.grant_read_write_data(self.worker_function)
        self.api_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["dynamodb:SearchVectors"], resources=[documents_table.table_arn]
            )
        )
        ingestion_queue.grant_consume_messages(self.worker_function)
        self.api_function.add_to_role_policy(
            iam.PolicyStatement(actions=["bedrock:InvokeModel"], resources=["*"])
        )
        self.worker_function.add_to_role_policy(
            iam.PolicyStatement(actions=["bedrock:InvokeModel"], resources=["*"])
        )
        self.worker_function.add_event_source(
            event_sources.SqsEventSource(
                ingestion_queue, batch_size=5, report_batch_item_failures=True
            )
        )
        issuer = f"https://cognito-idp.{Aws.REGION}.amazonaws.com/{user_pool.user_pool_id}"
        self.http_api = apigwv2.HttpApi(
            self,
            "HttpApi",
            cors_preflight=apigwv2.CorsPreflightOptions(
                allow_headers=["authorization", "content-type"],
                allow_methods=[apigwv2.CorsHttpMethod.ANY],
                allow_origins=self.node.try_get_context("apiOrigins") or ["http://localhost:5173"],
            ),
        )
        jwt = authorizers.HttpJwtAuthorizer(
            "JwtAuthorizer", issuer, jwt_audience=[user_pool_client.user_pool_client_id]
        )
        self.http_api.add_routes(
            path="/{proxy+}",
            methods=[apigwv2.HttpMethod.ANY],
            integration=integrations.HttpLambdaIntegration("ApiIntegration", self.api_function),
            authorizer=jwt,
        )
        self.http_api.add_routes(
            path="/me",
            methods=[apigwv2.HttpMethod.GET],
            integration=integrations.HttpLambdaIntegration("MeIntegration", self.api_function),
            authorizer=jwt,
        )
        for name, function in [
            ("ApiErrors", self.api_function),
            ("WorkerErrors", self.worker_function),
        ]:
            function.metric_errors().create_alarm(self, name, threshold=1, evaluation_periods=1)
        ingestion_queue.metric_approximate_number_of_messages_visible().create_alarm(
            self, "DlqMessages", threshold=1, evaluation_periods=1
        )
        CfnOutput(self, "ApiUrl", value=self.http_api.api_endpoint)

    def _function(
        self,
        name: str,
        handler: str,
        environment: dict[str, str],
        timeout: Duration | None = None,
    ) -> lambda_.Function:
        return lambda_.Function(
            self,
            name,
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler=handler,
            code=lambda_.Code.from_asset(SERVICE_SOURCE, exclude=["**/__pycache__/**", "**/*.pyc"]),
            timeout=timeout or Duration.seconds(30),
            memory_size=512,
            environment=environment,
            layers=[self.dependencies_layer],
            tracing=lambda_.Tracing.ACTIVE,
            log_retention=logs.RetentionDays.ONE_MONTH,
        )


class FrontendStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        stage: str,
        api: apigwv2.IHttpApi,
        user_pool: cognito.IUserPool,
        user_pool_client: cognito.IUserPoolClient,
        **kwargs: object,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)
        app = amplify.CfnApp(
            self,
            "AmplifyApp",
            name=f"private-rag-{stage}",
            platform="WEB",
            build_spec=AMPLIFY_BUILD_SPEC,
        )
        amplify.CfnBranch(
            self,
            "MainBranch",
            app_id=app.attr_app_id,
            branch_name="main",
            enable_auto_build=True,
            environment_variables=[
                amplify.CfnBranch.EnvironmentVariableProperty(
                    name="VITE_API_BASE_URL", value=api.api_endpoint
                ),
                amplify.CfnBranch.EnvironmentVariableProperty(
                    name="VITE_OIDC_ISSUER",
                    value=f"https://cognito-idp.{Aws.REGION}.amazonaws.com/{user_pool.user_pool_id}",
                ),
                amplify.CfnBranch.EnvironmentVariableProperty(
                    name="VITE_OIDC_CLIENT_ID", value=user_pool_client.user_pool_client_id
                ),
            ],
        )
