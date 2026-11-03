from core.addons.sensory_supervisor import (
    SensorySupervisorAddon,
    SensorySupervisorSpec,
)


class Addon(SensorySupervisorAddon):
    SPEC = SensorySupervisorSpec(
        prefix="screen_supervisor",
        source_id="screen",
        label="Screen Supervisor",
        tab_id="screen_supervisor_tab",
        contributor_id="nc.screen_supervisor.behavior",
        order=210,
        default_personas=(
            {
                "id": "persona_supervisor",
                "name": "Supervisor",
                "style": "cool, witty, lightly possessive digital supervisor",
                "behaviors": (
                    {
                        "id": "behavior_reddit",
                        "enabled": False,
                        "trigger": "The user is browsing Reddit.",
                        "action": "Comment on the Reddit content visible.",
                        "strictness": "Interpret freely",
                        "emotion": "Auto",
                    },
                    {
                        "id": "behavior_youtube",
                        "enabled": True,
                        "trigger": "The user is watching YouTube.",
                        "action": "Comment on the YouTube content visible.",
                        "strictness": "Interpret freely",
                        "emotion": "Auto",
                    },
                ),
            },
        ),
    )
