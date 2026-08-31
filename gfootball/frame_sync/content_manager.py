"""
Content management system for teams, stadiums, and leagues.

This module provides:
- Team database and management
- Stadium database
- League and tournament system
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class LeagueType(Enum):
    """League types."""
    LEAGUE = "league"
    CUP = "cup"
    FRIENDLY = "friendly"


@dataclass
class Player:
    """Football player."""
    player_id: str
    name: str
    position: str
    nationality: str
    age: int
    overall: int
    pace: int = 70
    shooting: int = 70
    passing: int = 70
    dribbling: int = 70
    defending: int = 70
    physical: int = 70

    def to_dict(self) -> dict:
        return {
            "player_id": self.player_id,
            "name": self.name,
            "position": self.position,
            "overall": self.overall,
        }


@dataclass
class Team:
    """Football team."""
    team_id: str
    name: str
    country: str
    league: str
    rating: int = 70
    players: list[Player] = field(default_factory=list)
    kit_color_home: str = "#FFFFFF"
    kit_color_away: str = "#000000"
    stadium: Optional[str] = None

    @property
    def squad_size(self) -> int:
        return len(self.players)

    def add_player(self, player: Player) -> None:
        self.players.append(player)

    def get_player(self, player_id: str) -> Optional[Player]:
        return next((p for p in self.players if p.player_id == player_id), None)

    def to_dict(self) -> dict:
        return {
            "team_id": self.team_id,
            "name": self.name,
            "country": self.country,
            "league": self.league,
            "rating": self.rating,
            "squad_size": self.squad_size,
        }


@dataclass
class Stadium:
    """Football stadium."""
    stadium_id: str
    name: str
    city: str
    country: str
    capacity: int
    pitch_type: str = "natural"
    weather_effects: bool = True

    def to_dict(self) -> dict:
        return {
            "stadium_id": self.stadium_id,
            "name": self.name,
            "city": self.city,
            "capacity": self.capacity,
        }


@dataclass
class League:
    """Football league."""
    league_id: str
    name: str
    country: str
    league_type: LeagueType
    teams: list[str] = field(default_factory=list)
    current_matchday: int = 0
    total_matchdays: int = 38

    def add_team(self, team_id: str) -> None:
        if team_id not in self.teams:
            self.teams.append(team_id)

    def remove_team(self, team_id: str) -> bool:
        if team_id in self.teams:
            self.teams.remove(team_id)
            return True
        return False

    def to_dict(self) -> dict:
        return {
            "league_id": self.league_id,
            "name": self.name,
            "country": self.country,
            "type": self.league_type.value,
            "teams": len(self.teams),
        }


class ContentManager:
    """Manages all game content."""

    def __init__(self):
        self._teams: dict[str, Team] = {}
        self._stadiums: dict[str, Stadium] = {}
        self._leagues: dict[str, League] = {}
        self._load_default_content()

    def _load_default_content(self) -> None:
        """Load default game content."""
        # Teams
        self._teams["real_madrid"] = Team(
            team_id="real_madrid", name="Real Madrid", country="Spain",
            league="La Liga", rating=89, kit_color_home="#FFFFFF", kit_color_away="#000000"
        )
        self._teams["barcelona"] = Team(
            team_id="barcelona", name="FC Barcelona", country="Spain",
            league="La Liga", rating=88, kit_color_home="#A50044", kit_color_away="#004D98"
        )
        self._teams["liverpool"] = Team(
            team_id="liverpool", name="Liverpool FC", country="England",
            league="Premier League", rating=87, kit_color_home="#C8102E", kit_color_away="#FFFFFF"
        )
        self._teams["man_city"] = Team(
            team_id="man_city", name="Manchester City", country="England",
            league="Premier League", rating=88, kit_color_home="#6CABDD", kit_color_away="#1C2C5B"
        )
        self._teams["bayern"] = Team(
            team_id="bayern", name="FC Bayern München", country="Germany",
            league="Bundesliga", rating=87, kit_color_home="#DC052D", kit_color_away="#FFFFFF"
        )

        # Players for Real Madrid
        self._add_sample_players("real_madrid", [
            ("Courtois", "GK", "Belgium", 27, 89),
            ("Militao", "CB", "Brazil", 25, 84),
            ("Modric", "CM", "Croatia", 38, 86),
            ("Vinicius", "LW", "Brazil", 23, 88),
            ("Bellingham", "CAM", "England", 20, 86),
        ])

        # Stadiums
        self._stadiums["santiago_bernabeu"] = Stadium(
            stadium_id="santiago_bernabeu", name="Santiago Bernabéu",
            city="Madrid", country="Spain", capacity=81044
        )
        self._stadiums["camp_nou"] = Stadium(
            stadium_id="camp_nou", name="Camp Nou",
            city="Barcelona", country="Spain", capacity=99354
        )
        self._stadiums["anfield"] = Stadium(
            stadium_id="anfield", name="Anfield",
            city="Liverpool", country="England", capacity=53394
        )

        # Leagues
        self._leagues["la_liga"] = League(
            league_id="la_liga", name="La Liga", country="Spain",
            league_type=LeagueType.LEAGUE, teams=["real_madrid", "barcelona"]
        )
        self._leagues["premier_league"] = League(
            league_id="premier_league", name="Premier League", country="England",
            league_type=LeagueType.LEAGUE, teams=["liverpool", "man_city"]
        )

    def _add_sample_players(self, team_id: str, players: list) -> None:
        """Add sample players to a team."""
        team = self._teams.get(team_id)
        if not team:
            return
        for i, (name, pos, nation, age, overall) in enumerate(players):
            player = Player(
                player_id=f"{team_id}_{i+1}", name=name, position=pos,
                nationality=nation, age=age, overall=overall
            )
            team.add_player(player)

    def get_team(self, team_id: str) -> Optional[Team]:
        return self._teams.get(team_id)

    def list_teams(self, country: Optional[str] = None) -> list[Team]:
        teams = list(self._teams.values())
        if country:
            teams = [t for t in teams if t.country == country]
        return teams

    def get_stadium(self, stadium_id: str) -> Optional[Stadium]:
        return self._stadiums.get(stadium_id)

    def list_stadiums(self) -> list[Stadium]:
        return list(self._stadiums.values())

    def get_league(self, league_id: str) -> Optional[League]:
        return self._leagues.get(league_id)

    def list_leagues(self, country: Optional[str] = None) -> list[League]:
        leagues = list(self._leagues.values())
        if country:
            leagues = [l for l in leagues if l.country == country]
        return leagues

    def get_content_summary(self) -> dict:
        return {
            "teams": len(self._teams),
            "stadiums": len(self._stadiums),
            "leagues": len(self._leagues),
            "total_players": sum(t.squad_size for t in self._teams.values()),
        }
