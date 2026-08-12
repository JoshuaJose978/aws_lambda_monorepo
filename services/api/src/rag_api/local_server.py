from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import jwt
from jwt import InvalidTokenError, PyJWKClient
from jwt.exceptions import PyJWKClientError
from rag_common.config import Settings
from rag_ingestion.worker import clients, process_record

from rag_api.aws_adapters import DynamoStores
from rag_api.handler import json_dumps, lambda_handler


class _Context:
    aws_request_id = "local"


_jwks_client: PyJWKClient | None = None

_ingestion_lock = threading.Lock()
_ingestion_threads: dict[tuple[str, str], threading.Thread] = {}


def _claims(authorization: str) -> dict[str, str] | None:
    if not authorization.startswith("Bearer "):
        return None
    global _jwks_client
    try:
        if _jwks_client is None:
            _jwks_client = PyJWKClient(os.environ["OIDC_JWKS_URL"])
        token = authorization.removeprefix("Bearer ")
        key = _jwks_client.get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            key.key,
            algorithms=["RS256"],
            issuer=os.environ["OIDC_ISSUER"],
            options={"verify_aud": False},
        )
        if claims.get("azp") != os.environ["OIDC_CLIENT_ID"]:
            return None
        return {key: str(value) for key, value in claims.items()}
    except (InvalidTokenError, KeyError, PyJWKClientError, ValueError):
        return None


class ApiHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        self._handle()

    def do_POST(self) -> None:  # noqa: N802
        self._handle()

    def _handle(self) -> None:
        if self.path == "/health":
            self._write(200, {"status": "ok"})
            return
        authorization = self.headers.get("Authorization", "")
        claims = _claims(authorization)
        if not claims:
            self._write(401, {"code": "unauthorized", "message": "Valid Keycloak token required"})
            return
        path = self.path.split("?", 1)[0]
        path_parts = path.split("/")
        if (
            self.command == "POST"
            and len(path_parts) == 4
            and path_parts[1] == "documents"
            and path_parts[3] == "ingest"
        ):
            self._ingest(claims["sub"], path_parts[2])
            return
        body = self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}"
        event: dict[str, Any] = {
            "rawPath": path,
            "body": body.decode(),
            "requestContext": {
                "http": {"method": self.command},
                "authorizer": {"jwt": {"claims": claims}},
            },
            "pathParameters": {},
        }
        path_parts = event["rawPath"].split("/")
        if (
            len(path_parts) == 4
            and path_parts[1] == "conversations"
            and path_parts[3] == "messages"
        ):
            event["pathParameters"] = {"id": path_parts[2]}
        if len(path_parts) == 3 and path_parts[1] == "documents":
            event["pathParameters"] = {"id": path_parts[2]}
        if (
            len(path_parts) == 4
            and path_parts[1] == "documents"
            and path_parts[3] == "cancel"
        ):
            event["pathParameters"] = {"id": path_parts[2]}
        response = lambda_handler(event, _Context())
        self._write(int(str(response["statusCode"])), json.loads(str(response["body"])))

    def _ingest(self, owner_id: str, document_id: str) -> None:
        settings = Settings.from_env()
        dynamodb, s3 = clients(settings)
        document = DynamoStores(
            dynamodb, settings.chat_table, settings.documents_table
        ).get_document(owner_id, document_id)
        if not document:
            self._write(404, {"code": "not_found", "message": "Document not found"})
            return
        record = {
            "body": json.dumps(
                {"owner_id": owner_id, "document_id": document_id, "key": document["s3_key"]}
            ),
            "messageId": f"local-{document_id}",
        }

        def _run() -> None:
            try:
                process_record(record, settings, dynamodb, s3)
            except Exception:
                # Errors are recorded onto the document by the worker.
                return

        key = (owner_id, document_id)
        with _ingestion_lock:
            existing = _ingestion_threads.get(key)
            if existing and existing.is_alive():
                self._write(202, {"status": "processing"})
                return
            thread = threading.Thread(target=_run, name=f"ingest-{owner_id}-{document_id}")
            thread.daemon = True
            _ingestion_threads[key] = thread
            thread.start()

        # Ingestion is async; client should poll GET /documents/{id}.
        self._write(202, {"status": "processing"})

    def _cors(self) -> None:
        origin = self.headers.get("Origin", "")
        allowed = {"http://localhost:5173", "http://127.0.0.1:5173"}
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Origin", origin if origin in allowed else "http://localhost:5173")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _write(self, status: int, payload: dict[str, object]) -> None:
        data = json_dumps(payload).encode()
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 3000), ApiHandler).serve_forever()
