"""Crusoe fine-tuning transport with persistent, single-submission state.

No upload, paid job, or inference runs during import. The caller must perform
dataset review and reserve the cost before calling mutation methods. Ambiguous
POST results require reconciliation; they are never sent again automatically.
"""
from __future__ import annotations

from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time
from typing import Any
from urllib import error, parse, request

from .provider import load_key

BASE_URL = "https://api.intelligence.crusoecloud.com/v1"
TRAINING_MODEL = "ftmodel-6c22bf52-fb65-4bd5-94c4-736f0a7d33f0"
USER_AGENT = "uita-historical-benchmark/1.0"
TERMINAL = {"succeeded", "failed", "cancelled"}


class CrusoeError(RuntimeError):
    pass


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def scrub(value: Any) -> Any:
    """Persist provenance without keys or temporary access-bearing links."""
    if isinstance(value, dict):
        return {k: scrub(v) for k, v in value.items()
                if not re.search(r"token$|secret|credential|authorization|download_url|signed_url", k, re.I)
                or k == "trained_tokens"}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, str):
        return re.sub(r"https?://[^\s\"<>]+", "[URL omitted]", value)
    return value


class _SafeRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old_origin, new_origin = parse.urlsplit(req.full_url), parse.urlsplit(newurl)
        if new_origin.scheme != "https":
            raise CrusoeError("Crusoe redirects must preserve HTTPS")
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected and (old_origin.scheme, old_origin.netloc) != (new_origin.scheme, new_origin.netloc):
            redirected.remove_header("Authorization")
        return redirected


class Client:
    def __init__(self, *, key: str | None = None):
        self.key = key or load_key()
        self.opener = request.build_opener(_SafeRedirect())

    def call(self, method: str, path: str, *, payload: Any = None,
             body: bytes | None = None, content_type: str | None = None,
             idempotency_key: str | None = None, raw: bool = False) -> Any:
        if not path.startswith("/") or path.startswith("//"):
            raise CrusoeError("Only relative Crusoe API paths are allowed")
        if payload is not None:
            body, content_type = canonical(payload), "application/json"
        headers = {"Authorization": "Bearer " + self.key, "User-Agent": USER_AGENT,
                   "Accept": "application/octet-stream" if raw else "application/json"}
        if content_type:
            headers["Content-Type"] = content_type
        if idempotency_key:
            # Provider support is not assumed. The durable ledger below is the
            # duplicate-submission defense even if this header is ignored.
            headers["Idempotency-Key"] = idempotency_key
        req = request.Request(BASE_URL + path, data=body, headers=headers, method=method)
        try:
            with self.opener.open(req, timeout=90) as response:
                result = response.read()
            return result if raw else json.loads(result)
        except error.HTTPError as exc:
            # Bodies can contain signed links or backend credentials. Keep only
            # the status code; callers collect structured job errors by GET.
            raise CrusoeError(f"Crusoe {method} returned HTTP {exc.code}") from None
        except (error.URLError, TimeoutError, ValueError, OSError):
            raise CrusoeError(f"Crusoe {method} response unavailable; do not repeat an ambiguous POST") from None

    def models(self) -> list[dict]:
        return self.call("GET", "/models")["data"]

    def files(self) -> list[dict]:
        data = self.call("GET", "/files?limit=10000")
        if data.get("has_more"):
            raise CrusoeError("File list is incomplete; reconcile uploads before continuing")
        return data["data"]

    def jobs(self, suffix: str | None = None) -> list[dict]:
        path = "/fine_tuning/jobs"
        if suffix:
            path += "?" + parse.urlencode({"suffix": suffix})
        data = self.call("GET", path)
        if data.get("has_more"):
            raise CrusoeError("Job list is incomplete; reconcile jobs before continuing")
        return data["data"]


