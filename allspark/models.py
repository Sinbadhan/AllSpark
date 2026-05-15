from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class ResourceType(Enum):
    POWER = "power"
    WATER = "water"
    FOOD = "food"
    FIRE = "fire"
    STORAGE = "storage"


class OperatingMode(Enum):
    PROACTIVE = "proactive"
    STANDARD = "standard"
    ECONOMY = "economy"
    HIBERNATION = "hibernation"
    RECOVERY = "recovery"


class SurvivalPhase(Enum):
    IMMEDIATE = 0
    SHORT_TERM = 1
    MID_TERM = 2
    QUALITY = 3
    RENAISSANCE = 4


class PersonalityMode(Enum):
    CRISIS = "crisis"
    STABLE = "stable"
    COMPANION = "companion"
    MULTIPLAYER = "multiplayer"
    RENAISSANCE = "renaissance"


class GovernanceRole(Enum):
    COMMANDER = "commander"
    SPECIALIST = "specialist"
    EXECUTOR = "executor"
    OBSERVER = "observer"


class SpecialistDomain(Enum):
    MEDICAL = "medical"
    ENGINEERING = "engineering"
    AGRICULTURE = "agriculture"
    DEFENSE = "defense"
    LOGISTICS = "logistics"
    COMMUNICATION = "communication"
    EDUCATION = "education"


class ConflictStatus(Enum):
    OPEN = "open"
    MEDIATING = "mediating"
    RESOLVED = "resolved"
    ESCALATED = "escalated"


class TradeStatus(Enum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    COMPLETED = "completed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class TaskStatus(Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskPriority(Enum):
    URGENT = 0
    HIGH = 1
    MEDIUM = 2
    LOW = 3


@dataclass
class Resource:
    type: ResourceType
    current_amount: float
    unit: str
    daily_consumption: float = 0.0
    daily_intake: float = 0.0
    estimated_remaining_hours: float = 0.0
    last_updated: str = ""


@dataclass
class SurvivorState:
    health_status: str = "unknown"
    skills: list[str] = field(default_factory=list)
    psychological_state: str = "unknown"
    injuries: list[str] = field(default_factory=list)


@dataclass
class Task:
    id: str
    phase: int
    priority: int
    title: str
    description: str = ""
    status: str = "pending"
    created_at: str = ""
    updated_at: str = ""


@dataclass
class KnowledgeEntry:
    id: str
    category: str
    subcategory: str
    priority: int
    title: str
    summary: str
    steps: list[str] = field(default_factory=list)
    prerequisites: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    verification: str = "unverified"
    source: str = "pre_collapse"
    version: int = 1
    language: str = "zh"


@dataclass
class ExperienceLog:
    id: str
    timestamp: str
    event: str
    outcome: str
    lesson: str = ""
    related_knowledge_id: str = ""


@dataclass
class MapPOI:
    id: str
    name: str
    type: str
    description: str = ""
    distance_km: float = 0.0
    direction: str = ""
    notes: str = ""
    discovered_at: str = ""
    verified: bool = False


@dataclass
class OperatingState:
    mode: str = "standard"
    power_remaining_hours: float = 48.0
    last_mode_change: str = ""


@dataclass
class CommunityMember:
    id: str
    name: str
    role: str = "executor"
    domains: list[str] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    health_status: str = "unknown"
    psychological_stability: float = 0.5
    contribution_score: float = 0.0
    joined_at: str = ""
    last_active: str = ""
    is_commander: bool = False


@dataclass
class ConflictRecord:
    id: str
    title: str
    description: str = ""
    parties: list[str] = field(default_factory=list)
    status: str = "open"
    mediator: str = ""
    resolution: str = ""
    created_at: str = ""
    resolved_at: str = ""


@dataclass
class TradeOffer:
    id: str
    proposer_id: str
    target_spark_id: str
    offer_knowledge_ids: list[str] = field(default_factory=list)
    request_knowledge_ids: list[str] = field(default_factory=list)
    status: str = "proposed"
    created_at: str = ""
    completed_at: str = ""
