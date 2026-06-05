from rich.panel import Panel
from rich.table import Table

from allspark.commands.base import BaseCommand
from allspark.core.i18n import t


class BriefingCommand(BaseCommand):
    COMMAND_NAME = "briefing"
    ALIASES = ("简报", "daily")

    def execute(self, args: list[str]) -> None:
        daily_briefing = self.container.get("daily_briefing")
        if not daily_briefing:
            self.console.print(f"[yellow]{t('briefing_not_loaded')}[/]")
            return
        briefing = daily_briefing.generate()
        self.console.print(Panel(briefing, title=t("title_daily_briefing"), border_style="cyan"))


class TimelineCommand(BaseCommand):
    COMMAND_NAME = "timeline"
    ALIASES = ("时间线", "时间")

    def execute(self, args: list[str]) -> None:
        timeline = self.container.get("timeline")
        if not timeline:
            self.console.print(f"[yellow]{t('timeline_not_loaded')}[/]")
            return
        tl = timeline

        if not args:
            output = tl.format_timeline()
            self.console.print(output)
            return

        sub = args[0].lower()
        if sub in ("天", "day") and len(args) > 1:
            try:
                day = int(args[1])
                summary = tl.get_day_summary(day)
                if summary["event_count"] == 0:
                    self.console.print(f"[dim]{t('timeline_no_events_day', day=day)}[/]")
                else:
                    self.console.print(tl.format_timeline(summary["events"]))
            except ValueError:
                self.console.print(f"[yellow]{t('invalid_day_number')}[/]")
        elif sub in ("添加", "add"):
            title = " ".join(args[1:]) if len(args) > 1 else ""
            if not title:
                self.console.print(f"[yellow]{t('timeline_specify_title')}[/]")
                return
            tl.add_event("system_event", title, description="Manual entry")
            self.console.print(f"[green]✓ {t('timeline_event_added', title=title)}[/]")
        else:
            self.console.print(f"[dim]{t('timeline_usage')}[/]")


class DiaryCommand(BaseCommand):
    COMMAND_NAME = "diary"
    ALIASES = ("日记",)

    def execute(self, args: list[str]) -> None:
        diary = self.container.get("diary")
        if not diary:
            self.console.print(f"[yellow]{t('diary_not_loaded')}[/]")
            return
        dm = diary

        if not args:
            output = dm.format_entries()
            self.console.print(output)
            return

        sub = args[0].lower()

        if sub in ("写", "add", "写日记", "new"):
            self.console.print(f"[dim]{t('diary_enter_content')}[/]")
            lines = []
            while True:
                try:
                    line = self.console.input("").strip()
                    if line == "END":
                        break
                    lines.append(line)
                except (EOFError, KeyboardInterrupt):
                    break
            content = "\n".join(lines)
            if not content:
                self.console.print(f"[yellow]{t('diary_empty_not_saved')}[/]")
                return
            emotion = "neutral"
            result = dm.add_entry(content=content, emotion=emotion)
            self.console.print(f"[green]{t('diary_entry_saved', id=result['id'], chars=result['content_length'])}[/]")

        elif sub in ("查看", "view", "show"):
            entry_id = args[1] if len(args) > 1 else ""
            if not entry_id:
                entries = dm.get_entries(limit=10)
                self.console.print(dm.format_entries(entries))
            else:
                entry = dm.get_entry(entry_id)
                if entry:
                    self.console.print(dm.format_entry_detail(entry))
                else:
                    self.console.print(f"[yellow]{t('diary_entry_not_found', id=entry_id)}[/]")

        elif sub in ("删除", "delete", "remove"):
            entry_id = args[1] if len(args) > 1 else ""
            if dm.delete_entry(entry_id):
                self.console.print(f"[green]{t('diary_entry_deleted', id=entry_id)}[/]")
            else:
                self.console.print(f"[yellow]{t('diary_entry_not_found', id=entry_id)}[/]")

        elif sub in ("情绪", "emotion", "stats"):
            stats = dm.get_emotion_stats()
            table = Table(title=t("title_diary_stats"))
            table.add_column(t("field_metric"), style="cyan")
            table.add_column(t("field_value"))
            table.add_row(t("field_total_entries"), str(stats["total_entries"]))
            table.add_row(t("field_positive"), str(stats["positive"]))
            table.add_row(t("field_neutral"), str(stats["neutral"]))
            table.add_row(t("field_negative"), str(stats["negative"]))
            table.add_row(t("field_positive_ratio"), f"{stats['positive_ratio']:.0%}")
            self.console.print(table)

        else:
            self.console.print(f"[dim]{t('diary_usage')}[/]")


