"""Addon-owned composition; providers resolve only on explicit generation workers."""
from pathlib import Path
from uuid import uuid4

from .api import SoundscapeAPI
from .generation import SoundGenerationJobs
from .library import SoundLibrary
from .state import SoundscapeStateStore, atomic_json
from .uploads import SoundUploads


def create_soundscape(root: Path, context, scope, *, model=None) -> SoundscapeAPI:
    import json
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    identity_path=root/'installation.json'
    if identity_path.exists():
        instance=json.loads(identity_path.read_text(encoding='utf-8'))['id']
        from .models import identity
        identity(instance,asset=True)
    else:
        instance=uuid4().hex;atomic_json(identity_path,{'id':instance})
    def client():
        factory=getattr(context.capabilities.remote_commands,'soundscape_client',None)
        if not callable(factory): raise ValueError('Voice Studio sound generation is unavailable.')
        return factory()
    library=SoundLibrary(root/'library')
    from .feedback import SoundFeedbackStore
    feedback=SoundFeedbackStore(root/'feedback.json')
    state=SoundscapeStateStore(root/'settings.json')
    from .director import SoundscapeDirector
    director=SoundscapeDirector(state.snapshot, library.list_assets,
                                provider=getattr(context.capabilities, 'providers', None), model=model, feedback=feedback)
    jobs=SoundGenerationJobs(root/'drafts',client,library)
    uploads=SoundUploads(root/'uploads',library)
    return SoundscapeAPI(state,library,uploads,jobs,scope,instance_id=instance,director=director,feedback=feedback)
