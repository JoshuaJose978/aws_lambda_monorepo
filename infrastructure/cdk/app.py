#!/usr/bin/env python3
import os

import aws_cdk as cdk
from stacks import ApiIngestionStack, AuthStack, DataStack, FoundationStack, FrontendStack

app = cdk.App()
stage = app.node.try_get_context("stage") or os.getenv("CDK_STAGE", "dev")
account = app.node.try_get_context("account") or os.getenv("CDK_ACCOUNT")
region = app.node.try_get_context("region") or os.getenv("AWS_REGION", "us-east-1")
env = cdk.Environment(account=account, region=region)

FoundationStack(app, f"PrivateRag-{stage}-Foundation", env=env, stage=stage)
auth = AuthStack(app, f"PrivateRag-{stage}-Auth", env=env, stage=stage)
data = DataStack(app, f"PrivateRag-{stage}-Data", env=env, stage=stage)
api = ApiIngestionStack(
    app,
    f"PrivateRag-{stage}-ApiIngestion",
    env=env,
    stage=stage,
    user_pool=auth.user_pool,
    user_pool_client=auth.user_pool_client,
    documents_bucket=data.documents_bucket,
    chat_table=data.chat_table,
    documents_table=data.documents_table,
    ingestion_queue=data.ingestion_queue,
)
FrontendStack(
    app,
    f"PrivateRag-{stage}-Frontend",
    env=env,
    stage=stage,
    api=api.http_api,
    user_pool=auth.user_pool,
    user_pool_client=auth.user_pool_client,
)

app.synth()
