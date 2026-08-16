#!/usr/bin/env python3
"""Extract selected Paperclip papers and run a schema-constrained Codex audit."""

import argparse
import contextlib
import csv
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
DEFAULT_CSV = (
    REPO_ROOT
    / "benchmarks"
    / "perturbation_prediction"
    / "results"
    / "latest_search.csv"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "benchmarks"
    / "perturbation_prediction"
    / "results"
    / "postsearch"
)
DEFAULT_PAPERCLIP = "~/.local/bin/paperclip"
DEFAULT_AGENT_MODEL = "gpt-5.6-luna"
DEFAULT_REASONING_EFFORT = "medium"
OUTPUT_CONTRACT_VERSION = 2
ACQUISITION_VERSION = 4
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
LINE_PATTERN = re.compile(r"^L([0-9]+):[ \t]?(.*)$")
URL_PATTERN = re.compile(r"https?://[^\s<>\"']+")
TRAILING_URL_PUNCTUATION = ".,;:!?"
REMOTE_EXIT_PATTERN = re.compile(r"(?m)^\[exit ([1-9][0-9]*)\][ \t]*$")
CLIPBOARD_ID_PATTERN = re.compile(r"\busr_[a-z0-9]+\b", re.IGNORECASE)
CATALOG_COLUMN_ALIASES = {
    "paperclip_doc_id": ("doc_id",),
    "paper_title": ("title",),
    "paper_url": ("url",),
    "venue": ("source",),
    "publication_date": ("pub_date",),
    "model_name": ("gold_name",),
}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
        raise


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write_text(path, json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def has_pdf_header(path: Path) -> bool:
    try:
        with path.open("rb") as handle:
            return handle.read(4) == b"%PDF"
    except OSError:
        return False


def embedded_paperclip_error(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return ""
    lines = text.splitlines()
    first_line = lines[0].strip()
    exit_match = REMOTE_EXIT_PATTERN.search(text)
    if first_line.startswith("ERR:") and exit_match:
        return f"{first_line} (remote exit {exit_match.group(1)})"
    return ""


def run_capture(command: List[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=timeout,
    )


def normalize_id(raw: str) -> str:
    value = raw.strip()
    if value.startswith("/papers/"):
        value = value[len("/papers/") :]
    value = value.rstrip("/")
    if not ID_PATTERN.fullmatch(value):
        raise ValueError(f"invalid Paperclip ID: {raw!r}")
    return value


def parse_csv_boolean(value: str, path: Path, line_number: int) -> bool:
    normalized = value.strip().lower()
    if normalized in {"true", "1", "yes", "y"}:
        return True
    if normalized in {"false", "0", "no", "n"}:
        return False
    raise ValueError(
        f"{path}:{line_number}: search_reachable must be true or false, got {value!r}"
    )


def normalize_catalog_row(raw_row: Dict[str, Optional[str]]) -> Dict[str, str]:
    row = {
        key: (value.strip() if value is not None else "")
        for key, value in raw_row.items()
        if key is not None
    }
    for canonical, aliases in CATALOG_COLUMN_ALIASES.items():
        if row.get(canonical):
            continue
        row[canonical] = first_text(*(row.get(alias, "") for alias in aliases))

    publication_date = row.get("publication_date", "")
    if publication_date and not row.get("publication_year"):
        year_match = re.match(r"^([0-9]{4})(?:-|$)", publication_date)
        if year_match:
            row["publication_year"] = year_match.group(1)

    doi = row.get("doi", "")
    if doi and not row.get("doi_url"):
        row["doi_url"] = (
            doi if doi.lower().startswith("https://doi.org/") else f"https://doi.org/{doi}"
        )
    return row


def read_catalog_csv(path: Path) -> Tuple[List[Dict[str, str]], List[Dict[str, Any]]]:
    if not path.is_file():
        raise FileNotFoundError(f"CSV file does not exist: {path}")
    selected: List[Dict[str, str]] = []
    skipped: List[Dict[str, Any]] = []
    seen = set()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"CSV has no header: {path}")
        headers = [header.strip() for header in reader.fieldnames]
        if any(not header for header in headers):
            raise ValueError(f"CSV contains an empty header: {path}")
        if len(set(headers)) != len(headers):
            raise ValueError(f"CSV contains duplicate headers: {path}")
        effective_headers = set(headers)
        for canonical, aliases in CATALOG_COLUMN_ALIASES.items():
            if any(alias in effective_headers for alias in aliases):
                effective_headers.add(canonical)
        required = {"paperclip_doc_id"}
        missing = sorted(required - effective_headers)
        if missing:
            descriptions = [
                f"{name} (or {', '.join(CATALOG_COLUMN_ALIASES.get(name, ()))})"
                if CATALOG_COLUMN_ALIASES.get(name)
                else name
                for name in missing
            ]
            raise ValueError(
                f"CSV is missing required column(s): {', '.join(descriptions)}"
            )
        reader.fieldnames = headers

        for raw_row in reader:
            line_number = reader.line_num
            if None in raw_row:
                raise ValueError(
                    f"{path}:{line_number}: row has more values than the header"
                )
            row = normalize_catalog_row(raw_row)
            if not any(row.values()):
                continue
            reachable = True
            if "search_reachable" in headers:
                reachable = parse_csv_boolean(
                    row.get("search_reachable", ""), path, line_number
                )
            if not reachable:
                skipped.append(
                    {
                        "csv_line": line_number,
                        "model_name": row.get("model_name", ""),
                        "paper_title": row.get("paper_title", ""),
                        "paperclip_doc_id": row.get("paperclip_doc_id", ""),
                        "reason": "search_reachable is false",
                    }
                )
                continue
            raw_id = row.get("paperclip_doc_id", "")
            if not raw_id:
                raise ValueError(
                    f"{path}:{line_number}: row has no paperclip_doc_id or doc_id"
                )
            try:
                paper_id = normalize_id(raw_id)
            except ValueError as error:
                raise ValueError(f"{path}:{line_number}: {error}") from error
            if paper_id in seen:
                raise ValueError(
                    f"{path}:{line_number}: duplicate paperclip_doc_id {paper_id!r}"
                )
            row["paperclip_doc_id"] = paper_id
            selected.append(row)
            seen.add(paper_id)
    if not selected:
        raise ValueError(f"CSV contains no papers to process: {path}")
    return selected, skipped


def directory_name(paper_id: str) -> str:
    # The ID validator excludes path separators, so the original value is a
    # safe directory name. Periods are normalized for predictable paths.
    return paper_id.replace(".", "_")


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9._-]+", "-", value.strip().lower()).strip("-")
    return slug


def method_identity(catalog_row: Dict[str, str], paper_id: str) -> Tuple[str, str]:
    preferred = catalog_row.get("bibtex_key", "").strip()
    fallback = catalog_row.get("model_name", "").strip()
    method_folder = slugify(preferred or fallback or paper_id)
    if not method_folder or method_folder in {"logs", "papers", "state"}:
        method_folder = f"method_{slugify(paper_id)}"
    return method_folder, method_folder


def agent_catalog_row(catalog_row: Dict[str, str]) -> Dict[str, str]:
    return {
        key: value
        for key, value in catalog_row.items()
        if key not in {"github_repositories", "paperclip_path"}
    }


def resolve_binary(value: str) -> str:
    if os.path.sep in value:
        path = Path(value).expanduser().resolve()
        if not path.is_file() or not os.access(path, os.X_OK):
            raise FileNotFoundError(f"executable not found: {path}")
        return str(path)
    found = shutil.which(value)
    if not found:
        raise FileNotFoundError(f"executable not found on PATH: {value}")
    return found


def parse_expected_lines(output: bytes) -> Optional[int]:
    match = re.search(rb"[0-9]+", output)
    if not match:
        return None
    value = int(match.group(0))
    return value if value > 0 else None


def json_object_from_output(output: bytes) -> Optional[Dict[str, Any]]:
    try:
        value = json.loads(output.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def first_text(*values: Any) -> str:
    for value in values:
        if value is not None:
            text = str(value).strip()
            if text and text.lower() != "none":
                return text
    return ""


def fetch_targets(catalog_row: Dict[str, str], paper_id: str) -> List[str]:
    targets: List[str] = []
    target_keys = set()

    def add(value: str) -> None:
        candidate = value.strip()
        key = candidate.lower().rstrip("/")
        if candidate and key not in target_keys:
            targets.append(candidate)
            target_keys.add(key)

    doi = catalog_row.get("doi", "").strip()
    if doi.lower().startswith("https://doi.org/"):
        doi = doi[len("https://doi.org/") :]
    if doi:
        add(doi)
    add(catalog_row.get("paper_url", ""))
    add(catalog_row.get("doi_url", ""))
    if paper_id.upper().startswith("PMC"):
        add(f"https://pmc.ncbi.nlm.nih.gov/articles/{paper_id.upper()}/")
    if paper_id.lower().startswith("arx_"):
        add(f"https://arxiv.org/abs/{paper_id[4:]}")
    return targets


def clipboard_ready(
    paperclip_bin: str,
    remote_base: str,
    timeout: int,
    wait_seconds: int,
) -> Tuple[bool, Dict[str, Any], List[Dict[str, Any]]]:
    deadline = time.monotonic() + max(0, wait_seconds)
    polls: List[Dict[str, Any]] = []
    latest_meta: Dict[str, Any] = {}
    while True:
        meta_result = run_capture(
            [paperclip_bin, "cat", f"{remote_base}/meta.json"], timeout
        )
        parsed_meta = json_object_from_output(meta_result.stdout)
        if parsed_meta is not None:
            latest_meta = parsed_meta
        wc_result = run_capture(
            [paperclip_bin, "wc", "-l", f"{remote_base}/content.lines"], timeout
        )
        line_count = (
            parse_expected_lines(wc_result.stdout)
            if wc_result.returncode == 0
            else None
        )
        polls.append(
            {
                "at": utc_now(),
                "metadata_returncode": meta_result.returncode,
                "content_returncode": wc_result.returncode,
                "content_lines": line_count,
                "content_status": first_text(latest_meta.get("content_status")),
                "index_status": first_text(latest_meta.get("index_status")),
            }
        )
        if line_count is not None:
            return True, latest_meta, polls
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False, latest_meta, polls
        time.sleep(min(5.0, remaining))


def fetch_clipboard_paper(
    paperclip_bin: str,
    catalog_row: Dict[str, str],
    paper_id: str,
    method_folder: str,
    paper_dir: Path,
    timeout: int,
    wait_seconds: int,
) -> Dict[str, Any]:
    clipboard_folder = f"/clipboard/paperclip-postsearch/{method_folder}/"
    fetch_path = paper_dir / "fetch.json"
    previous: Dict[str, Any] = {}
    if fetch_path.is_file():
        with contextlib.suppress(OSError, json.JSONDecodeError):
            loaded = read_json(fetch_path)
            if isinstance(loaded, dict):
                previous = loaded

    attempts: List[Dict[str, Any]] = []
    previous_base = first_text(previous.get("clipboard_remote_base"))
    if previous_base:
        ready, clipboard_meta, polls = clipboard_ready(
            paperclip_bin, previous_base, timeout, wait_seconds
        )
        attempts.append(
            {
                "target": first_text(previous.get("selected_target")),
                "reused": True,
                "clipboard_remote_base": previous_base,
                "ready": ready,
                "polls": polls,
            }
        )
        if ready:
            return {
                "status": "ready",
                "selected_target": first_text(previous.get("selected_target")),
                "clipboard_document_id": previous_base.rstrip("/").split("/")[-1],
                "clipboard_remote_base": previous_base,
                "clipboard_folder": clipboard_folder,
                "clipboard_metadata": clipboard_meta,
                "attempts": attempts,
            }

    previous_target = first_text(previous.get("selected_target"))
    for target in fetch_targets(catalog_row, paper_id):
        if previous_base and target == previous_target:
            continue
        try:
            result = run_capture(
                [paperclip_bin, "fetch", target, "--into", clipboard_folder],
                timeout,
            )
        except subprocess.TimeoutExpired:
            attempts.append(
                {"target": target, "reused": False, "status": "timeout"}
            )
            continue
        stdout = result.stdout.decode("utf-8", errors="replace")
        stderr = result.stderr.decode("utf-8", errors="replace")
        combined = f"{stdout}\n{stderr}"
        ids = CLIPBOARD_ID_PATTERN.findall(combined)
        attempt: Dict[str, Any] = {
            "target": target,
            "reused": False,
            "returncode": result.returncode,
            "stdout": stdout.strip(),
            "stderr": stderr.strip(),
        }
        attempts.append(attempt)
        if result.returncode != 0 or not ids:
            continue
        clipboard_id = ids[-1].lower()
        remote_base = f"{clipboard_folder.rstrip('/')}/{clipboard_id}"
        ready, clipboard_meta, polls = clipboard_ready(
            paperclip_bin, remote_base, timeout, wait_seconds
        )
        attempt.update(
            {
                "clipboard_document_id": clipboard_id,
                "clipboard_remote_base": remote_base,
                "ready": ready,
                "polls": polls,
            }
        )
        if ready:
            return {
                "status": "ready",
                "selected_target": target,
                "clipboard_document_id": clipboard_id,
                "clipboard_remote_base": remote_base,
                "clipboard_folder": clipboard_folder,
                "clipboard_metadata": clipboard_meta,
                "attempts": attempts,
            }

    return {
        "status": "unavailable",
        "selected_target": "",
        "clipboard_document_id": "",
        "clipboard_remote_base": "",
        "clipboard_folder": clipboard_folder,
        "clipboard_metadata": {},
        "attempts": attempts,
    }


def combine_metadata(
    paper_id: str,
    catalog_row: Dict[str, str],
    corpus_meta: Dict[str, Any],
    fetch_info: Dict[str, Any],
) -> Dict[str, Any]:
    clipboard_meta = fetch_info.get("clipboard_metadata", {})
    if not isinstance(clipboard_meta, dict):
        clipboard_meta = {}
    normalized = {
        "title": first_text(
            corpus_meta.get("title"),
            catalog_row.get("paper_title"),
            clipboard_meta.get("title"),
        ),
        "authors": first_text(corpus_meta.get("authors")),
        "doi": first_text(corpus_meta.get("doi"), catalog_row.get("doi")),
        "source": first_text(
            corpus_meta.get("journal"),
            corpus_meta.get("source"),
            catalog_row.get("venue"),
        ),
        "date": first_text(
            corpus_meta.get("pub_date"),
            corpus_meta.get("date"),
            catalog_row.get("publication_date"),
            catalog_row.get("publication_year"),
        ),
        "url": first_text(
            catalog_row.get("paper_url"), catalog_row.get("doi_url")
        ),
        "abstract": first_text(
            corpus_meta.get("abstract"), corpus_meta.get("abstract_text")
        ),
    }
    return {
        "paperclip_doc_id": paper_id,
        "normalized": normalized,
        "catalog": agent_catalog_row(catalog_row),
        "corpus": corpus_meta,
        "clipboard": clipboard_meta,
        "acquisition": {
            "status": fetch_info.get("status", "unavailable"),
            "selected_target": fetch_info.get("selected_target", ""),
            "clipboard_document_id": fetch_info.get("clipboard_document_id", ""),
            "clipboard_remote_base": fetch_info.get("clipboard_remote_base", ""),
        },
    }


def extract_urls(values: Iterable[str]) -> List[str]:
    found = set()
    for value in values:
        for match in URL_PATTERN.findall(value):
            url = match.rstrip(TRAILING_URL_PUNCTUATION)
            for opening, closing in (("(", ")"), ("[", "]"), ("{", "}")):
                while url.endswith(closing) and url.count(closing) > url.count(opening):
                    url = url[:-1]
            if url:
                found.add(url)
    return sorted(found)


def extract_labeled_url_evidence(raw: bytes) -> List[Dict[str, Any]]:
    evidence: List[Dict[str, Any]] = []
    seen = set()
    current_label: Optional[int] = None
    decoded = raw.decode("utf-8", errors="replace")
    for physical_line, line in enumerate(decoded.splitlines(), 1):
        label_match = LINE_PATTERN.match(line)
        if label_match:
            current_label = int(label_match.group(1))
            text = label_match.group(2)
        else:
            text = line
        for url in extract_urls([text]):
            if url in seen:
                continue
            seen.add(url)
            evidence.append(
                {
                    "url": url,
                    "paper_line": f"L{current_label}" if current_label else "",
                    "physical_line": physical_line,
                }
            )
    return evidence


def parse_full_text(raw: bytes, expected_lines: Optional[int]) -> Tuple[str, Dict[str, Any]]:
    decoded = raw.decode("utf-8", errors="replace")
    physical_lines = decoded.splitlines()
    labels: List[int] = []
    cleaned: List[str] = []
    continuation_lines: List[int] = []
    unparsed_before_first_label: List[int] = []

    for physical_number, line in enumerate(physical_lines, 1):
        match = LINE_PATTERN.match(line)
        if match:
            labels.append(int(match.group(1)))
            cleaned.append(match.group(2))
        else:
            cleaned.append(line)
            if labels:
                continuation_lines.append(physical_number)
            else:
                unparsed_before_first_label.append(physical_number)

    contiguous = labels == list(range(1, len(labels) + 1))
    # Paperclip's `wc -l` can undercount the virtual records emitted by
    # `cat --full` (observed as exactly one fewer). The complete output's
    # explicit labels are therefore the canonical count.
    cat_full_count = len(labels)
    cat_is_shorter_than_wc = (
        expected_lines is not None and cat_full_count < expected_lines
    )
    valid = (
        bool(raw)
        and not unparsed_before_first_label
        and contiguous
        and not cat_is_shorter_than_wc
    )
    warnings: List[str] = []
    if expected_lines is not None and expected_lines != cat_full_count:
        warnings.append(
            "paperclip wc -l reported "
            f"{expected_lines}, while cat --full emitted {cat_full_count} "
            "contiguous labeled records; cat --full labels are authoritative"
        )
    if continuation_lines:
        warnings.append(
            f"cat --full emitted {len(continuation_lines)} physical continuation "
            "line(s) inside labeled records; preserved verbatim"
        )
    clean_text = "\n".join(cleaned) + ("\n" if physical_lines else "")
    validation = {
        "status": "complete" if valid else "invalid",
        "validation_basis": "contiguous_cat_full_labels",
        "expected_virtual_lines": cat_full_count,
        "wc_reported_newline_count": expected_lines,
        "wc_count_matches_cat_full": expected_lines == cat_full_count,
        "parsed_virtual_lines": cat_full_count,
        "physical_lines": len(physical_lines),
        "first_label": labels[0] if labels else None,
        "last_label": labels[-1] if labels else None,
        "labels_contiguous_from_one": contiguous,
        "continuation_physical_lines": continuation_lines,
        "unparsed_physical_lines": unparsed_before_first_label,
        "warnings": warnings,
        "raw_sha256": sha256_bytes(raw),
        "clean_sha256": sha256_bytes(clean_text.encode("utf-8")),
    }
    return clean_text, validation


def load_state(path: Path, input_file: Path) -> Dict[str, Any]:
    if path.exists():
        state = read_json(path)
        if not isinstance(state, dict) or state.get("schema_version") != 1:
            raise ValueError(f"unsupported or corrupt state file: {path}")
        if not isinstance(state.get("papers"), dict):
            raise ValueError(f"state has no papers object: {path}")
    else:
        state = {
            "schema_version": 1,
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "input_file": str(input_file.resolve()),
            "last_input_ids": [],
            "papers": {},
        }
    return state


def save_state(path: Path, state: Dict[str, Any]) -> None:
    state["updated_at"] = utc_now()
    atomic_write_json(path, state)


def ensure_record(state: Dict[str, Any], paper_id: str, paper_dir: Path, root: Path) -> Dict[str, Any]:
    papers = state["papers"]
    if paper_id not in papers:
        papers[paper_id] = {
            "paper_id": paper_id,
            "status": "queued",
            "attempts": {"extraction": 0, "agent": 0},
            "artifacts": {"paper_directory": str(paper_dir.relative_to(root))},
            "extraction": {},
            "agent": {},
            "analysis": {},
            "errors": [],
        }
    papers[paper_id].setdefault("artifacts", {})["paper_directory"] = str(
        paper_dir.relative_to(root)
    )
    return papers[paper_id]


def add_error(record: Dict[str, Any], phase: str, message: str) -> None:
    record.setdefault("errors", []).append(
        {"at": utc_now(), "phase": phase, "message": message}
    )


def extract_paper(
    paper_id: str,
    paper_dir: Path,
    paperclip_bin: str,
    catalog_row: Dict[str, str],
    method_folder: str,
    source_folder: str,
    timeout: int,
    fetch_wait: int,
    skip_fetch: bool,
) -> Dict[str, Any]:
    paper_dir.mkdir(parents=True, exist_ok=True)
    corpus_base = f"/papers/{paper_id}"

    corpus_meta: Dict[str, Any] = {}
    metadata_error = ""
    try:
        meta_result = run_capture(
            [paperclip_bin, "cat", f"{corpus_base}/meta.json"], timeout
        )
        metadata_error = meta_result.stderr.decode("utf-8", errors="replace").strip()
        if meta_result.returncode == 0:
            parsed = json_object_from_output(meta_result.stdout)
            if parsed is not None:
                corpus_meta = parsed
            else:
                metadata_error = "corpus meta.json was not a JSON object"
    except subprocess.TimeoutExpired:
        metadata_error = f"corpus metadata retrieval timed out after {timeout}s"
    atomic_write_json(paper_dir / "corpus_meta.json", corpus_meta)

    if skip_fetch:
        fetch_info: Dict[str, Any] = {
            "status": "skipped",
            "selected_target": "",
            "clipboard_document_id": "",
            "clipboard_remote_base": "",
            "clipboard_folder": "",
            "clipboard_metadata": {},
            "attempts": [],
        }
    else:
        fetch_info = fetch_clipboard_paper(
            paperclip_bin,
            catalog_row,
            paper_id,
            method_folder,
            paper_dir,
            timeout,
            fetch_wait,
        )
    atomic_write_json(paper_dir / "fetch.json", fetch_info)
    clipboard_meta = fetch_info.get("clipboard_metadata", {})
    if not isinstance(clipboard_meta, dict):
        clipboard_meta = {}
    atomic_write_json(paper_dir / "clipboard_meta.json", clipboard_meta)

    metadata = combine_metadata(paper_id, catalog_row, corpus_meta, fetch_info)
    metadata_status = (
        "available" if any(metadata["normalized"].values()) else "unavailable"
    )
    atomic_write_json(paper_dir / "meta.json", metadata)
    remote_base = first_text(fetch_info.get("clipboard_remote_base")) or corpus_base
    content_origin = "clipboard_fetch" if remote_base != corpus_base else "public_corpus"

    expected_lines = None
    try:
        wc_result = run_capture(
            [paperclip_bin, "wc", "-l", f"{remote_base}/content.lines"], timeout
        )
        if wc_result.returncode == 0:
            expected_lines = parse_expected_lines(wc_result.stdout)
    except subprocess.TimeoutExpired:
        pass

    pdf_status = "unavailable"
    pdf_path = ""
    pdf_temporary = paper_dir / ".paper.pdf.part"
    try:
        find_result = run_capture(
            [paperclip_bin, "find", "*.pdf", f"{remote_base}/"], timeout
        )
        if find_result.returncode == 0:
            listing = find_result.stdout.decode("utf-8", errors="replace")
            remote_match = re.search(
                r"/(?:papers|clipboard)/[^\s]+\.[Pp][Dd][Ff]", listing
            )
            if remote_match:
                with pdf_temporary.open("wb") as output:
                    pdf_result = subprocess.run(
                        [paperclip_bin, "cat", remote_match.group(0)],
                        stdout=output,
                        stderr=subprocess.PIPE,
                        check=False,
                        timeout=timeout,
                    )
                    output.flush()
                    os.fsync(output.fileno())
                if (
                    pdf_result.returncode == 0
                    and pdf_temporary.is_file()
                    and has_pdf_header(pdf_temporary)
                ):
                    os.replace(pdf_temporary, paper_dir / "paper.pdf")
                    pdf_status = "downloaded"
                    pdf_path = f"{source_folder}/paper.pdf"
    except (OSError, subprocess.TimeoutExpired):
        pass
    finally:
        with contextlib.suppress(FileNotFoundError):
            pdf_temporary.unlink()

    # This is deliberately the final Paperclip command for this paper.
    raw_path = paper_dir / "full_text.cat-full.lines"
    temporary = paper_dir / ".full_text.cat-full.lines.part"
    error_path = paper_dir / "full_text.cat-full.error.txt"
    invalid_path = paper_dir / "full_text.cat-full.invalid.lines"
    try:
        with temporary.open("wb") as output:
            cat_result = subprocess.run(
                [paperclip_bin, "cat", "--full", f"{remote_base}/content.lines"],
                stdout=output,
                stderr=subprocess.PIPE,
                check=False,
                timeout=timeout,
            )
            output.flush()
            os.fsync(output.fileno())
    except subprocess.TimeoutExpired as error:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        raise RuntimeError(f"paperclip cat --full timed out after {timeout}s") from error
    if cat_result.returncode != 0 or temporary.stat().st_size == 0:
        diagnostic = temporary.read_bytes() if temporary.is_file() else b""
        stderr = cat_result.stderr.decode("utf-8", errors="replace").strip()
        if stderr:
            diagnostic += (b"\n" if diagnostic else b"") + stderr.encode("utf-8") + b"\n"
        if diagnostic:
            atomic_write_bytes(error_path, diagnostic)
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()
        raise RuntimeError(
            f"paperclip cat --full failed for {remote_base}: "
            f"{stderr or 'empty output'}"
        )

    raw = temporary.read_bytes()
    remote_error = embedded_paperclip_error(raw)
    if remote_error:
        atomic_write_bytes(error_path, raw)
        temporary.unlink()
        raise RuntimeError(
            f"paperclip cat --full remote failure for {remote_base}: {remote_error}"
        )

    clean_text, validation = parse_full_text(raw, expected_lines)
    if validation["status"] != "complete":
        os.replace(temporary, invalid_path)
        atomic_write_json(paper_dir / "extraction.json", validation)
        raise RuntimeError(
            "cat --full content failed line validation: "
            f"parsed={validation['parsed_virtual_lines']} "
            f"expected={validation['expected_virtual_lines']} "
            f"unparsed={len(validation['unparsed_physical_lines'])}"
        )

    os.replace(temporary, raw_path)
    clean_path = paper_dir / "full_text.txt"
    atomic_write_text(clean_path, clean_text)
    link_evidence = extract_labeled_url_evidence(raw)
    urls = [item["url"] for item in link_evidence]
    atomic_write_json(paper_dir / "links.json", urls)
    atomic_write_json(paper_dir / "link_evidence.json", link_evidence)
    github_leads = [
        item for item in link_evidence
        if item["url"].lower().startswith("https://github.com/")
    ]
    atomic_write_text(
        paper_dir / "code_matches.txt",
        "\n".join(f"{item['paper_line']}\t{item['url']}" for item in github_leads)
        + ("\n" if github_leads else ""),
    )

    extraction = {
        **validation,
        "acquisition_version": ACQUISITION_VERSION,
        "extracted_at": utc_now(),
        "content_origin": content_origin,
        "fetch_status": fetch_info.get("status", "unavailable"),
        "fetch_target": fetch_info.get("selected_target", ""),
        "clipboard_document_id": fetch_info.get("clipboard_document_id", ""),
        "clipboard_remote_base": fetch_info.get("clipboard_remote_base", ""),
        "remote_content_path": f"{remote_base}/content.lines",
        "final_paperclip_command": f"paperclip cat --full {remote_base}/content.lines",
        "metadata_status": metadata_status,
        "metadata_error": metadata_error,
        "url_count": len(urls),
        "title": metadata["normalized"]["title"],
        "metadata_path": f"{source_folder}/meta.json" if metadata_status == "available" else "",
        "raw_full_text_path": f"{source_folder}/full_text.cat-full.lines",
        "clean_full_text_path": f"{source_folder}/full_text.txt",
        "full_text_validation_path": f"{source_folder}/extraction.json",
        "code_evidence_path": f"{source_folder}/code_matches.txt",
        "pdf_status": pdf_status,
        "pdf_path": pdf_path,
    }
    atomic_write_json(paper_dir / "extraction.json", extraction)
    return extraction


def render_prompt(
    template_path: Path,
    paper_id: str,
    method_name: str,
    method_folder: str,
    source_folder: str,
) -> str:
    template = template_path.read_text(encoding="utf-8")
    replacements = {
        "{{PAPER_ID}}": paper_id,
        "{{METHOD_NAME}}": method_name,
        "{{METHOD_FOLDER}}": method_folder,
        "{{SOURCE_FOLDER}}": source_folder,
    }
    for marker, replacement in replacements.items():
        if marker not in template:
            raise ValueError(f"prompt template is missing {marker}: {template_path}")
        template = template.replace(marker, replacement)
    return template


def require_keys(value: Dict[str, Any], keys: Iterable[str], where: str) -> None:
    missing = [key for key in keys if key not in value]
    if missing:
        raise ValueError(f"{where} missing fields: {', '.join(missing)}")


def validate_agent_result(
    value: Any,
    paper_id: str,
    method_name: str,
    method_folder: str,
    source_folder: str,
    extraction: Dict[str, Any],
) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("agent result is not a JSON object")
    fields = [
        "title", "authors", "id", "source", "date", "url", "abstract",
        "method_name", "method_folder", "source_folder", "metadata_status",
        "metadata_path", "full_text_status", "raw_full_text_path",
        "clean_full_text_path", "full_text_validation_path",
        "code_evidence_path", "github_flag", "github_candidates",
        "pdf_status", "pdf_path",
    ]
    require_keys(value, fields, "agent result")
    extras = sorted(set(value) - set(fields))
    if extras:
        raise ValueError(f"agent result has unsupported fields: {', '.join(extras)}")
    for field in fields:
        if not isinstance(value[field], str):
            raise ValueError(f"agent result {field} must be a string")
    expected_identity = {
        "id": paper_id,
        "method_name": method_name,
        "method_folder": method_folder,
        "source_folder": source_folder,
    }
    for field, expected in expected_identity.items():
        if value[field] != expected:
            raise ValueError(f"agent result {field}={value[field]!r}, expected {expected!r}")
    deterministic = {
        "metadata_status": extraction["metadata_status"],
        "metadata_path": extraction["metadata_path"],
        "raw_full_text_path": extraction["raw_full_text_path"],
        "clean_full_text_path": extraction["clean_full_text_path"],
        "full_text_validation_path": extraction["full_text_validation_path"],
        "code_evidence_path": extraction["code_evidence_path"],
        "pdf_status": extraction["pdf_status"],
        "pdf_path": extraction["pdf_path"],
    }
    for field, expected in deterministic.items():
        if value[field] != expected:
            raise ValueError(f"agent result {field}={value[field]!r}, expected {expected!r}")
    if value["full_text_status"] not in {"complete", "needs_review"}:
        raise ValueError("agent must mark extracted text complete or needs_review")
    github_flag = value["github_flag"]
    github_url = value["github_candidates"]
    if github_flag == "candidate_found":
        if not re.fullmatch(r"https://github\.com/[^/]+/[^/?#]+", github_url):
            raise ValueError("github_candidates is not one web-verified canonical repository URL")
    elif github_url:
        raise ValueError("unverified github_candidates must be empty")
    return value


def run_agent(
    paper_id: str,
    paper_dir: Path,
    method_name: str,
    method_folder: str,
    source_folder: str,
    codex_bin: str,
    schema_path: Path,
    prompt_path: Path,
    model: str,
    reasoning_effort: str,
    attempt: int,
    timeout: int,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    prompt = render_prompt(
        prompt_path, paper_id, method_name, method_folder, source_folder
    )
    logs_dir = paper_dir / "agent_logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    attempt_stem = f"attempt-{attempt:04d}"
    prompt_log = logs_dir / f"{attempt_stem}.prompt.md"
    events_path = logs_dir / f"{attempt_stem}.events.jsonl"
    stderr_path = logs_dir / f"{attempt_stem}.stderr.log"
    command_log = logs_dir / f"{attempt_stem}.command.json"
    result_part = logs_dir / f"{attempt_stem}.paper.json.part"
    atomic_write_text(prompt_log, prompt)

    command = [
        codex_bin,
        "exec",
        "--ephemeral",
        "--json",
        "--sandbox",
        "read-only",
        "--skip-git-repo-check",
        "--config",
        'web_search="live"',
        "--config",
        f'model_reasoning_effort="{reasoning_effort}"',
        "--output-schema",
        str(schema_path),
        "--output-last-message",
        str(result_part),
        "--cd",
        str(paper_dir),
        "--model",
        model,
    ]
    command.append("-")

    started_at = utc_now()
    process: Optional[subprocess.Popen] = None
    try:
        with events_path.open("wb") as events, stderr_path.open("wb") as errors:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=events,
                stderr=errors,
            )
            atomic_write_json(
                command_log,
                {
                    "paper_id": paper_id,
                    "attempt": attempt,
                    "started_at": started_at,
                    "pid": process.pid,
                    "model": model,
                    "reasoning_effort": reasoning_effort,
                    "sandbox": "read-only",
                    "web_search": "live",
                    "command": command,
                },
            )
            process.communicate(input=prompt.encode("utf-8"), timeout=timeout)
    except subprocess.TimeoutExpired as error:
        if process is not None:
            process.kill()
            process.communicate()
        raise RuntimeError(f"codex exec timed out after {timeout}s") from error

    if process is None:
        raise RuntimeError("codex exec did not start")
    if process.returncode != 0:
        raise RuntimeError(
            f"codex exec exited {process.returncode}; see {stderr_path} and {events_path}"
        )
    if not result_part.is_file():
        raise RuntimeError("codex exec produced no --output-last-message file")
    extraction = read_json(paper_dir / "extraction.json")
    catalog_path = paper_dir / "catalog_row.json"
    try:
        result = validate_agent_result(
            read_json(result_part),
            paper_id,
            method_name,
            method_folder,
            source_folder,
            extraction,
        )
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise RuntimeError(f"invalid schema-constrained agent result: {error}") from error

    result_path = paper_dir / "paper.json"
    os.replace(result_part, result_path)
    agent_meta = {
        "status": "complete",
        "attempt": attempt,
        "started_at": started_at,
        "completed_at": utc_now(),
        "pid": process.pid,
        "input_clean_sha256": extraction["clean_sha256"],
        "input_catalog_sha256": sha256_bytes(catalog_path.read_bytes()),
        "output_contract_version": OUTPUT_CONTRACT_VERSION,
        "output_schema_sha256": sha256_bytes(schema_path.read_bytes()),
        "prompt_sha256": sha256_bytes(prompt_path.read_bytes()),
        "model": model,
        "reasoning_effort": reasoning_effort,
        "web_search": "live",
        "sandbox": "read-only",
        "result_path": "paper.json",
        "logs": {
            "directory": "agent_logs",
            "prompt": f"agent_logs/{prompt_log.name}",
            "events": f"agent_logs/{events_path.name}",
            "stderr": f"agent_logs/{stderr_path.name}",
            "command": f"agent_logs/{command_log.name}",
        },
    }
    return result, agent_meta


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Post-process a selected-paper CSV with a resumable Codex audit."
    )
    result.add_argument(
        "--csv",
        "--input-csv",
        dest="csv_path",
        type=Path,
        default=DEFAULT_CSV,
        help=(
            "catalog CSV containing paperclip_doc_id or doc_id; an optional "
            f"search_reachable column can exclude rows (default: {DEFAULT_CSV})"
        ),
    )
    result.add_argument(
        "--max-rows",
        "--limit",
        dest="max_rows",
        type=int,
        metavar="N",
        help="process only the first N eligible rows from the CSV",
    )
    result.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"output directory (default: {DEFAULT_OUTPUT})",
    )
    result.add_argument(
        "--paperclip-bin",
        default=os.environ.get("PAPERCLIP_BIN", DEFAULT_PAPERCLIP),
    )
    result.add_argument("--codex-bin", default=os.environ.get("CODEX_BIN", "codex"))
    result.add_argument(
        "--schema", type=Path, default=SCRIPT_DIR / "paperclip_postsearch.schema.json"
    )
    result.add_argument(
        "--prompt",
        type=Path,
        default=SCRIPT_DIR / "prompts" / "paperclip_postsearch_prompt.md",
    )
    result.add_argument(
        "--model",
        default=os.environ.get("PAPERCLIP_AGENT_MODEL") or DEFAULT_AGENT_MODEL,
    )
    result.add_argument(
        "--reasoning-effort",
        choices=("none", "minimal", "low", "medium", "high", "xhigh", "max"),
        default=(
            os.environ.get("PAPERCLIP_AGENT_REASONING")
            or DEFAULT_REASONING_EFFORT
        ),
    )
    result.add_argument("--paperclip-timeout", type=int, default=300)
    result.add_argument(
        "--fetch-wait",
        type=int,
        default=os.environ.get("PAPERCLIP_FETCH_WAIT", "180"),
        help="seconds to wait for each fetched clipboard document to finish parsing",
    )
    result.add_argument(
        "--skip-fetch",
        action="store_true",
        default=os.environ.get("PAPERCLIP_SKIP_FETCH", "").lower()
        in {"1", "true", "yes"},
        help="skip DOI/URL fetch and use the existing public-corpus document ID",
    )
    result.add_argument("--agent-timeout", type=int, default=1800)
    result.add_argument("--force-extract", action="store_true")
    result.add_argument("--force-agent", action="store_true")
    result.add_argument(
        "--extract-only",
        action="store_true",
        help="fetch and validate evidence but do not run Codex",
    )
    return result


