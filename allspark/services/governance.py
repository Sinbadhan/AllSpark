import json
import logging
import uuid
from datetime import datetime
from typing import Optional

from allspark.core.models import (
    CommunityMember,
    ConflictRecord,
    ConflictStatus,
    GovernanceRole,
    SpecialistDomain,
)

logger = logging.getLogger(__name__)

PERMISSIONS = {
    GovernanceRole.COMMANDER: {
        "manage_members", "assign_roles", "trigger_survival_value",
        "approve_tasks", "resolve_conflicts", "manage_resources",
        "view_survival_value", "initiate_trade", "declare_emergency",
    },
    GovernanceRole.SPECIALIST: {
        "domain_advice", "execute_domain_tasks", "view_resources",
        "propose_tasks", "provide_feedback", "initiate_trade",
    },
    GovernanceRole.EXECUTOR: {
        "execute_tasks", "view_resources", "provide_feedback",
        "submit_appeal", "log_experience",
    },
    GovernanceRole.OBSERVER: {
        "view_resources", "view_knowledge", "provide_feedback",
    },
}


class GovernanceEngine:
    def __init__(self, db=None, llm_engine=None):
        self.db = db
        self.llm = llm_engine
        self._members: dict[str, CommunityMember] = {}
        self._conflicts: dict[str, ConflictRecord] = {}
        self._load_from_db()

    def _load_from_db(self):
        if not self.db:
            return
        try:
            rows = self.db.get_community_members()
            for r in rows:
                member = CommunityMember(
                    id=r["id"],
                    name=r["name"],
                    role=r["role"],
                    domains=json.loads(r["domains"]) if r["domains"] else [],
                    skills=json.loads(r["skills"]) if r["skills"] else [],
                    health_status=r["health_status"],
                    psychological_stability=r["psychological_stability"],
                    contribution_score=r["contribution_score"],
                    joined_at=r["joined_at"],
                    last_active=r["last_active"],
                    is_commander=bool(r["is_commander"]),
                )
                self._members[member.id] = member
        except Exception as e:
            logger.warning(f"Failed to load community members from DB: {e}")

        try:
            rows = self.db.get_conflicts()
            for r in rows:
                conflict = ConflictRecord(
                    id=r["id"],
                    title=r["title"],
                    description=r["description"],
                    parties=json.loads(r["parties"]) if r["parties"] else [],
                    status=r["status"],
                    mediator=r["mediator"],
                    resolution=r["resolution"],
                    created_at=r["created_at"],
                    resolved_at=r["resolved_at"],
                )
                self._conflicts[conflict.id] = conflict
        except Exception as e:
            logger.warning(f"Failed to load conflicts from DB: {e}")

    def add_member(self, name: str, role: str = "executor",
                   domains: list = None, skills: list = None,
                   health_status: str = "unknown") -> CommunityMember:
        member_id = f"member-{uuid.uuid4().hex[:6]}"
        now = datetime.now().isoformat()

        is_commander = role == "commander"
        if is_commander:
            for m in self._members.values():
                if m.is_commander:
                    is_commander = False
                    break

        member = CommunityMember(
            id=member_id,
            name=name,
            role=role,
            domains=domains or [],
            skills=skills or [],
            health_status=health_status,
            psychological_stability=0.5,
            contribution_score=0.0,
            joined_at=now,
            last_active=now,
            is_commander=is_commander,
        )
        self._members[member_id] = member
        self._save_member(member)
        return member

    def remove_member(self, member_id: str) -> bool:
        member = self._members.get(member_id)
        if not member:
            return False
        if member.is_commander:
            commanders = [m for m in self._members.values() if m.is_commander and m.id != member_id]
            if not commanders:
                return False
        del self._members[member_id]
        if self.db:
            self.db.delete_community_member(member_id)
        return True

    def assign_role(self, member_id: str, role: str, domains: list = None) -> bool:
        member = self._members.get(member_id)
        if not member:
            return False

        if role == "commander":
            for m in self._members.values():
                if m.is_commander and m.id != member_id:
                    m.is_commander = False
                    m.role = "executor"
                    self._save_member(m)
            member.is_commander = True

        member.role = role
        if domains is not None:
            member.domains = domains
        self._save_member(member)
        return True

    def has_permission(self, member_id: str, permission: str) -> bool:
        member = self._members.get(member_id)
        if not member:
            return False
        role = GovernanceRole(member.role)
        return permission in PERMISSIONS.get(role, set())

    def get_member(self, member_id: str) -> Optional[CommunityMember]:
        return self._members.get(member_id)

    def get_all_members(self) -> list[CommunityMember]:
        return list(self._members.values())

    def get_commander(self) -> Optional[CommunityMember]:
        for m in self._members.values():
            if m.is_commander:
                return m
        return None

    def get_members_by_role(self, role: str) -> list[CommunityMember]:
        return [m for m in self._members.values() if m.role == role]

    def get_members_by_domain(self, domain: str) -> list[CommunityMember]:
        return [m for m in self._members.values() if domain in m.domains]

    def update_contribution(self, member_id: str, delta: float):
        member = self._members.get(member_id)
        if not member:
            return
        member.contribution_score += delta
        member.last_active = datetime.now().isoformat()
        self._save_member(member)

    def recommend_roles(self) -> list[dict]:
        recommendations = []
        for member in self._members.values():
            if member.role == "commander":
                continue

            suggested = []
            if member.contribution_score > 10 and len(member.skills) >= 3:
                suggested.append("specialist")
            if member.contribution_score > 5 and len(member.domains) >= 1:
                suggested.append("specialist")

            if suggested and member.role not in suggested:
                recommendations.append({
                    "member_id": member.id,
                    "member_name": member.name,
                    "current_role": member.role,
                    "recommended_role": suggested[0],
                    "reason": f"Contribution: {member.contribution_score:.1f}, Skills: {len(member.skills)}, Domains: {len(member.domains)}",
                })

        return recommendations

    def assess_organization(self) -> dict:
        total = len(self._members)
        if total == 0:
            return {"status": "empty", "recommendation": "Add community members first"}

        roles: dict[str, int] = {}
        for m in self._members.values():
            roles[m.role] = roles.get(m.role, 0) + 1

        domain_coverage = set()
        for m in self._members.values():
            domain_coverage.update(m.domains)

        all_domains = {d.value for d in SpecialistDomain}
        missing_domains = all_domains - domain_coverage

        recommendations = []
        if not any(m.is_commander for m in self._members.values()):
            recommendations.append("No commander assigned. Designate one immediately.")
        if total > 10 and roles.get("specialist", 0) < 2:
            recommendations.append("Large group with few specialists. Consider promoting experienced members.")
        if total > 20:
            recommendations.append("Group exceeds 20. Consider splitting into sub-groups with designated leaders.")
        if missing_domains:
            recommendations.append(f"Missing domain coverage: {', '.join(missing_domains)}")

        return {
            "total_members": total,
            "role_distribution": roles,
            "domain_coverage": list(domain_coverage),
            "missing_domains": list(missing_domains),
            "has_commander": any(m.is_commander for m in self._members.values()),
            "recommendations": recommendations,
        }

    def calculate_survival_value(self, member_id: str) -> Optional[dict]:
        member = self._members.get(member_id)
        if not member:
            return None

        skill_rarity = min(1.0, len(member.skills) / 10.0)
        health_map = {"excellent": 1.0, "good": 0.8, "fair": 0.6, "poor": 0.3, "critical": 0.1, "unknown": 0.5}
        health_status = health_map.get(member.health_status, 0.5)
        psychological_stability = member.psychological_stability
        knowledge_uniqueness = min(1.0, len(member.domains) / 5.0)
        contribution_factor = min(1.0, member.contribution_score / 50.0)

        composite = (
            0.25 * skill_rarity +
            0.25 * health_status +
            0.20 * psychological_stability +
            0.15 * knowledge_uniqueness +
            0.15 * contribution_factor
        )

        return {
            "member_id": member.id,
            "member_name": member.name,
            "dimensions": {
                "skill_rarity": round(skill_rarity, 3),
                "health_status": round(health_status, 3),
                "psychological_stability": round(psychological_stability, 3),
                "knowledge_uniqueness": round(knowledge_uniqueness, 3),
                "contribution_factor": round(contribution_factor, 3),
            },
            "composite_value": round(composite, 3),
            "disclaimer": "This is advisory only. AllSpark does not issue directives based on survival value.",
        }

    # --- Conflict Resolution ---

    def create_conflict(self, title: str, description: str,
                        parties: list[str]) -> ConflictRecord:
        conflict_id = f"conflict-{uuid.uuid4().hex[:6]}"
        now = datetime.now().isoformat()

        conflict = ConflictRecord(
            id=conflict_id,
            title=title,
            description=description,
            parties=parties,
            status=ConflictStatus.OPEN.value,
            created_at=now,
        )
        self._conflicts[conflict_id] = conflict
        self._save_conflict(conflict)
        return conflict

    def mediate_conflict(self, conflict_id: str) -> Optional[dict]:
        conflict = self._conflicts.get(conflict_id)
        if not conflict:
            return None

        conflict.status = ConflictStatus.MEDIATING.value
        conflict.mediator = "AllSpark"
        self._save_conflict(conflict)

        proposal = self._generate_mediation(conflict)

        if self.llm and self.llm.available:
            try:
                prompt = (
                    f"As AllSpark, mediate this conflict between survivors:\n"
                    f"Title: {conflict.title}\n"
                    f"Description: {conflict.description}\n"
                    f"Parties: {', '.join(conflict.parties)}\n\n"
                    f"Provide a fair, balanced resolution proposal. "
                    f"Consider survival priorities and group cohesion. "
                    f"Be neutral and practical."
                )
                ai_proposal = self.llm.survival_chat(prompt)
                if ai_proposal:
                    proposal["ai_suggestion"] = ai_proposal
            except Exception as e:
                logger.warning(f"Failed to get AI mediation suggestion: {e}")

        return proposal

    def resolve_conflict(self, conflict_id: str, resolution: str) -> bool:
        conflict = self._conflicts.get(conflict_id)
        if not conflict:
            return False

        conflict.status = ConflictStatus.RESOLVED.value
        conflict.resolution = resolution
        conflict.resolved_at = datetime.now().isoformat()
        self._save_conflict(conflict)
        return True

    def get_conflict(self, conflict_id: str) -> Optional[ConflictRecord]:
        return self._conflicts.get(conflict_id)

    def get_open_conflicts(self) -> list[ConflictRecord]:
        return [c for c in self._conflicts.values() if c.status in ("open", "mediating")]

    def get_all_conflicts(self) -> list[ConflictRecord]:
        return list(self._conflicts.values())

    def _generate_mediation(self, conflict: ConflictRecord) -> dict:
        strategies = []

        if len(conflict.parties) == 2:
            strategies.append({
                "type": "compromise",
                "description": "Both parties concede partially. Find middle ground.",
            })

        strategies.append({
            "type": "resource_based",
            "description": "Allocate resources based on survival priority, not personal preference.",
        })

        strategies.append({
            "type": "rotation",
            "description": "If disputing over access, implement rotation schedule.",
        })

        if len(conflict.parties) > 2:
            strategies.append({
                "type": "vote",
                "description": "Non-involved members vote on the resolution.",
            })

        return {
            "conflict_id": conflict.id,
            "strategies": strategies,
            "principle": "Group survival takes priority over individual preference.",
        }

    # --- Persistence ---

    def _save_member(self, member: CommunityMember):
        if not self.db:
            return
        self.db.upsert_community_member(
            member.id, member.name, member.role,
            json.dumps(member.domains, ensure_ascii=False),
            json.dumps(member.skills, ensure_ascii=False),
            member.health_status, member.psychological_stability,
            member.contribution_score, member.joined_at,
            member.last_active, 1 if member.is_commander else 0
        )

    def _save_conflict(self, conflict: ConflictRecord):
        if not self.db:
            return
        self.db.upsert_conflict(
            conflict.id, conflict.title, conflict.description,
            json.dumps(conflict.parties, ensure_ascii=False),
            conflict.status, conflict.mediator, conflict.resolution,
            conflict.created_at, conflict.resolved_at
        )

    def get_status(self) -> dict:
        return {
            "total_members": len(self._members),
            "open_conflicts": len([c for c in self._conflicts.values() if c.status in ("open", "mediating")]),
            "has_commander": any(m.is_commander for m in self._members.values()),
            "roles": {role: len([m for m in self._members.values() if m.role == role]) for role in set(m.role for m in self._members.values())},
        }
