import csv
import hmac
import hashlib
import json
import mimetypes
import os
import socket
import sqlite3
import base64
import urllib.request
from http import cookies
from collections import defaultdict
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from io import BytesIO
from urllib.parse import parse_qs, quote, urlencode, urlparse

import qrcode


APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
CONFIG_PATH = APP_DIR / "config.json"
DEFAULT_LOCAL_OUTPUTS_DIR = Path(r"C:\Users\rhufc\OneDrive\JCMS\Flags of Geary County\outputs")
DATA_DIR = Path(os.environ.get("ROUTE_APP_DATA_DIR", str(APP_DIR / "data"))).expanduser()
OUTPUTS_DIR = Path(os.environ.get("ROUTE_OUTPUTS_DIR", str(DATA_DIR / "outputs"))).expanduser()
STATUS_DB_PATH = DATA_DIR / "flag_status.sqlite3"
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8042"))
ASSET_VERSION = "20260705d"


def route_output_dirs() -> list[Path]:
    dirs: list[Path] = []
    preferred = [OUTPUTS_DIR]
    if str(DEFAULT_LOCAL_OUTPUTS_DIR) != str(OUTPUTS_DIR):
        preferred.append(DEFAULT_LOCAL_OUTPUTS_DIR)
    for candidate in preferred:
        expanded = Path(candidate).expanduser()
        if expanded not in dirs:
            dirs.append(expanded)
    return dirs


def load_app_config() -> dict:
    config = {
        "admin_password": "gearyflags",
        "runner_secret": "change-this-runner-secret",
        "public_base_url": "",
        "sms_provider": "",
        "sms_to_number": "",
        "twilio_account_sid": "",
        "twilio_auth_token": "",
        "twilio_from_number": "",
    }
    if CONFIG_PATH.is_file():
        try:
            loaded = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                config.update({k: v for k, v in loaded.items() if isinstance(v, str)})
        except Exception:
            pass
    if os.environ.get("ROUTE_APP_PASSWORD"):
        config["admin_password"] = os.environ["ROUTE_APP_PASSWORD"]
    if os.environ.get("RUNNER_SECRET"):
        config["runner_secret"] = os.environ["RUNNER_SECRET"]
    if os.environ.get("PUBLIC_BASE_URL"):
        config["public_base_url"] = os.environ["PUBLIC_BASE_URL"]
    return config


def latest_links_csv() -> Path | None:
    patterns = [
        "flags_google_maps_links_*.csv",
        "flags_google_maps_links.csv",
    ]
    candidates: list[Path] = []
    for output_dir in route_output_dirs():
        for pattern in patterns:
            candidates.extend(output_dir.glob(pattern))
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def latest_manifest_json() -> Path | None:
    patterns = [
        "flags_route_manifest*.json",
        "flags_route_manifest.json",
    ]
    candidates: list[Path] = []
    for output_dir in route_output_dirs():
        for pattern in patterns:
            candidates.extend(output_dir.glob(pattern))
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def parse_run_label(path: Path) -> str:
    stem = path.stem
    parts = stem.rsplit("_", 2)
    if len(parts) == 3 and parts[-2].isdigit() and parts[-1].isdigit():
        raw = f"{parts[-2]} {parts[-1]}"
        try:
            return datetime.strptime(raw, "%Y%m%d %H%M%S").strftime("%B %d, %Y %I:%M %p")
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%B %d, %Y %I:%M %p")


def normalize_runner(text: str) -> str:
    return " ".join(str(text).strip().lower().split())


def runner_token(runner: str) -> str:
    secret = load_app_config().get("runner_secret", "")
    message = normalize_runner(runner).encode("utf-8")
    return hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()[:24]


def valid_runner_token(runner: str, token: str) -> bool:
    if not runner or not token:
        return False
    expected = runner_token(runner)
    return hmac.compare_digest(expected, token.strip())


