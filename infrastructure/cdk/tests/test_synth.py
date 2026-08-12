import json
import os
import subprocess
import sys
from pathlib import Path


def test_synthesizes_dev_template(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[3]
    environment = os.environ | {"CDK_OUTDIR": str(tmp_path)}
    result = subprocess.run(
        [sys.executable, "app.py", "--context", "stage=dev"],
        cwd=root / "infrastructure" / "cdk",
        capture_output=True,
        text=True,
        env=environment,
    )
    assert result.returncode == 0, result.stderr
    templates = list(tmp_path.glob("*.template.json"))
    resources = [
        resource
        for template in templates
        for resource in json.loads(template.read_text()).get("Resources", {}).values()
    ]
    resource_types = [resource["Type"] for resource in resources]
    assert "AWS::S3::Bucket" in resource_types
    assert "AWS::SQS::Queue" in resource_types
    assert "AWS::DynamoDB::Table" in resource_types
    assert "AWS::Cognito::UserPool" in resource_types
    assert "AWS::ApiGatewayV2::Api" in resource_types
    assert "AWS::RDS::DBProxy" not in resource_types
    assert "AWS::EC2::NatGateway" not in resource_types
    assert any(
        resource["Type"] == "AWS::DynamoDB::Table"
        and resource.get("Properties", {}).get("VectorIndexes", [{}])[0].get("IndexName")
        == "ChunksByEmbedding"
        for resource in resources
    )
