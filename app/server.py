#!/usr/bin/env python3
import json
import os
import re
import sqlite3
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
STATIC_DIR = os.path.join(ROOT_DIR, "static")
DB_PATH = os.path.join(ROOT_DIR, "golf.db")

# Ensure DB and tables
conn = sqlite3.connect(DB_PATH, check_same_thread=False)
conn.row_factory = sqlite3.Row

def init_db():
	with conn:
		conn.execute(
			"""
			CREATE TABLE IF NOT EXISTS matches (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				name TEXT NOT NULL,
				num_holes INTEGER NOT NULL DEFAULT 18,
				created_at TEXT NOT NULL
			)
			"""
		)
		conn.execute(
			"""
			CREATE TABLE IF NOT EXISTS players (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				name TEXT NOT NULL UNIQUE
			)
			"""
		)
		conn.execute(
			"""
			CREATE TABLE IF NOT EXISTS match_players (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				match_id INTEGER NOT NULL,
				player_id INTEGER NOT NULL,
				UNIQUE(match_id, player_id),
				FOREIGN KEY(match_id) REFERENCES matches(id) ON DELETE CASCADE,
				FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
			)
			"""
		)
		conn.execute(
			"""
			CREATE TABLE IF NOT EXISTS scores (
				id INTEGER PRIMARY KEY AUTOINCREMENT,
				match_id INTEGER NOT NULL,
				player_id INTEGER NOT NULL,
				hole_number INTEGER NOT NULL,
				strokes INTEGER NOT NULL,
				created_at TEXT NOT NULL,
				UNIQUE(match_id, player_id, hole_number),
				FOREIGN KEY(match_id) REFERENCES matches(id) ON DELETE CASCADE,
				FOREIGN KEY(player_id) REFERENCES players(id) ON DELETE CASCADE
			)
			"""
		)


def json_response(handler: BaseHTTPRequestHandler, status: int, data):
	payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
	handler.send_response(status)
	handler.send_header("Content-Type", "application/json; charset=utf-8")
	handler.send_header("Content-Length", str(len(payload)))
	handler.end_headers()
	handler.wfile.write(payload)


def text_response(handler: BaseHTTPRequestHandler, status: int, text: str, content_type: str = "text/plain; charset=utf-8"):
	payload = text.encode("utf-8")
	handler.send_response(status)
	handler.send_header("Content-Type", content_type)
	handler.send_header("Content-Length", str(len(payload)))
	handler.end_headers()
	handler.wfile.write(payload)


def read_json(handler: BaseHTTPRequestHandler):
	length = int(handler.headers.get("Content-Length", "0"))
	if length == 0:
		return {}
	body = handler.rfile.read(length)
	try:
		return json.loads(body.decode("utf-8"))
	except Exception:
		raise ValueError("Invalid JSON body")