def main() -> int:
    args = parser().parse_args()
    try:
        if args.max_rows is not None and args.max_rows < 1:
            raise ValueError("--max-rows/--limit must be at least 1")
        paperclip_bin = resolve_binary(args.paperclip_bin)
        codex_bin = ""
        if not args.extract_only:
            codex_bin = resolve_binary(args.codex_bin)
        schema_path = args.schema.expanduser().resolve()
        prompt_path = args.prompt.expanduser().resolve()
        if not schema_path.is_file() or not prompt_path.is_file():
            raise FileNotFoundError("schema or prompt template does not exist")
        catalog_rows, skipped_rows = read_catalog_csv(args.csv_path.expanduser())
        eligible_rows = len(catalog_rows)
        if args.max_rows is not None:
            catalog_rows = catalog_rows[: args.max_rows]
        ids = [row["paperclip_doc_id"] for row in catalog_rows]
    except (FileNotFoundError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    output_root = args.output.expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    state_path = output_root / "state.json"
    lock_path = output_root / ".state.lock"
    failures = 0
    agent_queue: List[Tuple[str, Path, str, str, str, int]] = []

    with lock_path.open("a+") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"error: another post-search process holds {lock_path}", file=sys.stderr)
            return 2

        try:
            state = load_state(state_path, args.csv_path)
        except (OSError, json.JSONDecodeError, ValueError) as error:
            print(f"error: {error}", file=sys.stderr)
            return 2
        state["input_file"] = str(args.csv_path.expanduser().resolve())
        state["input_eligible_rows"] = eligible_rows
        state.pop("input_reachable_rows", None)
        state["row_limit"] = args.max_rows
        state["last_input_ids"] = ids
        state["last_input_rows"] = [
            {
                "paperclip_doc_id": row["paperclip_doc_id"],
                "model_name": row.get("model_name", ""),
                "paper_title": row.get("paper_title", ""),
            }
            for row in catalog_rows
        ]
        state["skipped_input_rows"] = skipped_rows
        for row in catalog_rows:
            paper_id = row["paperclip_doc_id"]
            method_name, method_folder = method_identity(row, paper_id)
            source_folder = f"{method_folder}/sources/{directory_name(paper_id)}"
            paper_dir = output_root / source_folder
            record = ensure_record(state, paper_id, paper_dir, output_root)
            previous_source_folder = record.get("source_folder", "")
            if previous_source_folder and previous_source_folder != source_folder:
                record["status"] = "queued"
                record["extraction"] = {}
                record["agent"] = {}
                record["analysis"] = {}
                record["artifacts"] = {
                    "paper_directory": str(paper_dir.relative_to(output_root))
                }
            atomic_write_json(paper_dir / "catalog_row.json", agent_catalog_row(row))
            record["catalog"] = agent_catalog_row(row)
            record["method_name"] = method_name
            record["method_folder"] = method_folder
            record["source_folder"] = source_folder
            record["artifacts"]["catalog_row"] = str(
                (paper_dir / "catalog_row.json").relative_to(output_root)
            )
        save_state(state_path, state)

        loaded_summary = f"Loaded {len(ids)} paper(s)"
        if len(ids) < eligible_rows:
            loaded_summary += f" of {eligible_rows} (--max-rows {args.max_rows})"
        print(
            f"{loaded_summary} from {args.csv_path}; "
            f"skipped {len(skipped_rows)} row(s) marked search_reachable=false"
        )
        print(f"State: {state_path}")
        for index, catalog_row in enumerate(catalog_rows, 1):
            paper_id = catalog_row["paperclip_doc_id"]
            method_name, method_folder = method_identity(catalog_row, paper_id)
            source_folder = f"{method_folder}/sources/{directory_name(paper_id)}"
            paper_dir = output_root / source_folder
            record = ensure_record(state, paper_id, paper_dir, output_root)
            print(f"[{index}/{len(ids)}] {paper_id} -> {source_folder}")

            extraction = record.get("extraction", {})
            extraction_complete = (
                extraction.get("status") == "complete"
                and extraction.get("acquisition_version") == ACQUISITION_VERSION
                and (paper_dir / "full_text.cat-full.lines").is_file()
                and (paper_dir / "full_text.txt").is_file()
                and (paper_dir / "extraction.json").is_file()
            )
            if args.force_extract or not extraction_complete:
                record["status"] = "extracting"
                record["attempts"]["extraction"] += 1
                save_state(state_path, state)
                try:
                    if args.skip_fetch:
                        print("  acquisition: public corpus (--skip-fetch)")
                    else:
                        print("  acquisition: fetch DOI/URL into Paperclip clipboard first")
                    extraction = extract_paper(
                        paper_id,
                        paper_dir,
                        paperclip_bin,
                        catalog_row,
                        method_folder,
                        source_folder,
                        args.paperclip_timeout,
                        args.fetch_wait,
                        args.skip_fetch,
                    )
                    record["extraction"] = extraction
                    record["artifacts"].update(
                        {
                            "metadata": str((paper_dir / "meta.json").relative_to(output_root)),
                            "corpus_metadata": str(
                                (paper_dir / "corpus_meta.json").relative_to(output_root)
                            ),
                            "clipboard_metadata": str(
                                (paper_dir / "clipboard_meta.json").relative_to(output_root)
                            ),
                            "fetch": str(
                                (paper_dir / "fetch.json").relative_to(output_root)
                            ),
                            "raw_full_text": str(
                                (paper_dir / "full_text.cat-full.lines").relative_to(output_root)
                            ),
                            "clean_full_text": str(
                                (paper_dir / "full_text.txt").relative_to(output_root)
                            ),
                            "extraction": str(
                                (paper_dir / "extraction.json").relative_to(output_root)
                            ),
                            "links": str((paper_dir / "links.json").relative_to(output_root)),
                            "link_evidence": str(
                                (paper_dir / "link_evidence.json").relative_to(output_root)
                            ),
                            "code_evidence": str(
                                (paper_dir / "code_matches.txt").relative_to(output_root)
                            ),
                        }
                    )
                    if extraction["pdf_path"]:
                        record["artifacts"]["pdf"] = extraction["pdf_path"]
                    record["status"] = "extracted"
                    print(f"  final Paperclip command: {extraction['final_paperclip_command']}")
                    print(
                        f"  extracted {extraction['parsed_virtual_lines']} virtual lines; "
                        f"source={extraction['content_origin']}; "
                        f"found {extraction['url_count']} URL(s)"
                    )
                    for warning in extraction.get("warnings", []):
                        print(f"  extraction warning: {warning}")
                except (OSError, subprocess.SubprocessError, RuntimeError) as error:
                    record["status"] = "extraction_failed"
                    add_error(record, "extraction", str(error))
                    save_state(state_path, state)
                    failures += 1
                    print(f"  extraction failed: {error}", file=sys.stderr)
                    continue
                save_state(state_path, state)
            else:
                print("  extraction already complete; reusing it")

            if args.extract_only:
                continue

            clean_sha = record["extraction"].get("clean_sha256", "")
            catalog_sha = sha256_bytes((paper_dir / "catalog_row.json").read_bytes())
            prior_agent = record.get("agent", {})
            agent_complete = (
                record.get("status") == "complete"
                and prior_agent.get("input_clean_sha256") == clean_sha
                and prior_agent.get("input_catalog_sha256") == catalog_sha
                and prior_agent.get("model") == args.model
                and prior_agent.get("reasoning_effort") == args.reasoning_effort
                and prior_agent.get("output_contract_version") == OUTPUT_CONTRACT_VERSION
                and prior_agent.get("output_schema_sha256")
                == sha256_bytes(schema_path.read_bytes())
                and prior_agent.get("prompt_sha256")
                == sha256_bytes(prompt_path.read_bytes())
                and (paper_dir / "paper.json").is_file()
            )
            if args.force_agent or not agent_complete:
                record["status"] = "agent_running"
                record["attempts"]["agent"] += 1
                attempt = record["attempts"]["agent"]
                record["agent"] = {
                    "status": "queued",
                    "attempt": attempt,
                    "queued_at": utc_now(),
                    "model": args.model,
                    "reasoning_effort": args.reasoning_effort,
                    "web_search": "live",
                    "sandbox": "read-only",
                    "logs": {
                        "directory": "agent_logs",
                        "prompt": f"agent_logs/attempt-{attempt:04d}.prompt.md",
                        "events": f"agent_logs/attempt-{attempt:04d}.events.jsonl",
                        "stderr": f"agent_logs/attempt-{attempt:04d}.stderr.log",
                        "command": f"agent_logs/attempt-{attempt:04d}.command.json",
                    },
                }
                record["artifacts"]["agent_logs"] = str(
                    (paper_dir / "agent_logs").relative_to(output_root)
                )
                agent_queue.append(
                    (
                        paper_id,
                        paper_dir,
                        method_name,
                        method_folder,
                        source_folder,
                        attempt,
                    )
                )
                save_state(state_path, state)
                print(
                    "  queued background Codex agent: "
                    f"{args.model} ({args.reasoning_effort}), attempt {attempt}"
                )
            else:
                print("  agent result already complete for this extraction; skipping")

        if agent_queue:
            print(
                f"Launching {len(agent_queue)} background agent(s) concurrently: "
                f"{args.model} ({args.reasoning_effort})"
            )
            futures: Dict[Future, Tuple[str, Path]] = {}
            with ThreadPoolExecutor(
                max_workers=len(agent_queue), thread_name_prefix="paper-agent"
            ) as executor:
                for (
                    paper_id,
                    paper_dir,
                    method_name,
                    method_folder,
                    source_folder,
                    attempt,
                ) in agent_queue:
                    future = executor.submit(
                        run_agent,
                        paper_id,
                        paper_dir,
                        method_name,
                        method_folder,
                        source_folder,
                        codex_bin,
                        schema_path,
                        prompt_path,
                        args.model,
                        args.reasoning_effort,
                        attempt,
                        args.agent_timeout,
                    )
                    futures[future] = (paper_id, paper_dir)
                    print(
                        f"  launched {paper_id}; logs: "
                        f"{paper_dir / 'agent_logs'}"
                    )

                for future in as_completed(futures):
                    paper_id, paper_dir = futures[future]
                    record = state["papers"][paper_id]
                    try:
                        analysis, agent_meta = future.result()
                        record["analysis"] = analysis
                        record["agent"] = agent_meta
                        record["artifacts"]["paper_json"] = str(
                            (paper_dir / "paper.json").relative_to(output_root)
                        )
                        record["status"] = "complete"
                        print(
                            f"  completed {paper_id}: "
                            f"GitHub={analysis['github_flag']}"
                        )
                    except (
                        OSError,
                        subprocess.SubprocessError,
                        RuntimeError,
                        ValueError,
                    ) as error:
                        record["status"] = "agent_failed"
                        record.setdefault("agent", {})["status"] = "failed"
                        record["agent"]["failed_at"] = utc_now()
                        add_error(record, "agent", str(error))
                        failures += 1
                        print(f"  agent failed for {paper_id}: {error}", file=sys.stderr)
                    save_state(state_path, state)

    if failures:
        print(f"Finished with {failures} failed paper(s). Re-run to resume.", file=sys.stderr)
        return 1
    print("Finished successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
