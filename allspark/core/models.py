import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum


class ResourceType(Enum):
    POWER = "power"
    WATER = "water"
    FOOD = "food"
    FIRE = "fire"
    STORAGE = "storage"


RESOURCE_UNITS = {
    ResourceType.POWER: "Wh",
    ResourceType.WATER: "L",
    ResourceType.FOOD: "kcal",
    ResourceType.FIRE: "uses",
    ResourceType.STORAGE: "GB",
}


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


class ResetLevel(Enum):
    ASSESSMENT = 1     # L1: 重置评估
    ARCHIVE = 2        # L2: 重置档案
    FACTORY = 3        # L3: 重置出厂


class GoalPriority(Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class GoalStatus(Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"
    PAUSED = "paused"


class GoalType(Enum):
    AUTO = "auto"
    MANUAL = "manual"


class GoalSource(Enum):
    ASSESSMENT = "assessment"
    SURVIVOR = "survivor"
    TRADE = "trade"
    EXPERIENCE = "experience"


class GoalCategory(Enum):
    SURVIVAL = "survival"
    QUALITY = "quality"
    EXPLORATION = "exploration"
    COMMUNITY = "community"
    CIVILIZATION = "civilization"


class TimelineEventType(Enum):
    GOAL_COMPLETED = "goal_completed"
    RESOURCE_CHANGE = "resource_change"
    MEMBER_JOINED = "member_joined"
    KNOWLEDGE_ACQUIRED = "knowledge_acquired"
    MILESTONE = "milestone"
    DIARY_ENTRY = "diary_entry"
    SYSTEM_EVENT = "system_event"


class DiaryEmotion(Enum):
    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


@dataclass
class Resource:
    type: ResourceType
    current_amount: float
    unit: str
    daily_consumption: float = 0.0
    daily_intake: float = 0.0
    estimated_remaining_hours: float = 0.0
    last_updated: str = ""
    amount_known: bool = False
    consumption_known: bool = False
    intake_known: bool = False
    source: str = "migration"
    people_count: int = 1
    as_of: str = ""
    capacity: float = 0.0
    capacity_known: bool = False


@dataclass
class SurvivorState:
    health_status: str = "unknown"
    skills: list[str] = field(default_factory=list)
    psychological_state: str = "unknown"
    injuries: list[str] = field(default_factory=list)


class TaskType(Enum):
    MAIN = "main"
    SIDE = "side"


@dataclass
class Task:
    id: str
    phase: int
    priority: int
    title: str
    description: str = ""
    status: str = "pending"
    task_type: str = "main"
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
    # SHA-148: auditable expert signoff. Empty/0 by default = "no formal
    # signoff". ``expert_verified`` must never be assigned without a populated
    # reviewer + signoff_version whose content_hash still matches the entry
    # content (see is_signed_off / compute_content_hash).
    reviewer: str = ""
    qualification: str = ""
    review_date: str = ""
    citation: str = ""
    content_hash: str = ""
    signoff_version: int = 0

    def is_signed_off(self) -> bool:
        """True only when a named expert has signed off AND the content is
        unchanged since signing (SHA-148). An entry without a reviewer, or one
        whose content drifted from the pinned hash, is NOT signed off and must
        not be labeled ``expert_verified``."""
        return (
            bool(self.reviewer)
            and self.signoff_version > 0
            and bool(self.content_hash)
            and self.content_hash == compute_content_hash(self)
        )


def compute_content_hash(entry: "KnowledgeEntry") -> str:
    """SHA-256 of an entry's content fields (SHA-148 signoff pin).

    Signoff fields are excluded so signing does not change the hash. Editing
    any content field invalidates a signoff pinned to the old hash.
    """
    parts = [
        entry.id, entry.category, entry.subcategory, str(entry.priority),
        entry.title, entry.summary,
        json.dumps(entry.steps, ensure_ascii=False, sort_keys=True),
        json.dumps(entry.prerequisites, ensure_ascii=False, sort_keys=True),
        json.dumps(entry.warnings, ensure_ascii=False, sort_keys=True),
    ]
    return "sha256:" + hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


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
    # When True, automatic mode adaptation (based on power telemetry)
    # is suspended and the operator's explicit choice is honoured.
    # Set by /api/system/operating-mode and the equivalent CLI command.
    mode_manual_override: bool = False


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


@dataclass
class Goal:
    """PRD §10.1 目标系统 — 生存者需要达成的方向性成果"""
    id: str
    title: str
    description: str = ""
    goal_type: str = "auto"          # auto / manual
    category: str = "survival"        # survival / quality / exploration / community / civilization
    priority: str = "medium"          # critical / high / medium / low
    status: str = "active"            # active / completed / abandoned / paused
    source: str = "assessment"        # assessment / survivor / trade / experience
    progress: float = 0.0             # 0.0 - 1.0
    deadline: str = ""                # 可选截止日期
    created_at: str = ""
    updated_at: str = ""
    # 自动生成特有
    triggers: str = ""                # JSON 数组: 触发条件
    rationale: str = ""               # 为什么生成
    # 手动添加特有
    created_by: str = ""              # 生存者名字
    # 关联
    milestone_count: int = 0
    milestone_done: int = 0


@dataclass
class Milestone:
    """PRD §10.1 目标里程碑 — 目标的关键节点"""
    id: str
    goal_id: str
    description: str
    done: bool = False
    order: int = 0
    created_at: str = ""
    completed_at: str = ""


@dataclass
class DiaryEntry:
    """PRD §4.7 火种日记 — 生存者的个人记录"""
    id: str
    date: str                         # YYYY-MM-DD
    content: str
    emotion: str = "neutral"          # positive / neutral / negative
    keywords: str = ""                # JSON 数组
    related_goal_id: str = ""
    related_event: str = ""
    is_public: bool = False           # 多人场景是否公开
    created_at: str = ""


@dataclass
class TimelineEvent:
    """PRD §4.4 生存时间线 — 自动记录的关键事件"""
    id: str
    day: int                          # Day N
    timestamp: str
    event_type: str                   # 见 TimelineEventType
    title: str
    description: str = ""
    emotion: str = "neutral"
    related_goal_id: str = ""
    auto_generated: bool = True


@dataclass
class ActionPlan:
    """PRD §3.1.3 资源预警协议 — 行动方案"""
    id: str
    warning_id: str                   # 关联的预警资源类型
    resource_type: str                # 资源类型
    solution_source: str              # knowledge / fallback
    steps: list[str] = field(default_factory=list)
    rank_score: float = 0.0
    status: str = "proposed"          # proposed / accepted / executing / failed / completed
    created_at: str = ""
    updated_at: str = ""
    result: str = ""
    title: str = ""                   # 方案标题