class App(BaseHTTPRequestHandler):
	def log_message(self, format, *args):
		# quiet basic logs
		pass

	def do_OPTIONS(self):
		# Basic CORS preflight support
		self.send_response(HTTPStatus.NO_CONTENT)
		self.send_header("Access-Control-Allow-Origin", "*")
		self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
		self.send_header("Access-Control-Allow-Headers", "Content-Type")
		self.end_headers()

	def do_GET(self):
		parsed = urlparse(self.path)
		path = parsed.path

		if path.startswith("/api/"):
			return self.handle_api_get(path)
		return self.serve_static(path)

	def do_POST(self):
		parsed = urlparse(self.path)
		path = parsed.path
		if not path.startswith("/api/"):
			return text_response(self, HTTPStatus.NOT_FOUND, "Not Found")
		try:
			return self.handle_api_post(path)
		except ValueError as ve:
			return json_response(self, HTTPStatus.BAD_REQUEST, {"detail": str(ve)})
		except Exception as ex:
			return json_response(self, HTTPStatus.INTERNAL_SERVER_ERROR, {"detail": str(ex)})

	# ---------- Static ----------
	def serve_static(self, path: str):
		if path == "/":
			return self._serve_file(os.path.join(STATIC_DIR, "index.html"))
		# Prevent path traversal
		rel = os.path.normpath(path.lstrip("/"))
		target = os.path.join(STATIC_DIR, rel)
		if not target.startswith(STATIC_DIR):
			return text_response(self, HTTPStatus.FORBIDDEN, "Forbidden")
		if os.path.isdir(target):
			target = os.path.join(target, "index.html")
		if not os.path.exists(target):
			return text_response(self, HTTPStatus.NOT_FOUND, "Not Found")
		return self._serve_file(target)

	def _serve_file(self, file_path: str):
		try:
			with open(file_path, "rb") as f:
				data = f.read()
			ctype = "text/plain; charset=utf-8"
			if file_path.endswith(".html"):
				ctype = "text/html; charset=utf-8"
			elif file_path.endswith(".js"):
				ctype = "application/javascript; charset=utf-8"
			elif file_path.endswith(".css"):
				ctype = "text/css; charset=utf-8"
			self.send_response(HTTPStatus.OK)
			self.send_header("Content-Type", ctype)
			self.send_header("Content-Length", str(len(data)))
			self.end_headers()
			self.wfile.write(data)
		except FileNotFoundError:
			return text_response(self, HTTPStatus.NOT_FOUND, "Not Found")

	# ---------- API ----------
	def handle_api_get(self, path: str):
		m = re.fullmatch(r"/api/matches", path)
		if m:
			rows = conn.execute("SELECT id, name, num_holes, created_at FROM matches ORDER BY datetime(created_at) DESC").fetchall()
			return json_response(self, HTTPStatus.OK, [dict(r) for r in rows])

		m = re.fullmatch(r"/api/matches/(\d+)", path)
		if m:
			match_id = int(m.group(1))
			row = conn.execute("SELECT id, name, num_holes, created_at FROM matches WHERE id=?", (match_id,)).fetchone()
			if not row:
				return json_response(self, HTTPStatus.NOT_FOUND, {"detail": "Match not found"})
			return json_response(self, HTTPStatus.OK, dict(row))

		m = re.fullmatch(r"/api/matches/(\d+)/players", path)
		if m and self.command == "GET":
			match_id = int(m.group(1))
			exists = conn.execute("SELECT 1 FROM matches WHERE id=?", (match_id,)).fetchone()
			if not exists:
				return json_response(self, HTTPStatus.NOT_FOUND, {"detail": "Match not found"})
			rows = conn.execute(
				"""
				SELECT p.id, p.name
				FROM players p
				JOIN match_players mp ON mp.player_id = p.id
				WHERE mp.match_id = ?
				ORDER BY p.name
				""",
				(match_id,),
			).fetchall()
			return json_response(self, HTTPStatus.OK, [dict(r) for r in rows])

		m = re.fullmatch(r"/api/matches/(\d+)/leaderboard", path)
		if m:
			match_id = int(m.group(1))
			exists = conn.execute("SELECT 1 FROM matches WHERE id=?", (match_id,)).fetchone()
			if not exists:
				return json_response(self, HTTPStatus.NOT_FOUND, {"detail": "Match not found"})
			rows = conn.execute(
				"""
				SELECT p.id as player_id, p.name as player_name, COALESCE(SUM(s.strokes), 0) as total_strokes
				FROM players p
				JOIN scores s ON s.player_id = p.id
				WHERE s.match_id = ?
				GROUP BY p.id, p.name
				ORDER BY total_strokes ASC, p.name ASC
				""",
				(match_id,),
			).fetchall()
			return json_response(self, HTTPStatus.OK, [dict(r) for r in rows])

		return json_response(self, HTTPStatus.NOT_FOUND, {"detail": "Not Found"})

	def handle_api_post(self, path: str):
		# Create match
		m = re.fullmatch(r"/api/matches", path)
		if m:
			payload = read_json(self)
			name = (payload.get("name") or "").strip()
			num_holes = int(payload.get("num_holes") or 18)
			if not name:
				raise ValueError("name is required")
			if num_holes < 1 or num_holes > 36:
				raise ValueError("num_holes must be between 1 and 36")
			created_at = datetime.utcnow().isoformat()
			with conn:
				cur = conn.execute(
					"INSERT INTO matches(name, num_holes, created_at) VALUES (?, ?, ?)",
					(name, num_holes, created_at),
				)
			match_id = cur.lastrowid
			row = conn.execute("SELECT id, name, num_holes, created_at FROM matches WHERE id=?", (match_id,)).fetchone()
			return json_response(self, HTTPStatus.OK, dict(row))

		# Add player to match
		m = re.fullmatch(r"/api/matches/(\d+)/players", path)
		if m:
			match_id = int(m.group(1))
			payload = read_json(self)
			name = (payload.get("name") or "").strip()
			if not name:
				raise ValueError("name is required")
			if not conn.execute("SELECT 1 FROM matches WHERE id=?", (match_id,)).fetchone():
				return json_response(self, HTTPStatus.NOT_FOUND, {"detail": "Match not found"})
			with conn:
				# Insert or get player
				player_row = conn.execute("SELECT id FROM players WHERE name=?", (name,)).fetchone()
				if player_row is None:
					cur = conn.execute("INSERT INTO players(name) VALUES (?)", (name,))
					player_id = cur.lastrowid
				else:
					player_id = int(player_row["id"])
				# Link to match (ignore if exists)
				conn.execute(
					"INSERT OR IGNORE INTO match_players(match_id, player_id) VALUES (?, ?)",
					(match_id, player_id),
				)
			row = conn.execute("SELECT id, name FROM players WHERE id=?", (player_id,)).fetchone()
			return json_response(self, HTTPStatus.OK, dict(row))

		# Record score (upsert per-hole)
		m = re.fullmatch(r"/api/matches/(\d+)/scores", path)
		if m:
			match_id = int(m.group(1))
			payload = read_json(self)
			player_id = int(payload.get("player_id"))
			hole_number = int(payload.get("hole_number"))
			strokes = int(payload.get("strokes"))

			if not conn.execute("SELECT 1 FROM matches WHERE id=?", (match_id,)).fetchone():
				return json_response(self, HTTPStatus.NOT_FOUND, {"detail": "Match not found"})
			if not conn.execute("SELECT 1 FROM players WHERE id=?", (player_id,)).fetchone():
				return json_response(self, HTTPStatus.NOT_FOUND, {"detail": "Player not found"})
			if not conn.execute(
				"SELECT 1 FROM match_players WHERE match_id=? AND player_id=?",
				(match_id, player_id),
			).fetchone():
				return json_response(self, HTTPStatus.BAD_REQUEST, {"detail": "Player not in this match"})
			# Validate hole range
			row = conn.execute("SELECT num_holes FROM matches WHERE id=?", (match_id,)).fetchone()
			num_holes = int(row["num_holes"]) if row else 18
			if hole_number < 1 or hole_number > num_holes:
				raise ValueError(f"hole_number must be between 1 and {num_holes}")

			created_at = datetime.utcnow().isoformat()
			with conn:
				# Upsert
				existing = conn.execute(
					"SELECT id FROM scores WHERE match_id=? AND player_id=? AND hole_number=?",
					(match_id, player_id, hole_number),
				).fetchone()
				if existing:
					conn.execute(
						"UPDATE scores SET strokes=?, created_at=? WHERE id=?",
						(strokes, created_at, int(existing["id"])),
					)
					score_id = int(existing["id"])
				else:
					cur = conn.execute(
						"INSERT INTO scores(match_id, player_id, hole_number, strokes, created_at) VALUES (?, ?, ?, ?, ?)",
						(match_id, player_id, hole_number, strokes, created_at),
					)
					score_id = cur.lastrowid
			row = conn.execute(
				"SELECT id, player_id, hole_number, strokes, created_at FROM scores WHERE id=?",
				(score_id,),
			).fetchone()
			return json_response(self, HTTPStatus.OK, dict(row))

		return json_response(self, HTTPStatus.NOT_FOUND, {"detail": "Not Found"})


def run(host: str = "0.0.0.0", port: int = 8000):
	init_db()
	server = ThreadingHTTPServer((host, port), App)
	print(f"Serving on http://{host}:{port}")
	server.serve_forever()


if __name__ == "__main__":
	run()