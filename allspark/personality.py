from allspark.config import PERSONALITY_TEMPLATES, INTENT_KEYWORDS
from allspark.models import PersonalityMode, OperatingMode
from allspark.i18n import t


class PersonalitySystem:
    def __init__(self):
        self.current_mode = PersonalityMode.STABLE

    def determine_mode(self, operating_mode: OperatingMode,
                       warnings: list, phase: int,
                       is_multiplayer: bool = False) -> PersonalityMode:
        has_critical = any(w.get("level") == "critical" for w in warnings)

        if operating_mode == OperatingMode.HIBERNATION or has_critical or phase == 0:
            self.current_mode = PersonalityMode.CRISIS
        elif is_multiplayer:
            self.current_mode = PersonalityMode.MULTIPLAYER
        elif operating_mode in (OperatingMode.STANDARD, OperatingMode.ECONOMY):
            if warnings:
                self.current_mode = PersonalityMode.CRISIS
            elif phase >= 4:
                self.current_mode = PersonalityMode.RENAISSANCE
            else:
                self.current_mode = PersonalityMode.STABLE
        else:
            if phase >= 4:
                self.current_mode = PersonalityMode.RENAISSANCE
            else:
                self.current_mode = PersonalityMode.COMPANION
        return self.current_mode

    def get_template(self) -> dict:
        return PERSONALITY_TEMPLATES.get(self.current_mode.value, PERSONALITY_TEMPLATES["stable"])

    def greet(self) -> str:
        tmpl = self.get_template()
        return f"{tmpl['emoji_prefix']} {tmpl['greeting']}"

    def format_response(self, content: str, add_greeting: bool = False) -> str:
        tmpl = self.get_template()
        parts = []
        if add_greeting:
            parts.append(f"{tmpl['emoji_prefix']} {tmpl['greeting']}")
        parts.append(content)
        if self.current_mode == PersonalityMode.CRISIS:
            parts.append(f"\n{t('crisis_mode_notice')}")
        return "\n".join(parts)

    def classify_intent(self, user_input: str) -> str:
        text = user_input.lower()
        best_intent = "general"
        best_count = 0
        for intent, keywords in INTENT_KEYWORDS.items():
            count = sum(1 for kw in keywords if kw in text)
            if count > best_count:
                best_count = count
                best_intent = intent
        return best_intent
