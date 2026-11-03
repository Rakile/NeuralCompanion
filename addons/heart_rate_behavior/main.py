from core.addons.sensory_supervisor import (
    SensorySupervisorAddon,
    SensorySupervisorSpec,
)


class Addon(SensorySupervisorAddon):
    SPEC = SensorySupervisorSpec(
        prefix="heart_rate_behavior",
        source_id="heart_rate",
        label="Heart Rate Behavior",
        tab_id="heart_rate_behavior_tab",
        contributor_id="nc.heart_rate_behavior.behavior",
        order=210,
        default_personas=(
            {
                "id": "persona_coach",
                "name": "Coach",
                "style": "steady, supportive coach energy, calming and practical",
                "behaviors": (
                    {
                        "id": "behavior_elevated_bpm",
                        "enabled": False,
                        "trigger": "The user's heart rate is above 120 BPM.",
                        "action": "Tell the user to slow down, take a deep breath, and relax.",
                        "strictness": "Interpret freely",
                        "emotion": "Auto",
                    },
                ),
            },
        ),
    )