class WeatherCommand(BaseCommand):
    COMMAND_NAME = "weather"
    ALIASES = ("天气",)

    def execute(self, args: list[str]) -> None:
        weather = self.container.get("weather")
        if not weather:
            self.console.print(f"[yellow]{t('weather_not_loaded')}[/]")
            return
        wp = weather

        if not args:
            output = wp.format_prediction()
            self.console.print(Panel(output, title=t("title_weather"), border_style="cyan"))
            return

        sub = args[0].lower()
        if sub in ("云图", "cloud", "clouds"):
            self.console.print(wp.get_cloud_guide())
        elif sub in ("气压", "pressure") and len(args) > 1:
            try:
                hpa = float(args[1])
                wp.set_manual_pressure(hpa)
                self.console.print(f"[green]{t('weather_pressure_set', hpa=hpa)}[/]")
            except ValueError:
                self.console.print(f"[yellow]{t('weather_invalid_pressure')}[/]")
        else:
            self.console.print(f"[dim]{t('weather_usage')}[/]")


class PsychologyCommand(BaseCommand):
    COMMAND_NAME = "psychology"
    ALIASES = ("心理", "mood")

    def execute(self, args: list[str]) -> None:
        psychology = self.container.get("psychology")
        if not psychology:
            self.console.print(f"[yellow]{t('psychology_not_loaded')}[/]")
            return
        pt = psychology

        if not args:
            output = pt.format_status()
            self.console.print(Panel(output, title=t("title_psychology"), border_style="cyan"))
            return

        sub = args[0].lower()
        if sub in ("评估", "assess", "问卷", "quiz"):
            questions = pt.get_self_assessment_questions()
            self.console.print(f"[bold]{t('psych_assessment_title')}[/]\n")
            answers = {}
            for q in questions:
                self.console.print(f"  {q['question']}")
                for i, opt in enumerate(q["options"]):
                    self.console.print(f"    {i+1}. {opt}")
                try:
                    choice = self.console.input("  → ").strip()
                    idx = int(choice) - 1 if choice.isdigit() else 0
                    idx = max(0, min(idx, len(q["options"]) - 1))
                    answers[q["id"]] = idx
                except (ValueError, EOFError, KeyboardInterrupt):
                    answers[q["id"]] = 0
                self.console.print("")

            result = pt.process_assessment(answers)
            self.console.print(f"  {t('psych_score_result', score=result['score'], state=result['state'])}")
            self.console.print(f"  {t('psych_advice', advice=result['advice'])}")
        else:
            self.console.print(f"[dim]{t('psychology_usage')}[/]")


