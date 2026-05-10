"""Compatibility access for the avatar-addon-owned Hand Doctor dialog."""

from core.addons import bootstrap_runtime


HandDoctorDialog = bootstrap_runtime.invoke_addon_capability(
    "nc.vseeface_avatar",
    "ui.hand_doctor_dialog_class",
)
if HandDoctorDialog is None:
    raise ImportError("VSeeFace addon did not provide ui.hand_doctor_dialog_class.")

__all__ = ["HandDoctorDialog"]
