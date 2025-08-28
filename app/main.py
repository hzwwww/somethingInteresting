from datetime import datetime
from typing import List

from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, PositiveInt
from sqlalchemy import (
	create_engine,
	Integer,
	String,
	DateTime,
	ForeignKey,
	UniqueConstraint,
	func,
	select,
)
from sqlalchemy.orm import declarative_base, relationship, Mapped, mapped_column, sessionmaker, Session


DATABASE_URL = "sqlite:///./golf.db"

engine = create_engine(
	DATABASE_URL,
	connect_args={"check_same_thread": False},
	echo=False,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


class Match(Base):
	__tablename__ = "matches"

	id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
	name: Mapped[str] = mapped_column(String(200), nullable=False)
	num_holes: Mapped[int] = mapped_column(Integer, default=18)
	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

	players: Mapped[List["MatchPlayer"]] = relationship("MatchPlayer", back_populates="match", cascade="all, delete-orphan")
	scores: Mapped[List["Score"]] = relationship("Score", back_populates="match", cascade="all, delete-orphan")


class Player(Base):
	__tablename__ = "players"

	id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
	name: Mapped[str] = mapped_column(String(120), unique=True, nullable=False, index=True)

	matches: Mapped[List["MatchPlayer"]] = relationship("MatchPlayer", back_populates="player", cascade="all, delete-orphan")
	scores: Mapped[List["Score"]] = relationship("Score", back_populates="player", cascade="all, delete-orphan")


class MatchPlayer(Base):
	__tablename__ = "match_players"

	id: Mapped[int] = mapped_column(Integer, primary_key=True)
	match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"))
	player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"))

	match: Mapped[Match] = relationship("Match", back_populates="players")
	player: Mapped[Player] = relationship("Player", back_populates="matches")

	__table_args__ = (
		UniqueConstraint("match_id", "player_id", name="uq_match_player"),
	)


class Score(Base):
	__tablename__ = "scores"

	id: Mapped[int] = mapped_column(Integer, primary_key=True)
	match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"))
	player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"))
	hole_number: Mapped[int] = mapped_column(Integer)
	strokes: Mapped[int] = mapped_column(Integer)
	created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

	match: Mapped[Match] = relationship("Match", back_populates="scores")
	player: Mapped[Player] = relationship("Player", back_populates="scores")

	__table_args__ = (
		UniqueConstraint("match_id", "player_id", "hole_number", name="uq_score_once_per_hole"),
	)


# Pydantic Schemas
class MatchCreate(BaseModel):
	name: str = Field(min_length=1, max_length=200)
	num_holes: PositiveInt = 18


class MatchOut(BaseModel):
	id: int
	name: str
	num_holes: int
	created_at: datetime

	class Config:
		from_attributes = True


class PlayerAdd(BaseModel):
	name: str = Field(min_length=1, max_length=120)


class PlayerOut(BaseModel):
	id: int
	name: str

	class Config:
		from_attributes = True


class ScoreCreate(BaseModel):
	player_id: int
	hole_number: PositiveInt
	strokes: PositiveInt


class ScoreOut(BaseModel):
	id: int
	player_id: int
	hole_number: int
	strokes: int
	created_at: datetime

	class Config:
		from_attributes = True


class LeaderboardRow(BaseModel):
	player_id: int
	player_name: str
	total_strokes: int


app = FastAPI(title="Golf Mini App", version="0.1.0")

# CORS for local dev and simple static hosting
app.add_middleware(
	CORSMiddleware,
	allow_origins=["*"],
	allow_credentials=True,
	allow_methods=["*"],
	allow_headers=["*"],
)


# Dependency

def get_db() -> Session:
	db = SessionLocal()
	try:
		yield db
	finally:
		db.close()


# Create tables
Base.metadata.create_all(bind=engine)


# API routes under /api
@app.post("/api/matches", response_model=MatchOut)
def create_match(payload: MatchCreate, db: Session = Depends(get_db)):
	match = Match(name=payload.name.strip(), num_holes=payload.num_holes)
	db.add(match)
	db.commit()
	db.refresh(match)
	return match


@app.get("/api/matches", response_model=List[MatchOut])
def list_matches(db: Session = Depends(get_db)):
	matches = db.execute(select(Match).order_by(Match.created_at.desc())).scalars().all()
	return matches


@app.get("/api/matches/{match_id}", response_model=MatchOut)
def get_match(match_id: int, db: Session = Depends(get_db)):
	match = db.get(Match, match_id)
	if not match:
		raise HTTPException(status_code=404, detail="Match not found")
	return match


@app.post("/api/matches/{match_id}/players", response_model=PlayerOut)
def add_player(match_id: int, payload: PlayerAdd, db: Session = Depends(get_db)):
	match = db.get(Match, match_id)
	if not match:
		raise HTTPException(status_code=404, detail="Match not found")

	name = payload.name.strip()
	if not name:
		raise HTTPException(status_code=400, detail="Player name required")

	player = db.execute(select(Player).where(Player.name == name)).scalar_one_or_none()
	if not player:
		player = Player(name=name)
		db.add(player)
		db.flush()

	# link player to match if not already
	existing = db.execute(
		select(MatchPlayer).where(MatchPlayer.match_id == match.id, MatchPlayer.player_id == player.id)
	).scalar_one_or_none()
	if not existing:
		link = MatchPlayer(match_id=match.id, player_id=player.id)
		db.add(link)

	db.commit()
	db.refresh(player)
	return player


@app.get("/api/matches/{match_id}/players", response_model=List[PlayerOut])
def list_match_players(match_id: int, db: Session = Depends(get_db)):
	match = db.get(Match, match_id)
	if not match:
		raise HTTPException(status_code=404, detail="Match not found")

	rows = db.execute(
		select(Player).join(MatchPlayer, MatchPlayer.player_id == Player.id).where(MatchPlayer.match_id == match.id).order_by(Player.name)
	).scalars().all()
	return rows


@app.post("/api/matches/{match_id}/scores", response_model=ScoreOut)
def record_score(match_id: int, payload: ScoreCreate, db: Session = Depends(get_db)):
	match = db.get(Match, match_id)
	if not match:
		raise HTTPException(status_code=404, detail="Match not found")

	player = db.get(Player, payload.player_id)
	if not player:
		raise HTTPException(status_code=404, detail="Player not found")

	# validate player belongs to match
	link = db.execute(
		select(MatchPlayer).where(MatchPlayer.match_id == match.id, MatchPlayer.player_id == player.id)
	).scalar_one_or_none()
	if not link:
		raise HTTPException(status_code=400, detail="Player not in this match")

	if payload.hole_number < 1 or payload.hole_number > match.num_holes:
		raise HTTPException(status_code=400, detail=f"Hole number must be between 1 and {match.num_holes}")

	# upsert-like behavior: if a score exists for that hole, update it; else create
	existing_score = db.execute(
		select(Score).where(
			Score.match_id == match.id,
			Score.player_id == player.id,
			Score.hole_number == payload.hole_number,
		)
	).scalar_one_or_none()

	if existing_score:
		existing_score.strokes = payload.strokes
		db.add(existing_score)
		obj = existing_score
	else:
		score = Score(
			match_id=match.id,
			player_id=player.id,
			hole_number=payload.hole_number,
			strokes=payload.strokes,
		)
		db.add(score)
		obj = score

	db.commit()
	db.refresh(obj)
	return obj


@app.get("/api/matches/{match_id}/leaderboard", response_model=List[LeaderboardRow])
def leaderboard(match_id: int, db: Session = Depends(get_db)):
	match = db.get(Match, match_id)
	if not match:
		raise HTTPException(status_code=404, detail="Match not found")

	rows = db.execute(
		select(
			Player.id.label("player_id"),
			Player.name.label("player_name"),
			func.coalesce(func.sum(Score.strokes), 0).label("total_strokes"),
		)
		.join(Score, Score.player_id == Player.id)
		.where(Score.match_id == match.id)
		.group_by(Player.id, Player.name)
		.order_by(func.coalesce(func.sum(Score.strokes), 0).asc(), Player.name.asc())
	).all()

	# Convert SQLAlchemy Row objects to dicts for Pydantic
	result: List[LeaderboardRow] = [
		LeaderboardRow(
			player_id=row.player_id,
			player_name=row.player_name,
			total_strokes=row.total_strokes,
		)
		for row in rows
	]
	return result


# Serve static frontend at /
app.mount("/", StaticFiles(directory="static", html=True), name="static")