class Experiment:
    """A file lock and atomic writes make restarts/concurrent calls safe."""

    def __init__(self, directory: str | Path, *, client: Client | None = None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "crusoe-state.json"
        self.client = client or Client()

    @contextmanager
    def _locked(self):
        with (self.directory / "crusoe-state.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = json.loads(self.path.read_text()) if self.path.exists() else {"schema_version": 1, "files": {}}
            yield state

    def _save(self, state: dict) -> None:
        state["updated_at_epoch"] = time.time()
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(scrub(state), indent=2, allow_nan=False) + "\n")
        os.replace(temporary, self.path)

    def upload(self, path: Path, role: str, *, expected_sha256: str) -> dict:
        if role not in {"train", "validation"} or path.suffix != ".jsonl":
            raise CrusoeError("Only explicit train/validation JSONL uploads are supported")
        data = path.read_bytes()
        digest = sha256(data)
        if digest != expected_sha256:
            raise CrusoeError("Dataset changed after reviewed preflight; upload refused")
        filename = f"uita-{role}-{digest}.jsonl"
        with self._locked() as state:
            prior = state["files"].get(role)
            if prior and prior["sha256"] != digest:
                raise CrusoeError("Dataset changed under an existing experiment; use a new experiment directory")
            if prior and prior.get("id"):
                return prior
            matches = [f for f in self.client.files()
                       if f.get("filename") == filename and f.get("bytes") == len(data)]
            if len(matches) > 1:
                raise CrusoeError("Multiple identical-name uploaded files exist; reconcile without uploading again")
            if matches:
                f = matches[0]
                downloaded = self.client.call("GET", "/files/" + parse.quote(f["id"], safe="") + "/content", raw=True)
                if sha256(downloaded) != digest:
                    raise CrusoeError("Existing upload does not match the dataset content hash")
                state["files"][role] = {"id": f["id"], "sha256": digest, "bytes": len(data),
                                        "filename": filename, "status": "reconciled"}
                self._save(state)
                return state["files"][role]
            if prior and prior.get("status") in {"submitting", "ambiguous"}:
                raise CrusoeError("Upload response remains unresolved; absence from a list does not authorize another POST")
            record = {"sha256": digest, "bytes": len(data), "filename": filename, "status": "submitting"}
            state["files"][role] = record
            self._save(state)
            boundary = "uita-" + digest[:32]
            body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"purpose\"\r\n\r\nfine-tune\r\n"
                    f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
                    "Content-Type: application/jsonl\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
            try:
                result = self.client.call("POST", "/files", body=body,
                                          content_type="multipart/form-data; boundary=" + boundary,
                                          idempotency_key="uita-upload-" + digest)
                if not isinstance(result.get("id"), str):
                    raise CrusoeError("Upload response lacks an ID")
            except CrusoeError:
                record["status"] = "ambiguous"
                self._save(state)
                raise
            record.update({"id": result["id"], "status": "uploaded"})
            self._save(state)
            return record

    def estimate(self, payload: dict) -> dict:
        result = self.client.call("POST", "/fine_tuning/jobs/estimate_price", payload=payload)
        with self._locked() as state:
            state["price_estimate"] = {"request_sha256": sha256(canonical(payload)), "result": result}
            self._save(state)
        return result

    def start(self, payload: dict, *, cost_reservation_usd: float, max_runtime_seconds: int) -> dict:
        if not math.isfinite(cost_reservation_usd) or cost_reservation_usd <= 0:
            raise CrusoeError("A finite positive training cost reservation is required")
        if type(max_runtime_seconds) is not int or not 60 <= max_runtime_seconds <= 7200:
            raise CrusoeError("Training runtime must be bounded from 60 to 7,200 seconds")
        fingerprint = sha256(canonical(payload))
        with self._locked() as state:
            prior = state.get("job")
            if prior and prior["request_sha256"] != fingerprint:
                raise CrusoeError("Job configuration changed under an existing experiment")
            if prior and prior.get("id"):
                return self.client.call("GET", "/fine_tuning/jobs/" + parse.quote(prior["id"], safe=""))
            # The API supports a suffix query but need not echo suffix in each
            # job object. Match the returned filtered list by immutable inputs.
            matches = self.client.jobs(payload["suffix"])
            matches = [job for job in matches if job.get("model") == payload["model"]
                       and job.get("training_file") == payload["training_file"]
                       and job.get("validation_file") == payload["validation_file"]]
            if len(matches) > 1:
                raise CrusoeError("Multiple matching jobs exist; do not create another")
            if matches:
                job = matches[0]
                state["job"] = {"id": job["id"], "request_sha256": fingerprint,
                                "cost_reservation_usd": cost_reservation_usd,
                                "deadline_epoch": (prior or {}).get("deadline_epoch", time.time() + max_runtime_seconds),
                                "status": job["status"], "request": payload}
                self._save(state)
                return job
            if prior:
                raise CrusoeError("Job POST remains unresolved; absence from a list does not authorize resubmission")
            state["job"] = {"request_sha256": fingerprint, "status": "submitting", "request": payload,
                            "cost_reservation_usd": cost_reservation_usd,
                            "deadline_epoch": time.time() + max_runtime_seconds}
            self._save(state)
            try:
                job = self.client.call("POST", "/fine_tuning/jobs", payload=payload,
                                       idempotency_key="uita-job-" + fingerprint)
                if not isinstance(job.get("id"), str):
                    raise CrusoeError("Job creation response lacks an ID")
            except CrusoeError:
                state["job"]["status"] = "ambiguous"
                self._save(state)
                raise
            state["job"].update({"id": job["id"], "status": job["status"], "response": job})
            self._save(state)
            return job

    def status(self, *, cancel_overdue: bool = False) -> dict:
        with self._locked() as state:
            tracked = state.get("job", {})
            if not tracked.get("id"):
                raise CrusoeError("There is no resolved job ID in this experiment")
            endpoint = "/fine_tuning/jobs/" + parse.quote(tracked["id"], safe="")
            job = self.client.call("GET", endpoint)
            if job["status"] not in TERMINAL and time.time() > tracked["deadline_epoch"] and cancel_overdue:
                # Persist cancellation intent so a lost response does not become
                # a second paid training job. Cancelling this job is idempotent.
                tracked["cancellation_requested_at_epoch"] = time.time()
                self._save(state)
                job = self.client.call("POST", endpoint + "/cancel")
            tracked.update({"status": job["status"], "response": job})
            for name in ("checkpoints", "events", "metrics"):
                try:
                    tracked[name] = self.client.call("GET", endpoint + "/" + name)
                except CrusoeError as exc:
                    tracked[name + "_collection_error"] = str(exc)
            self._save(state)
            return scrub(tracked)

    def cancel(self) -> dict:
        with self._locked() as state:
            tracked = state.get("job", {})
            if not tracked.get("id"):
                raise CrusoeError("Cannot cancel an unresolved job")
            tracked["cancellation_requested_at_epoch"] = time.time()
            self._save(state)
            job = self.client.call("POST", "/fine_tuning/jobs/" + parse.quote(tracked["id"], safe="") + "/cancel")
            tracked.update({"status": job["status"], "response": job})
            self._save(state)
            return scrub(tracked)

    def download(self, checkpoint_id: str) -> dict:
        with self._locked() as state:
            tracked = state.get("job", {})
            files = (tracked.get("response") or {}).get("result_files") or []
            checkpoints = (tracked.get("checkpoints") or {}).get("data") or []
            allowed = set(files) | {c["id"] for c in checkpoints if "id" in c}
            if checkpoint_id not in allowed:
                raise CrusoeError("Checkpoint must belong to this experiment's recorded job")
            target = self.directory / ("checkpoint-" + sha256(checkpoint_id.encode())[:16] + ".zip")
            if target.exists():
                return {"path": str(target), "sha256": sha256(target.read_bytes()), "bytes": target.stat().st_size}
            payload = self.client.call("GET", "/files/" + parse.quote(checkpoint_id, safe="") + "/content", raw=True)
            temporary = target.with_suffix(".tmp")
            temporary.write_bytes(payload)
            os.replace(temporary, target)
            result = {"id": checkpoint_id, "path": str(target), "sha256": sha256(payload), "bytes": len(payload)}
            tracked.setdefault("downloads", []).append(result)
            self._save(state)
            return result
