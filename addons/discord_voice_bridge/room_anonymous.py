"""Persist room privacy changes and update only owned runtimes' privacy flags."""


def _set_runtime(setter, value):
    result = setter(value)
    if isinstance(result, dict) and (result.get('ok') is False
            or ('anonymous' in result and result['anonymous'] != value)):
        raise RuntimeError(str(result.get('error') or 'The runtime rejected the Anonymous change.'))


def apply_anonymous(addon, session, owned_ids, anonymous, previous, persist):
    targets = []
    for instance in list(getattr(addon, '_bridge_instances', []) or []):
        if str(getattr(instance, 'instance_id', '')) not in owned_ids:
            continue
        runtime = getattr(instance, 'runtime_server', None)
        setter = getattr(runtime, 'set_room_anonymous', None) if runtime is not None else None
        if runtime is not None and not callable(setter):
            raise RuntimeError('The owned room runtime cannot update Anonymous. Restart the room runtime to update it.')
        settings = getattr(instance, 'settings', None)
        targets.append((settings if isinstance(settings, dict) else None, setter))
    persist(anonymous)  # A failed disk write must leave every live flag unchanged.
    applied = []
    try:
        for settings, setter in targets:
            if setter is not None:
                applied.append(setter)
                _set_runtime(setter, anonymous)
        for settings, _ in targets:
            if settings is not None:
                settings['_room_anonymous'] = anonymous
        if session is not None:
            session['_room_anonymous'] = anonymous
    except Exception as exc:
        recovery_errors = []
        for setter in reversed(applied):
            try:
                _set_runtime(setter, previous)
            except Exception as recovery:
                recovery_errors.append(str(recovery))
        try:
            persist(previous)
        except Exception as recovery:
            recovery_errors.append(str(recovery))
        detail = '; rollback needs attention: ' + '; '.join(recovery_errors) if recovery_errors else ''
        raise RuntimeError('Anonymous update failed: ' + str(exc) + detail) from exc
