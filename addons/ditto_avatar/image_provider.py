"""Optional Qt adapter: QML receives owning images, never live slot pointers."""
from PySide6 import QtGui, QtQuick


class DittoImageProvider(QtQuick.QQuickImageProvider):
    def __init__(self, service):
        super().__init__(QtQuick.QQuickImageProvider.Image)
        self.service = service

    def requestImage(self, name, size, requested_size):
        frame = self.service.preview_image(name)
        if frame is None:
            return QtGui.QImage()
        width, height, pixels = frame
        image = QtGui.QImage(pixels, width, height, width*3, QtGui.QImage.Format_RGB888).copy()
        if size is not None:
            size.setWidth(width)
            size.setHeight(height)
        return image


def register_image_provider(engine):
    from .service import get_service
    # Resolve the service at request time: native addon setup follows engine creation.
    class LazyService:
        def preview_image(self, name):
            try:
                return get_service().preview_image(name)
            except RuntimeError:
                return None
    engine.addImageProvider('ditto', DittoImageProvider(LazyService()))