class GPSCommand(BaseCommand):
    COMMAND_NAME = "gps"
    ALIASES = ("定位", "位置")

    def execute(self, args: list[str]) -> None:
        gps_manager = self.container.get("gps_manager")
        if not gps_manager:
            self.console.print(f"[yellow]{t('gps_not_loaded')}[/]")
            return
        gm = gps_manager

        if not args:
            output = gm.format_position()
            self.console.print(output)
            return

        sub = args[0].lower()
        if sub in ("设置", "set") and len(args) >= 3:
            try:
                lat = float(args[1])
                lon = float(args[2])
                alt = float(args[3]) if len(args) > 3 else 0.0
                gm.set_manual_position(lat, lon, alt)
                self.console.print(f"[green]{t('gps_position_set', lat=lat, lon=lon)}[/]")
            except ValueError:
                self.console.print(f"[yellow]{t('gps_invalid_coords')}[/]")
        elif sub in ("轨迹", "track"):
            output = gm.format_track()
            self.console.print(output)
        elif sub in ("记录", "record"):
            label = " ".join(args[1:]) if len(args) > 1 else ""
            result = gm.record_track_point(label)
            if result:
                self.console.print(f"[green]{t('gps_track_recorded', result=result)}[/]")
            else:
                self.console.print(f"[yellow]{t('gps_no_position')}[/]")
        elif sub in ("距离", "distance") and len(args) >= 5:
            try:
                lat1, lon1 = float(args[1]), float(args[2])
                lat2, lon2 = float(args[3]), float(args[4])
                dist = gm.calculate_distance(lat1, lon1, lat2, lon2)
                bearing = gm.calculate_bearing(lat1, lon1, lat2, lon2)
                direction = gm.bearing_to_direction(bearing)
                self.console.print(f"  {t('gps_distance_result', dist=dist, direction=direction, bearing=bearing)}")
            except ValueError:
                self.console.print(f"[yellow]{t('gps_invalid_coords_short')}[/]")
        else:
            self.console.print(f"[dim]{t('gps_usage')}[/]")


class EnvironmentCommand(BaseCommand):
    COMMAND_NAME = "env"
    ALIASES = ("环境", "environment")

    def execute(self, args: list[str]) -> None:
        environment = self.container.get("environment")
        if not environment:
            self.console.print(f"[yellow]{t('env_not_loaded')}[/]")
            return
        output = environment.format_assessment()
        self.console.print(Panel(output, title=t("title_environment"), border_style="green"))


class VoiceCommand(BaseCommand):
    COMMAND_NAME = "voice"
    ALIASES = ("语音", "录音")

    def execute(self, args: list[str]) -> None:
        voice = self.container.get("voice")
        if not voice:
            self.console.print(f"[yellow]{t('voice_not_loaded')}[/]")
            return
        vm = voice

        if not args:
            output = vm.format_status()
            self.console.print(output)
            return

        sub = args[0].lower()
        if sub in ("加载", "load", "模型"):
            model_name = args[1] if len(args) > 1 else "base"
            self.console.print(f"[dim]{t('voice_loading_model', model=model_name)}[/]")
            result = vm.load_whisper(model_name)
            if result["status"] == "ok":
                self.console.print(f"[green]{t('voice_model_loaded', model=model_name)}[/]")
            else:
                self.console.print(f"[red]✗ {result['message']}[/]")

        elif sub in ("识别", "transcribe", "转写"):
            if len(args) > 1:
                audio_path = args[1]
                result = vm.transcribe(audio_path)
            else:
                self.console.print(f"[dim]{t('voice_recording')}[/]")
                result = vm.transcribe_from_mic(duration=5)

            if result.get("status") == "ok":
                self.console.print(f"[green]{t('voice_transcribed', language=result.get('language', '?'))}[/]")
                self.console.print(f"  {result['text']}")
            else:
                self.console.print(f"[red]✗ {result.get('message', 'Unknown error')}[/]")

        elif sub in ("说话", "speak", "朗读"):
            text = " ".join(args[1:]) if len(args) > 1 else t("voice_default_text")
            result = vm.speak(text)
            if result["status"] != "ok":
                self.console.print(f"[red]✗ {result.get('message', '')}[/]")

        elif sub in ("日记", "diary"):
            self.console.print(f"[dim]{t('voice_recording_diary')}[/]")
            result = vm.voice_diary(duration=10, emotion="neutral")
            if result.get("status") == "ok":
                self.console.print(f"[green]{t('voice_diary_saved')}[/]")
                self.console.print(f"  {result['text']}")
                if result.get("diary_entry"):
                    self.console.print(f"  ID: {result['diary_entry']['id']}")
            else:
                self.console.print(f"[red]✗ {result.get('message', '')}[/]")

        else:
            self.console.print(f"[dim]{t('voice_usage')}[/]")