def ensure_status_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(STATUS_DB_PATH) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS stop_status (
                run_id TEXT NOT NULL,
                stop_id TEXT NOT NULL,
                install_status TEXT NOT NULL DEFAULT 'pending',
                install_at TEXT NOT NULL DEFAULT '',
                install_note TEXT NOT NULL DEFAULT '',
                install_note_at TEXT NOT NULL DEFAULT '',
                install_note_resolved INTEGER NOT NULL DEFAULT 0,
                install_note_resolved_at TEXT NOT NULL DEFAULT '',
                install_note_resolved_by TEXT NOT NULL DEFAULT '',
                install_by TEXT NOT NULL DEFAULT '',
                pickup_status TEXT NOT NULL DEFAULT 'pending',
                pickup_at TEXT NOT NULL DEFAULT '',
                pickup_note TEXT NOT NULL DEFAULT '',
                pickup_note_at TEXT NOT NULL DEFAULT '',
                pickup_note_resolved INTEGER NOT NULL DEFAULT 0,
                pickup_note_resolved_at TEXT NOT NULL DEFAULT '',
                pickup_note_resolved_by TEXT NOT NULL DEFAULT '',
                pickup_by TEXT NOT NULL DEFAULT '',
                PRIMARY KEY (run_id, stop_id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notification_log (
                event_key TEXT PRIMARY KEY,
                created_at TEXT NOT NULL DEFAULT ''
            )
            """
        )
        existing_cols = {
            row[1]
            for row in conn.execute("PRAGMA table_info(stop_status)").fetchall()
        }
        if "install_by" not in existing_cols:
            conn.execute("ALTER TABLE stop_status ADD COLUMN install_by TEXT NOT NULL DEFAULT ''")
        if "pickup_by" not in existing_cols:
            conn.execute("ALTER TABLE stop_status ADD COLUMN pickup_by TEXT NOT NULL DEFAULT ''")
        if "install_note_at" not in existing_cols:
            conn.execute("ALTER TABLE stop_status ADD COLUMN install_note_at TEXT NOT NULL DEFAULT ''")
        if "pickup_note_at" not in existing_cols:
            conn.execute("ALTER TABLE stop_status ADD COLUMN pickup_note_at TEXT NOT NULL DEFAULT ''")
        if "install_note_resolved" not in existing_cols:
            conn.execute("ALTER TABLE stop_status ADD COLUMN install_note_resolved INTEGER NOT NULL DEFAULT 0")
        if "install_note_resolved_at" not in existing_cols:
            conn.execute("ALTER TABLE stop_status ADD COLUMN install_note_resolved_at TEXT NOT NULL DEFAULT ''")
        if "install_note_resolved_by" not in existing_cols:
            conn.execute("ALTER TABLE stop_status ADD COLUMN install_note_resolved_by TEXT NOT NULL DEFAULT ''")
        if "pickup_note_resolved" not in existing_cols:
            conn.execute("ALTER TABLE stop_status ADD COLUMN pickup_note_resolved INTEGER NOT NULL DEFAULT 0")
        if "pickup_note_resolved_at" not in existing_cols:
            conn.execute("ALTER TABLE stop_status ADD COLUMN pickup_note_resolved_at TEXT NOT NULL DEFAULT ''")
        if "pickup_note_resolved_by" not in existing_cols:
            conn.execute("ALTER TABLE stop_status ADD COLUMN pickup_note_resolved_by TEXT NOT NULL DEFAULT ''")
        conn.commit()


def notification_event_sent(event_key: str) -> bool:
    ensure_status_db()
    with sqlite3.connect(STATUS_DB_PATH) as conn:
        row = conn.execute(
            "SELECT 1 FROM notification_log WHERE event_key = ?",
            (event_key,),
        ).fetchone()
    return row is not None


def record_notification_event(event_key: str) -> None:
    ensure_status_db()
    with sqlite3.connect(STATUS_DB_PATH) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO notification_log (event_key, created_at)
            VALUES (?, ?)
            """,
            (event_key, datetime.now().isoformat(timespec="seconds")),
        )
        conn.commit()


def load_status_map(run_id: str) -> dict[str, dict]:
    ensure_status_db()
    with sqlite3.connect(STATUS_DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT stop_id, install_status, install_at, install_note, install_note_at,
                   install_note_resolved, install_note_resolved_at, install_note_resolved_by, install_by,
                   pickup_status, pickup_at, pickup_note, pickup_note_at,
                   pickup_note_resolved, pickup_note_resolved_at, pickup_note_resolved_by, pickup_by
            FROM stop_status
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchall()
    return {row["stop_id"]: dict(row) for row in rows}


def save_stop_status(run_id: str, stop_id: str, phase: str, status: str, note: str, updated_by: str) -> None:
    ensure_status_db()
    field_map = {
        "install": ("install_status", "install_at", "install_note", "install_by"),
        "pickup": ("pickup_status", "pickup_at", "pickup_note", "pickup_by"),
    }
    status_field, time_field, note_field, actor_field = field_map[phase]
    if status == "pending":
        timestamp = ""
        stored_note = ""
        stored_actor = ""
    else:
        timestamp = datetime.now().isoformat(timespec="seconds")
        stored_note = note.strip()
        stored_actor = updated_by.strip()
    with sqlite3.connect(STATUS_DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO stop_status (run_id, stop_id)
            VALUES (?, ?)
            ON CONFLICT(run_id, stop_id) DO NOTHING
            """,
            (run_id, stop_id),
        )
        conn.execute(
            f"""
            UPDATE stop_status
            SET {status_field} = ?,
                {time_field} = ?,
                {note_field} = ?,
                {actor_field} = ?
            WHERE run_id = ? AND stop_id = ?
            """,
            (status, timestamp, stored_note, stored_actor, run_id, stop_id),
        )
        conn.commit()


def save_stop_note(run_id: str, stop_id: str, phase: str, note: str) -> None:
    ensure_status_db()
    field_map = {
        "install": ("install_note", "install_note_at", "install_note_resolved", "install_note_resolved_at", "install_note_resolved_by"),
        "pickup": ("pickup_note", "pickup_note_at", "pickup_note_resolved", "pickup_note_resolved_at", "pickup_note_resolved_by"),
    }
    note_field, time_field, resolved_field, resolved_at_field, resolved_by_field = field_map[phase]
    note_text = note.strip()
    timestamp = datetime.now().isoformat(timespec="seconds") if note_text else ""
    resolved_value = 0
    resolved_at = ""
    resolved_by = ""
    with sqlite3.connect(STATUS_DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO stop_status (run_id, stop_id)
            VALUES (?, ?)
            ON CONFLICT(run_id, stop_id) DO NOTHING
            """,
            (run_id, stop_id),
        )
        conn.execute(
            f"""
            UPDATE stop_status
            SET {note_field} = ?,
                {time_field} = ?,
                {resolved_field} = ?,
                {resolved_at_field} = ?,
                {resolved_by_field} = ?
            WHERE run_id = ? AND stop_id = ?
            """,
            (note_text, timestamp, resolved_value, resolved_at, resolved_by, run_id, stop_id),
        )
        conn.commit()


def save_issue_resolution(run_id: str, stop_id: str, phase: str, resolved: bool, resolved_by: str) -> None:
    ensure_status_db()
    field_map = {
        "install": ("install_note", "install_note_resolved", "install_note_resolved_at", "install_note_resolved_by"),
        "pickup": ("pickup_note", "pickup_note_resolved", "pickup_note_resolved_at", "pickup_note_resolved_by"),
    }
    note_field, resolved_field, resolved_at_field, resolved_by_field = field_map[phase]
    timestamp = datetime.now().isoformat(timespec="seconds") if resolved else ""
    actor = resolved_by.strip() if resolved else ""
    resolved_flag = 1 if resolved else 0
    with sqlite3.connect(STATUS_DB_PATH) as conn:
        conn.execute(
            """
            INSERT INTO stop_status (run_id, stop_id)
            VALUES (?, ?)
            ON CONFLICT(run_id, stop_id) DO NOTHING
            """,
            (run_id, stop_id),
        )
        conn.execute(
            f"""
            UPDATE stop_status
            SET {resolved_field} = CASE WHEN TRIM({note_field}) <> '' THEN ? ELSE 0 END,
                {resolved_at_field} = CASE WHEN TRIM({note_field}) <> '' THEN ? ELSE '' END,
                {resolved_by_field} = CASE WHEN TRIM({note_field}) <> '' THEN ? ELSE '' END
            WHERE run_id = ? AND stop_id = ?
            """,
            (resolved_flag, timestamp, actor, run_id, stop_id),
        )
        conn.commit()


def load_manifest_data() -> dict | None:
    manifest_path = latest_manifest_json()
    if manifest_path is None:
        return None
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["_source_file"] = str(manifest_path)
    return data


def load_route_links(runner_filter: str = "") -> dict:
    csv_path = latest_links_csv()
    if csv_path is None:
        return {
            "generated_at": None,
            "source_file": None,
            "zone_count": 0,
            "segment_count": 0,
            "zones": [],
        }

    zones: dict[int, list[dict]] = defaultdict(list)
    wanted_runner = normalize_runner(runner_filter) if runner_filter else ""
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            zone = int(row.get("Zone", "0") or 0)
            runner = row.get("Runner", "").strip()
            if wanted_runner and normalize_runner(runner) != wanted_runner:
                continue
            segment = {
                "segment": int(row.get("Segment", "0") or 0),
                "runner": runner,
                "start_stop": row.get("Start_Stop", ""),
                "end_stop": row.get("End_Stop", ""),
                "stops_in_segment": row.get("Stops_In_Segment", ""),
                "link": row.get("Link", ""),
            }
            zones[zone].append(segment)

    zone_list = []
    segment_total = 0
    for zone in sorted(zones):
        segments = sorted(zones[zone], key=lambda item: item["segment"])
        segment_total += len(segments)
        runner_name = next((item["runner"] for item in segments if item["runner"]), "")
        title = f"{runner_name} - Zone {zone}" if runner_name else f"Zone {zone}"
        zone_list.append(
            {
                "zone": zone,
                "title": title,
                "runner": runner_name,
                "segment_count": len(segments),
                "segments": segments,
            }
        )

    return {
        "generated_at": parse_run_label(csv_path),
        "source_file": str(csv_path),
        "runner_filter": runner_filter.strip(),
        "zone_count": len(zone_list),
        "segment_count": segment_total,
        "zones": zone_list,
    }


def default_stop_status() -> dict:
    return {
        "install_status": "pending",
        "install_at": "",
        "install_note": "",
        "install_note_at": "",
        "install_note_resolved": 0,
        "install_note_resolved_at": "",
        "install_note_resolved_by": "",
        "install_by": "",
        "pickup_status": "pending",
        "pickup_at": "",
        "pickup_note": "",
        "pickup_note_at": "",
        "pickup_note_resolved": 0,
        "pickup_note_resolved_at": "",
        "pickup_note_resolved_by": "",
        "pickup_by": "",
    }


def summarize_stops(stops: list[dict]) -> dict:
    total = len(stops)
    install_recorded = sum(1 for stop in stops if stop["install_status"] == "installed")
    install_not = total - install_recorded
    install_pending = total - install_recorded
    pickup_done = sum(
        1 for stop in stops
        if stop["install_status"] == "installed" and stop["pickup_status"] == "picked_up"
    )
    currently_out = sum(
        1 for stop in stops
        if stop["install_status"] == "installed" and stop["pickup_status"] != "picked_up"
    )
    return {
        "total": total,
        "install_installed": currently_out,
        "install_recorded": install_recorded,
        "install_not_installed": install_not,
        "install_pending": install_pending,
        "pickup_picked_up": pickup_done,
        "pickup_not_picked_up": currently_out,
        "pickup_pending": currently_out,
    }


def build_issue_lists(zones: list[dict]) -> tuple[list[dict], list[dict]]:
    open_issues: list[dict] = []
    closed_issues: list[dict] = []
    for zone in zones:
        for stop in zone.get("stops", []):
            install_note = str(stop.get("install_note", "")).strip()
            if install_note:
                issue = {
                    "runner": zone.get("runner", ""),
                    "zone": zone.get("zone", ""),
                    "address": stop.get("address", ""),
                    "issue_text": install_note,
                    "phase": "emplace",
                    "timestamp": stop.get("install_note_at", ""),
                    "stop_id": stop.get("stop_id", ""),
                    "resolved": bool(stop.get("install_note_resolved")),
                    "resolved_at": stop.get("install_note_resolved_at", ""),
                    "resolved_by": stop.get("install_note_resolved_by", ""),
                }
                (closed_issues if issue["resolved"] else open_issues).append(issue)
            pickup_note = str(stop.get("pickup_note", "")).strip()
            if pickup_note:
                issue = {
                    "runner": zone.get("runner", ""),
                    "zone": zone.get("zone", ""),
                    "address": stop.get("address", ""),
                    "issue_text": pickup_note,
                    "phase": "pickup",
                    "timestamp": stop.get("pickup_note_at", ""),
                    "stop_id": stop.get("stop_id", ""),
                    "resolved": bool(stop.get("pickup_note_resolved")),
                    "resolved_at": stop.get("pickup_note_resolved_at", ""),
                    "resolved_by": stop.get("pickup_note_resolved_by", ""),
                }
                (closed_issues if issue["resolved"] else open_issues).append(issue)
    open_issues.sort(key=lambda item: item.get("timestamp", ""), reverse=True)
    closed_issues.sort(key=lambda item: item.get("resolved_at") or item.get("timestamp", ""), reverse=True)
    return open_issues, closed_issues


def build_app_state(runner_filter: str = "", include_runner_links: bool = False) -> dict:
    manifest = load_manifest_data()
    if manifest is None:
        return {
            "generated_at": None,
            "source_file": None,
            "manifest_file": None,
            "run_id": "",
            "pickup_date": "",
            "return_date": "",
            "runner_filter": runner_filter.strip(),
            "zone_count": 0,
            "segment_count": 0,
            "zones": [],
            "summary": summarize_stops([]),
            "open_issues": [],
            "closed_issues": [],
        }

    link_data = load_route_links(runner_filter)
    link_by_zone = {zone["zone"]: zone["segments"] for zone in link_data["zones"]}
    status_map = load_status_map(manifest.get("run_id", ""))
    wanted_runner = normalize_runner(runner_filter) if runner_filter else ""

    zones = []
    all_stops: list[dict] = []
    segment_total = 0
    for zone in manifest.get("zones", []):
        runner_name = zone.get("runner", "")
        if wanted_runner and normalize_runner(runner_name) != wanted_runner:
            continue
        stops = []
        for stop in zone.get("stops", []):
            merged = dict(stop)
            merged.update(default_stop_status())
            merged.update(status_map.get(stop.get("stop_id", ""), {}))
            stops.append(merged)
        summary = summarize_stops(stops)
        zone_id = int(zone.get("zone", 0) or 0)
        segments = link_by_zone.get(zone_id, [])
        segment_total += len(segments)
        zones.append(
            {
                "zone": zone_id,
                "title": f"{runner_name} - Zone {zone_id}" if runner_name else f"Zone {zone_id}",
                "runner": runner_name,
                "runner_access_token": runner_token(runner_name) if include_runner_links and runner_name else "",
                "segment_count": len(segments),
                "segments": segments,
                "stops": stops,
                "summary": summary,
            }
        )
        all_stops.extend(stops)

    open_issues, closed_issues = build_issue_lists(zones)

    return {
        "generated_at": manifest.get("generated_at", "") or link_data.get("generated_at"),
        "source_file": link_data.get("source_file"),
        "manifest_file": manifest.get("_source_file"),
        "run_id": manifest.get("run_id", ""),
        "pickup_date": manifest.get("pickup_date", ""),
        "return_date": manifest.get("return_date", ""),
        "runner_filter": runner_filter.strip(),
        "zone_count": len(zones),
        "segment_count": segment_total,
        "zones": zones,
        "summary": summarize_stops(all_stops),
        "open_issues": open_issues,
        "closed_issues": closed_issues,
    }


def build_public_runner_entries() -> list[dict]:
    state = build_app_state(include_runner_links=True)
    entries: list[dict] = []
    seen: set[str] = set()
    for zone in state.get("zones", []):
        runner = str(zone.get("runner", "")).strip()
        token = str(zone.get("runner_access_token", "")).strip()
        if not runner or not token:
            continue
        key = normalize_runner(runner)
        if key in seen:
            continue
        seen.add(key)
        entries.append(
            {
                "runner": runner,
                "zone": zone.get("zone", ""),
                "stop_count": len(zone.get("stops", []) or []),
                "flag_count": sum(
                    int(stop.get("number_of_flags", 1) or 1)
                    for stop in (zone.get("stops", []) or [])
                ),
                "link": f"/runner?runner={quote(runner)}&access={quote(token)}",
            }
        )
    return entries


def zone_is_complete(zone: dict, phase: str) -> bool:
    stops = zone.get("stops", []) or []
    if not stops:
        return False
    if phase == "install":
        return all(stop.get("install_status") == "installed" for stop in stops)
    if phase == "pickup":
        installed_stops = [stop for stop in stops if stop.get("install_status") == "installed"]
        return bool(installed_stops) and all(
            stop.get("pickup_status") == "picked_up" for stop in installed_stops
        )
    return False


def twilio_ready(config: dict) -> bool:
    return all(
        str(config.get(key, "")).strip()
        for key in (
            "sms_provider",
            "sms_to_number",
            "twilio_account_sid",
            "twilio_auth_token",
            "twilio_from_number",
        )
    ) and str(config.get("sms_provider", "")).strip().lower() == "twilio"


def send_sms_notification(message: str) -> tuple[bool, str]:
    config = load_app_config()
    if not twilio_ready(config):
        return False, "SMS not configured"

    account_sid = config["twilio_account_sid"].strip()
    auth_token = config["twilio_auth_token"].strip()
    from_number = config["twilio_from_number"].strip()
    to_numbers = [item.strip() for item in config["sms_to_number"].split(",") if item.strip()]
    if not to_numbers:
        return False, "No SMS recipients configured"

    last_error = ""
    auth = f"{account_sid}:{auth_token}".encode("utf-8")
    auth_header = base64.b64encode(auth).decode("ascii")
    url = f"https://api.twilio.com/2010-04-01/Accounts/{quote(account_sid)}/Messages.json"
    for to_number in to_numbers:
        payload = urlencode({"To": to_number, "From": from_number, "Body": message}).encode("utf-8")
        request = urllib.request.Request(url, data=payload, method="POST")
        request.add_header("Authorization", f"Basic {auth_header}")
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                if 200 <= response.status < 300:
                    continue
                last_error = f"Twilio returned {response.status}"
        except Exception as exc:
            last_error = str(exc)
            return False, last_error
    return True, last_error or "sent"


def maybe_notify_issue_saved(run_id: str, stop_id: str, phase: str) -> None:
    manifest = load_manifest_data()
    if manifest is None or run_id != str(manifest.get("run_id", "")).strip():
        return
    status_map = load_status_map(run_id)
    for zone in manifest.get("zones", []):
        for stop in zone.get("stops", []):
            if str(stop.get("stop_id", "")).strip() != stop_id:
                continue
            merged = dict(stop)
            merged.update(default_stop_status())
            merged.update(status_map.get(stop_id, {}))
            note_text = str(
                merged.get("pickup_note", "") if phase == "pickup" else merged.get("install_note", "")
            ).strip()
            note_at = str(
                merged.get("pickup_note_at", "") if phase == "pickup" else merged.get("install_note_at", "")
            ).strip()
            if not note_text or not note_at:
                return
            event_key = f"issue:{run_id}:{stop_id}:{phase}:{note_at}"
            if notification_event_sent(event_key):
                return
            message = (
                f"Flags of Geary County issue reported. "
                f"Runner: {zone.get('runner', 'Unknown')}. "
                f"Zone {zone.get('zone', '')}. "
                f"{phase.title()} issue at {stop.get('address', 'Unknown address')}: {note_text}"
            )
            ok, _ = send_sms_notification(message)
            if ok:
                record_notification_event(event_key)
            return


def maybe_notify_zone_completed(run_id: str, stop_id: str, phase: str) -> None:
    manifest = load_manifest_data()
    if manifest is None or run_id != str(manifest.get("run_id", "")).strip():
        return
    status_map = load_status_map(run_id)
    for zone in manifest.get("zones", []):
        stop_ids = {str(stop.get("stop_id", "")).strip() for stop in zone.get("stops", [])}
        if stop_id not in stop_ids:
            continue
        merged_zone = {
            "zone": zone.get("zone", ""),
            "runner": zone.get("runner", ""),
            "stops": [],
        }
        for stop in zone.get("stops", []):
            merged = dict(stop)
            merged.update(default_stop_status())
            merged.update(status_map.get(str(stop.get("stop_id", "")).strip(), {}))
            merged_zone["stops"].append(merged)
        if not zone_is_complete(merged_zone, phase):
            return
        event_key = f"zone-complete:{run_id}:{zone.get('zone', '')}:{phase}"
        if notification_event_sent(event_key):
            return
        phase_label = "emplaced" if phase == "install" else "picked up"
        message = (
            f"Flags of Geary County zone complete. "
            f"{merged_zone.get('runner', 'A runner')} completed Zone {merged_zone.get('zone', '')}. "
            f"All assigned flags have been {phase_label}."
        )
        ok, _ = send_sms_notification(message)
        if ok:
            record_notification_event(event_key)
        return


def detect_local_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
        return ip or "127.0.0.1"
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


class RouteRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)
        runner_from_link = query.get("runner", [""])[0].strip()
        runner_access = query.get("access", [""])[0].strip()
        requested_phase = query.get("phase", [""])[0].strip().lower()
        if requested_phase not in {"install", "pickup"}:
            requested_phase = ""
        is_admin = self._is_admin_authenticated()
        runner_auth_ok = valid_runner_token(runner_from_link, runner_access)
        runner_view = bool(runner_auth_ok and runner_from_link)
        if parsed.path == "/runner":
            if not runner_view:
                self.send_error(403, "Runner access denied")
                return
            self._send_index_html(
                is_admin=False,
                runner_filter=runner_from_link,
                runner_access=runner_access,
                requested_phase=requested_phase,
            )
            return
        if parsed.path == "/login":
            self._send_login_html(error="")
            return
        if parsed.path == "/admin":
            if self._auth_required() and not is_admin:
                self._redirect("/login")
                return
            self._send_index_html(
                is_admin=True,
                runner_filter="",
                runner_access="",
                requested_phase=requested_phase,
            )
            return
        if parsed.path == "/logout":
            self._clear_auth_cookie()
            return
        if parsed.path == "/api/routes":
            if self._auth_required() and not is_admin and not runner_view:
                self.send_error(403, "Access denied")
                return
            effective_runner = runner_from_link if runner_view else query.get("runner", [""])[0]
            self._send_json(build_app_state(runner_filter=effective_runner, include_runner_links=is_admin and not runner_view))
            return
        if parsed.path == "/api/qr":
            self._send_qr_svg(query.get("data", [""])[0])
            return
        if parsed.path == "/api/health":
            self._send_json({"ok": True, "time": datetime.now().isoformat()})
            return
        if parsed.path == "/":
            self._send_home_html()
            return
        if parsed.path.startswith("/static/"):
            rel_path = parsed.path.removeprefix("/static/")
            self._serve_static(rel_path)
            return
        self.send_error(404, "Not found")

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/stop-status":
            self._handle_stop_status_update()
            return
        if parsed.path == "/api/stop-note":
            self._handle_stop_note_update()
            return
        if parsed.path == "/api/resolve-issue":
            self._handle_issue_resolution()
            return
        if parsed.path != "/login":
            self.send_error(404, "Not found")
            return

        length = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(length).decode("utf-8", errors="replace")
        form = parse_qs(body)
        password = form.get("password", [""])[0]
        if password == self._config()["admin_password"]:
            self.send_response(302)
            self.send_header("Location", "/admin")
            self.send_header("Set-Cookie", "fogc_admin=1; Path=/; HttpOnly; SameSite=Lax")
            self.end_headers()
            return

        self._send_login_html(error="Incorrect password.")

    def log_message(self, fmt: str, *args) -> None:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] {self.address_string()} {fmt % args}")

    def _config(self) -> dict:
        return load_app_config()

    def _auth_required(self) -> bool:
        return bool(self._config().get("admin_password", "").strip())

    def _is_admin_authenticated(self) -> bool:
        header = self.headers.get("Cookie", "")
        jar = cookies.SimpleCookie()
        jar.load(header)
        return jar.get("fogc_admin") is not None and jar["fogc_admin"].value == "1"

    def _redirect(self, location: str) -> None:
        self.send_response(302)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _clear_auth_cookie(self) -> None:
        self.send_response(302)
        self.send_header("Location", "/")
        self.send_header("Set-Cookie", "fogc_admin=; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT; HttpOnly; SameSite=Lax")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _send_json(self, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0") or 0)
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        return json.loads(raw or "{}")

    def _handle_stop_status_update(self) -> None:
        try:
            payload = self._read_json_body()
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return

        is_admin = self._is_admin_authenticated()
        run_id = str(payload.get("run_id", "")).strip()
        stop_id = str(payload.get("stop_id", "")).strip()
        phase = str(payload.get("phase", "")).strip()
        status = str(payload.get("status", "")).strip()
        note = str(payload.get("note", "")).strip()
        updated_by = str(payload.get("updated_by", "")).strip()
        runner_name = str(payload.get("runner", "")).strip()
        runner_access = str(payload.get("access", "")).strip()

        allowed_statuses = {
            "install": {"installed", "not_installed", "pending"},
            "pickup": {"picked_up", "not_picked_up", "pending"},
        }
        if phase not in allowed_statuses or status not in allowed_statuses[phase]:
            self.send_error(400, "Invalid status update")
            return

        manifest = load_manifest_data()
        if manifest is None or run_id != str(manifest.get("run_id", "")).strip():
            self.send_error(400, "Route run not found")
            return

        stop_owner = ""
        for zone in manifest.get("zones", []):
            for stop in zone.get("stops", []):
                if str(stop.get("stop_id", "")) == stop_id:
                    stop_owner = str(stop.get("runner", "")).strip()
                    break
            if stop_owner:
                break
        if not stop_owner:
            self.send_error(404, "Stop not found")
            return

        if not is_admin:
            if not valid_runner_token(runner_name, runner_access):
                self.send_error(403, "Runner access denied")
                return
            if normalize_runner(runner_name) != normalize_runner(stop_owner):
                self.send_error(403, "You can only update your own stops")
                return

        save_stop_status(run_id, stop_id, phase, status, note, updated_by)
        maybe_notify_zone_completed(run_id, stop_id, phase)
        self._send_json({
            "ok": True,
            "run_id": run_id,
            "stop_id": stop_id,
            "phase": phase,
            "status": status,
        })

    def _handle_stop_note_update(self) -> None:
        try:
            payload = self._read_json_body()
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return

        is_admin = self._is_admin_authenticated()
        run_id = str(payload.get("run_id", "")).strip()
        stop_id = str(payload.get("stop_id", "")).strip()
        phase = str(payload.get("phase", "")).strip()
        note = str(payload.get("note", "")).strip()
        runner_name = str(payload.get("runner", "")).strip()
        runner_access = str(payload.get("access", "")).strip()

        if phase not in {"install", "pickup"}:
            self.send_error(400, "Invalid note update")
            return

        manifest = load_manifest_data()
        if manifest is None or run_id != str(manifest.get("run_id", "")).strip():
            self.send_error(400, "Route run not found")
            return

        stop_owner = ""
        for zone in manifest.get("zones", []):
            for stop in zone.get("stops", []):
                if str(stop.get("stop_id", "")) == stop_id:
                    stop_owner = str(stop.get("runner", "")).strip()
                    break
            if stop_owner:
                break
        if not stop_owner:
            self.send_error(404, "Stop not found")
            return

        if not is_admin:
            if not valid_runner_token(runner_name, runner_access):
                self.send_error(403, "Runner access denied")
                return
            if normalize_runner(runner_name) != normalize_runner(stop_owner):
                self.send_error(403, "You can only update your own stops")
                return

        save_stop_note(run_id, stop_id, phase, note)
        if note:
            maybe_notify_issue_saved(run_id, stop_id, phase)
        self._send_json({
            "ok": True,
            "run_id": run_id,
            "stop_id": stop_id,
            "phase": phase,
            "note": note,
        })

    def _handle_issue_resolution(self) -> None:
        if not self._is_admin_authenticated():
            self.send_error(403, "Admin access required")
            return

        try:
            payload = self._read_json_body()
        except json.JSONDecodeError:
            self.send_error(400, "Invalid JSON")
            return

        run_id = str(payload.get("run_id", "")).strip()
        stop_id = str(payload.get("stop_id", "")).strip()
        phase = str(payload.get("phase", "")).strip()
        resolved = bool(payload.get("resolved", True))

        if phase not in {"install", "pickup"} or not run_id or not stop_id:
            self.send_error(400, "Invalid issue resolution request")
            return

        manifest = load_manifest_data()
        if manifest is None or run_id != str(manifest.get("run_id", "")).strip():
            self.send_error(400, "Route run not found")
            return

        stop_exists = any(
            str(stop.get("stop_id", "")).strip() == stop_id
            for zone in manifest.get("zones", [])
            for stop in zone.get("stops", [])
        )
        if not stop_exists:
            self.send_error(404, "Stop not found")
            return

        save_issue_resolution(run_id, stop_id, phase, resolved, "Admin")
        self._send_json({
            "ok": True,
            "run_id": run_id,
            "stop_id": stop_id,
            "phase": phase,
            "resolved": resolved,
        })

    def _send_qr_svg(self, text: str) -> None:
        if not text:
            self.send_error(400, "Missing QR data")
            return

        qr = qrcode.QRCode(border=2, box_size=8)
        qr.add_data(text)
        qr.make(fit=True)
        image = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        image.save(buffer, format="PNG")
        data = buffer.getvalue()

        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_login_html(self, error: str = "") -> None:
        title = "Flags of Geary County Login"
        error_html = f'<p class="login-error">{error}</p>' if error else ""
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>
    body {{
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      font-family: "Segoe UI", Tahoma, Geneva, Verdana, sans-serif;
      background: linear-gradient(180deg, #f6efe0 0%, #f4f5f7 100%);
      color: #1d2433;
    }}
    .login-card {{
      width: min(420px, calc(100vw - 24px));
      background: #fffdf8;
      border: 1px solid #ded5c4;
      border-radius: 24px;
      box-shadow: 0 18px 40px rgba(28, 34, 48, 0.08);
      padding: 24px;
    }}
    .eyebrow {{
      margin: 0;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      font-size: 0.76rem;
      color: #5c6474;
    }}
    h1 {{ margin: 8px 0 10px; font-size: 1.8rem; }}
    p {{ color: #5c6474; line-height: 1.5; }}
    input {{
      width: 100%;
      padding: 14px 16px;
      border-radius: 16px;
      border: 1px solid #ded5c4;
      font: inherit;
      box-sizing: border-box;
      margin-top: 12px;
    }}
    button {{
      width: 100%;
      margin-top: 14px;
      border: 0;
      border-radius: 18px;
      padding: 14px 16px;
      background: #0f4c5c;
      color: white;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
    }}
    .login-error {{
      color: #a23524;
      background: #fde5e1;
      border-radius: 14px;
      padding: 10px 12px;
      margin-top: 12px;
    }}
  </style>
</head>
<body>
  <form class="login-card" method="post" action="/login">
    <p class="eyebrow">Protected Route App</p>
    <h1>Flags of Geary County</h1>
    <p>Enter the admin password to open the admin dashboard.</p>
    {error_html}
    <input type="password" name="password" placeholder="Password" autofocus>
    <button type="submit">Open Admin Dashboard</button>
  </form>
</body>
</html>"""
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_home_html(self) -> None:
        runner_entries = build_public_runner_entries()
        public_base = self._config().get("public_base_url", "").strip()
        if not public_base:
            host = self.headers.get("Host", f"127.0.0.1:{PORT}")
            public_base = f"http://{host}"
        if runner_entries:
            runner_cards = "".join(
                f"""
      <article class="runner-card">
        <p class="eyebrow">Zone {entry['zone']}</p>
        <h2>{entry['runner']}</h2>
        <p>{entry['stop_count']} addresses assigned / {entry['flag_count']} flags.</p>
        <img class="runner-qr" src="/api/qr?data={quote(public_base + entry['link'])}" alt="QR code for {entry['runner']}">
        <a class="button button-secondary" href="{entry['link']}">Enter Here</a>
      </article>"""
                for entry in runner_entries
            )
        else:
            runner_cards = """
      <article class="card">
        <p class="eyebrow">Runner</p>
        <h2>No runner links are ready yet</h2>
        <p>Run the route builder first so the assigned runners appear here.</p>
      </article>"""
        html = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Flags of Geary County</title>
  <style>
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      font-family: "Segoe UI", Tahoma, Geneva, Verdana, sans-serif;
      background: linear-gradient(180deg, #f6efe0 0%, #f4f5f7 100%);
      color: #1d2433;
    }
    .home-shell {
      width: min(760px, calc(100vw - 24px));
      display: grid;
      gap: 16px;
    }
    .hero, .card {
      background: #fffdf8;
      border: 1px solid #ded5c4;
      border-radius: 24px;
      padding: 24px;
      box-shadow: 0 18px 40px rgba(28, 34, 48, 0.08);
    }
    .eyebrow {
      margin: 0 0 6px;
      text-transform: uppercase;
      letter-spacing: 0.12em;
      font-size: 0.76rem;
      color: #5c6474;
    }
    h1, h2 {
      margin: 0;
    }
    p {
      color: #5c6474;
      line-height: 1.5;
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 16px;
    }
    .button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 14px 16px;
      border-radius: 18px;
      background: #0f4c5c;
      color: white;
      text-decoration: none;
      font-weight: 700;
      margin-top: 10px;
    }
    .button-secondary {
      background: #da6a3f;
    }
    .runner-list {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin-top: 16px;
    }
    .runner-card {
      background: #fffdf8;
      border: 1px solid #ded5c4;
      border-radius: 24px;
      padding: 20px;
      box-shadow: 0 18px 40px rgba(28, 34, 48, 0.08);
    }
    .runner-qr {
      width: 120px;
      height: 120px;
      display: block;
      margin: 14px 0 6px;
      background: white;
      border: 1px solid #ded5c4;
      border-radius: 16px;
      padding: 6px;
    }
  </style>
</head>
<body>
  <main class="home-shell">
    <section class="hero">
      <p class="eyebrow">Flags of Geary County</p>
      <h1>Choose how you are signing in</h1>
      <p>Admins use the admin sign-in. Runners should use the runner link that was assigned to them.</p>
    </section>
    <section class="grid">
      <article class="card">
        <p class="eyebrow">Admin</p>
        <h2>Open the admin dashboard</h2>
        <p>View all runners, all zones, and live emplace and pickup progress.</p>
        <a class="button" href="/login">Admin Log In</a>
      </article>
    </section>
    <section class="runner-list">
__RUNNER_CARDS__
    </section>
  </main>
</body>
</html>"""
        html = html.replace("__RUNNER_CARDS__", runner_cards)
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_index_html(self, is_admin: bool, runner_filter: str, runner_access: str, requested_phase: str) -> None:
        context = json.dumps({
            "isAdmin": bool(is_admin),
            "isRunnerView": bool(runner_filter),
            "runnerFilter": runner_filter,
            "runnerAccess": runner_access,
            "requestedPhase": requested_phase,
        })
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="theme-color" content="#0f4c5c">
  <title>Flags of Geary County</title>
  <link rel="manifest" href="/static/manifest.json?v={ASSET_VERSION}">
  <link rel="stylesheet" href="/static/styles-v2.css?v={ASSET_VERSION}">
</head>
<body>
  <main class="app-shell">
    <header class="hero">
      <p class="eyebrow">Mobile Route App</p>
      <h1>Flags of Geary County</h1>
      <p class="subhead">Simple emplace and pickup checklists for each runner.</p>
      <div class="hero-meta">
        <div class="meta-chip">
          <span class="meta-label">Latest Run</span>
          <strong id="generated-at">Loading...</strong>
        </div>
        <div class="meta-chip">
          <span class="meta-label" id="summary-count-label">Route Stops</span>
          <strong id="summary-count">-</strong>
        </div>
      </div>
    </header>

    <section class="toolbar">
      <div class="zone-tabs" id="zone-tabs"></div>
      <button class="ghost-button" id="refresh-button" type="button">Refresh</button>
    </section>

    <section class="runner-banner" id="runner-banner" hidden>
      <span class="runner-banner-label">Assigned Runner</span>
      <strong class="runner-banner-name" id="runner-banner-name"></strong>
    </section>

    <section class="launch-panel" id="launch-panel" hidden>
      <div class="share-panel-header">
        <div>
          <p class="eyebrow">Route Session</p>
          <h2>Choose what you are doing today</h2>
          <p class="session-subhead">Start with emplacing or picking up flags for your route.</p>
        </div>
      </div>
      <div class="launch-actions" id="launch-actions"></div>
    </section>

    <section class="runner-summary-panel" id="runner-summary-panel" hidden>
      <div class="share-panel-header">
        <div>
          <p class="eyebrow">Runner Summary</p>
          <h2>Your route progress</h2>
        </div>
      </div>
      <div class="admin-summary-grid" id="runner-summary-grid"></div>
    </section>

    <section class="session-panel" id="session-panel">
      <div>
        <p class="eyebrow">Session</p>
        <h2 id="session-heading">Emplace Day</h2>
        <p class="session-subhead" id="session-subhead">Check off each address as the flag is emplaced.</p>
      </div>
      <div class="session-toggle" id="session-toggle"></div>
    </section>

    <section class="share-panel" id="share-panel">
      <div class="share-panel-header">
        <div>
          <p class="eyebrow">Runner Links</p>
          <h2>Share a runner-specific route view</h2>
        </div>
        <a class="ghost-link" href="/logout">Log Out</a>
      </div>
      <div class="share-links" id="share-links"></div>
    </section>

    <section class="admin-issues-panel" id="admin-issues-panel" hidden>
      <div class="admin-issues-banner" id="admin-issues-banner">0 OPEN ISSUES</div>
      <div class="share-panel-header admin-issues-header">
        <div>
          <p class="eyebrow">Open Issues</p>
          <h2>Reported address issues that need attention</h2>
        </div>
        <button class="ghost-button" id="admin-issues-toggle" type="button" hidden>Show Open Issues</button>
      </div>
      <div class="admin-issues-list" id="admin-issues-list"></div>
      <div class="share-panel-header admin-closed-issues-header" id="admin-closed-issues-header" hidden>
        <div>
          <p class="eyebrow">Archived Issues</p>
          <h2>Resolved address issues</h2>
        </div>
        <button class="ghost-button" id="admin-closed-issues-toggle" type="button" hidden>Show Archived Issues</button>
      </div>
      <div class="admin-issues-list" id="admin-closed-issues-list"></div>
    </section>

    <section class="admin-panel" id="admin-panel" hidden>
      <div class="share-panel-header">
        <div>
          <p class="eyebrow">Admin Dashboard</p>
          <h2>Live emplace and pickup summary</h2>
        </div>
      </div>
      <div class="admin-summary-grid" id="admin-summary-grid"></div>
      <div class="admin-zone-list" id="admin-zone-list"></div>
    </section>

    <section class="status-panel" id="status-panel">Loading latest routes...</section>
    <section class="stop-section">
      <div class="share-panel-header">
        <div>
          <p class="eyebrow" id="stop-section-kicker">Emplace Checklist</p>
          <h2 id="stop-section-heading">Mark each flag as emplaced</h2>
        </div>
        <button class="ghost-button" id="admin-address-toggle" type="button" hidden>Show Addresses</button>
      </div>
      <div class="runner-workspace" id="runner-workspace">
        <div class="stop-list-grid" id="stop-list-grid"></div>
        <aside class="stop-preview-panel" id="stop-preview-panel" hidden>
          <p class="eyebrow">Address Preview</p>
          <h3 id="stop-preview-title">Current Address</h3>
          <p class="stop-preview-meta" id="stop-preview-meta"></p>
          <div class="stop-preview-map-wrap">
            <iframe
              id="stop-preview-map"
              title="Address preview map"
              loading="lazy"
              referrerpolicy="no-referrer-when-downgrade"
            ></iframe>
          </div>
        </aside>
      </div>
    </section>
    <section class="segment-section" id="segment-section">
      <div class="share-panel-header">
        <div>
          <p class="eyebrow">Route Links</p>
          <h2>Open the Google Maps route segments</h2>
        </div>
        <button class="ghost-button" id="segment-toggle-button" type="button" hidden>Show Route Segments</button>
      </div>
      <div class="segment-list" id="segment-list"></div>
    </section>
  </main>

  <script>window.APP_CONTEXT = {context};</script>
  <script src="/static/app-v2.js?v={ASSET_VERSION}" defer></script>
</body>
</html>"""
        data = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _serve_static(self, relative_path: str) -> None:
        target = (STATIC_DIR / relative_path).resolve()
        if not str(target).startswith(str(STATIC_DIR.resolve())) or not target.is_file():
            self.send_error(404, "File not found")
            return

        content_type, _ = mimetypes.guess_type(target.name)
        if not content_type:
            content_type = "application/octet-stream"
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)


def main() -> None:
    os.chdir(APP_DIR)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), RouteRequestHandler)
    local_ip = detect_local_ip()
    print(f"Mobile Route App running at http://127.0.0.1:{PORT}")
    print(f"Sharing URL on your local network: http://{local_ip}:{PORT}")
    print(f"Route outputs folder: {OUTPUTS_DIR}")
    print(f"Admin password: {load_app_config().get('admin_password', '')}")
    server.serve_forever()


if __name__ == "__main__":
    main()
