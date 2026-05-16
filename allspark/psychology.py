from datetime import datetime
from typing import Optional


class PsychologyTracker:
    def __init__(self, db, personality=None):
        self.db = db
        self.personality = personality
        self._interaction_count = 0
        self._last_interaction_time = None
        self._sentiment_samples = []

    def record_interaction(self, sentiment: str = "neutral"):
        self._interaction_count += 1
        self._last_interaction_time = datetime.now()
        self._sentiment_samples.append({
            "time": datetime.now().isoformat(),
            "sentiment": sentiment,
        })
        if len(self._sentiment_samples) > 100:
            self._sentiment_samples = self._sentiment_samples[-100:]

    def assess_state(self) -> dict:
        result = {
            "loneliness_index": self._calculate_loneliness(),
            "stress_index": self._calculate_stress(),
            "overall_state": "stable",
            "needs_intervention": False,
            "intervention_type": None,
            "recommendations": [],
        }

        if result["loneliness_index"] > 0.7:
            result["overall_state"] = "lonely"
            result["needs_intervention"] = True
            result["intervention_type"] = "companion"
            result["recommendations"].append(
                "检测到较高孤独指数，建议多与火种对话，或尝试联系其他幸存者。"
            )

        if result["stress_index"] > 0.7:
            if result["overall_state"] == "lonely":
                result["overall_state"] = "distressed"
            else:
                result["overall_state"] = "stressed"
            result["needs_intervention"] = True
            if result["intervention_type"] is None:
                result["intervention_type"] = "calm"
            result["recommendations"].append(
                "压力指数偏高，建议进行深呼吸、休息或记录日记来缓解。"
            )

        recent_sentiments = [s["sentiment"] for s in self._sentiment_samples[-10:]]
        negative_ratio = sum(1 for s in recent_sentiments if s == "negative") / max(len(recent_sentiments), 1)
        if negative_ratio > 0.6:
            result["needs_intervention"] = True
            if result["intervention_type"] is None:
                result["intervention_type"] = "emotional_support"
            result["recommendations"].append(
                "近期情绪偏消极，火种会主动提供陪伴和支持。"
            )

        return result

    def _calculate_loneliness(self) -> float:
        if not self._last_interaction_time:
            return 0.8

        hours_since = (datetime.now() - self._last_interaction_time).total_seconds() / 3600

        if hours_since < 1:
            return 0.1
        elif hours_since < 6:
            return 0.3
        elif hours_since < 24:
            return 0.5
        elif hours_since < 72:
            return 0.7
        else:
            return 0.9

    def _calculate_stress(self) -> float:
        stress = 0.0

        state = self.db.get_operating_state()
        if state.mode in ("economy", "hibernation"):
            stress += 0.3

        warnings = []
        try:
            from allspark.resource_manager import ResourceManager
            power = self.db.get_resource(
                __import__("allspark.models", fromlist=["ResourceType"]).ResourceType.POWER
            )
            if power and power.estimated_remaining_hours > 0:
                if power.estimated_remaining_hours < 6:
                    stress += 0.4
                elif power.estimated_remaining_hours < 24:
                    stress += 0.2
        except Exception:
            pass

        return min(1.0, stress)

    def get_self_assessment_questions(self) -> list[dict]:
        return [
            {
                "id": "sleep",
                "question": "过去24小时睡眠质量如何？",
                "options": ["良好（7h+）", "一般（4-7h）", "差（<4h）"],
                "scores": [0.0, 0.3, 0.7],
            },
            {
                "id": "appetite",
                "question": "食欲如何？",
                "options": ["正常", "略有下降", "明显下降"],
                "scores": [0.0, 0.2, 0.5],
            },
            {
                "id": "mood",
                "question": "当前情绪状态？",
                "options": ["平静/积极", "焦虑/不安", "低落/绝望"],
                "scores": [0.0, 0.4, 0.8],
            },
            {
                "id": "social",
                "question": "是否感到孤独？",
                "options": ["否", "偶尔", "经常"],
                "scores": [0.0, 0.3, 0.7],
            },
            {
                "id": "hope",
                "question": "对未来的信心？",
                "options": ["有信心", "不确定", "感到无望"],
                "scores": [0.0, 0.3, 0.8],
            },
        ]

    def process_assessment(self, answers: dict[str, int]) -> dict:
        questions = self.get_self_assessment_questions()
        total_score = 0.0
        max_score = 0.0

        for q in questions:
            idx = answers.get(q["id"], 0)
            idx = min(idx, len(q["scores"]) - 1)
            total_score += q["scores"][idx]
            max_score += max(q["scores"])

        normalized = total_score / max_score if max_score > 0 else 0

        if normalized < 0.2:
            state_label = "良好"
            advice = "心理状态良好，继续保持积极心态。"
        elif normalized < 0.4:
            state_label = "轻微压力"
            advice = "有些压力，建议适当休息和放松。"
        elif normalized < 0.6:
            state_label = "中度压力"
            advice = "压力较大，建议与火种多交流，记录感受。"
        else:
            state_label = "严重压力"
            advice = "🚨 心理压力很大，请务必与他人交流。如果出现自伤想法，请立即寻求帮助。"

        return {
            "score": round(normalized, 2),
            "state": state_label,
            "advice": advice,
            "needs_intervention": normalized >= 0.6,
        }

    def format_status(self) -> str:
        assessment = self.assess_state()
        loneliness_pct = int(assessment["loneliness_index"] * 100)
        stress_pct = int(assessment["stress_index"] * 100)

        state_icons = {
            "stable": "✅", "lonely": "😔", "stressed": "😰",
            "distressed": "🚨",
        }
        icon = state_icons.get(assessment["overall_state"], "📝")

        lines = [
            "🧠 心理状态",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"  {icon} 整体状态：{assessment['overall_state']}",
            f"  孤独指数：{loneliness_pct}%",
            f"  压力指数：{stress_pct}%",
            f"  需要干预：{'是' if assessment['needs_intervention'] else '否'}",
        ]

        if assessment["recommendations"]:
            lines.append("")
            for r in assessment["recommendations"]:
                lines.append(f"  💡 {r}")

        return "\n".join(lines)

    def check_and_trigger_intervention(self) -> Optional[dict]:
        assessment = self.assess_state()
        if not assessment["needs_intervention"]:
            return None

        intervention = assessment["intervention_type"]

        if intervention == "companion":
            return {
                "type": "companion_mode",
                "message": (
                    "我注意到你有一段时间没有和火种对话了。\n"
                    "无论何时，我都在这里。你可以随时和我聊天，\n"
                    "或者记录一下今天的感受。"
                ),
                "suggested_actions": ["写日记", "和火种聊天", "查看每日简报"],
            }

        if intervention == "calm":
            return {
                "type": "stress_relief",
                "message": (
                    "检测到你的压力指数偏高。\n"
                    "让我帮你缓解一下：\n"
                    "1. 深呼吸：吸气4秒→屏息4秒→呼气4秒，重复3次\n"
                    "2. 记录感受：写日记有助于梳理情绪\n"
                    "3. 回顾成就：看看你已经完成的目标"
                ),
                "suggested_actions": ["写日记", "查看目标", "心理评估"],
            }

        if intervention == "emotional_support":
            return {
                "type": "emotional_support",
                "message": (
                    "我观察到你最近的情绪偏低落。\n"
                    "请记住：每一步坚持都是有意义的。\n"
                    "如果你愿意，可以和我分享你的感受，\n"
                    "或者做一些让自己感到放松的事。"
                ),
                "suggested_actions": ["写日记", "心理评估", "查看天气"],
            }

        return None
