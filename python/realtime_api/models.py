from dataclasses import dataclass, field
from typing import List, Optional, Union, Tuple, Any, Dict

@dataclass
class AnalysisRequest:
    id: str
    moves: List[Tuple[str, str]]  # List of (Player, Move) e.g., ("B", "Q4")
    rules: str = "chinese"
    komi: float = 7.5
    boardXSize: int = 19
    boardYSize: int = 19
    includePolicy: bool = False
    includeOwnership: bool = False
    priority: int = 0
    maxVisits: Optional[int] = None
    initialStones: List[Tuple[str, str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        data = {
            "id": self.id,
            "moves": self.moves,
            "rules": self.rules,
            "komi": self.komi,
            "boardXSize": self.boardXSize,
            "boardYSize": self.boardYSize,
            "includePolicy": self.includePolicy,
            "includeOwnership": self.includeOwnership,
            "priority": self.priority,
            "initialStones": self.initialStones,
        }
        if self.maxVisits is not None:
            data["maxVisits"] = self.maxVisits
        return data

@dataclass
class MoveInfo:
    move: str
    visits: int
    winrate: float
    scoreLead: float
    scoreSelfplay: float
    utility: float
    prior: float
    order: int
    pv: List[str]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'MoveInfo':
        return cls(
            move=data.get("move", ""),
            visits=data.get("visits", 0),
            winrate=data.get("winrate", 0.0),
            scoreLead=data.get("scoreLead", 0.0),
            scoreSelfplay=data.get("scoreSelfplay", 0.0),
            utility=data.get("utility", 0.0),
            prior=data.get("prior", 0.0),
            order=data.get("order", 0),
            pv=data.get("pv", []),
        )

@dataclass
class RootInfo:
    winrate: float
    scoreLead: float
    visits: int
    utility: float
    currentPlayer: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'RootInfo':
        return cls(
            winrate=data.get("winrate", 0.0),
            scoreLead=data.get("scoreLead", 0.0),
            visits=data.get("visits", 0),
            utility=data.get("utility", 0.0),
            currentPlayer=data.get("currentPlayer"),
        )

@dataclass
class AnalysisResponse:
    id: str
    moveInfos: List[MoveInfo]
    rootInfo: Optional[RootInfo] = None
    isDuringSearch: bool = False
    turnNumber: int = 0
    error: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'AnalysisResponse':
        if "error" in data:
            return cls(id=data.get("id", ""), moveInfos=[], error=data["error"])
        
        move_infos = [MoveInfo.from_dict(m) for m in data.get("moveInfos", [])]
        root_info = RootInfo.from_dict(data["rootInfo"]) if "rootInfo" in data else None
        
        return cls(
            id=data.get("id", ""),
            moveInfos=move_infos,
            rootInfo=root_info,
            isDuringSearch=data.get("isDuringSearch", False),
            turnNumber=data.get("turnNumber", 0)
        )
