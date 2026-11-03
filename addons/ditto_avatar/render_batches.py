"""Small frame batches for Ditto's live PyTorch renderer."""
import queue
import time

import numpy as np

RENDER_BATCH_SIZE = 4


def take_batch(source, stop, size, max_wait=.004):
    """Never hold a short audio tail indefinitely waiting to fill a batch."""
    while not stop.is_set():
        try:
            first = source.get(timeout=.05)
            break
        except queue.Empty:
            continue
    else:
        return [], True
    if first is None:
        return [], True
    items = [first]
    deadline = time.perf_counter()+max_wait
    while len(items) < size and not stop.is_set():
        try:
            item = source.get_nowait()
        except queue.Empty:
            remaining = deadline-time.perf_counter()
            if remaining <= 0:
                break
            try:
                item = source.get(timeout=remaining)
            except queue.Empty:
                break
        if item is None:
            return items, True
        items.append(item)
    return items, stop.is_set()


def put_unless_stopped(target, item, stop):
    while not stop.is_set():
        try:
            target.put(item, timeout=.05)
            return True
        except queue.Full:
            continue
    return False


class BatchDecoder:
    def __init__(self, original):
        self.original = original

    def __call__(self, features):
        import torch
        decoder = self.original.decoder
        with torch.no_grad(), torch.autocast(device_type=decoder.device[:4],
                                            dtype=torch.float16, enabled=True):
            prediction = decoder.model(torch.from_numpy(features).to(decoder.device)).float().cpu().numpy()
        return np.transpose(prediction, (0, 2, 3, 1)).clip(0, 1)*255


class FrameBatchRenderer:
    def __init__(self, sdk, size=RENDER_BATCH_SIZE):
        if type(size) is not int or size not in (1, 2, 4):
            raise ValueError('Render batch must be 1, 2 or 4.')
        self.sdk = sdk
        supported = (sdk.warp_f3d.warp_net.model_type == 'pytorch'
                     and sdk.decode_f3d.decoder.model_type == 'pytorch')
        # ONNX/TRT exports may have fixed batch shapes; retain their existing path.
        self.batch_size = size if supported else 1
        self.installed = False
        self.warp_batches, self.decoder_batches = {}, {}

    def install(self):
        if self.batch_size == 1:
            return False
        if not self.installed:
            sdk = self.sdk
            self.originals = sdk._warp_f3d_worker, sdk._decode_f3d_worker, sdk.decode_f3d
            sdk._warp_f3d_worker = self.warp_worker
            sdk._decode_f3d_worker = self.decode_worker
            sdk.decode_f3d = BatchDecoder(sdk.decode_f3d)
            self.installed = True
        return True

    def configure_queues(self):
        # SDK.setup creates queues and idle threads. Call before submitting audio.
        # A queued item now holds up to four frames, so preserve the old frame bound.
        if self.installed:
            target = self.sdk.decode_f3d_queue
            with target.mutex:
                if target.maxsize > 0:
                    target.maxsize = max(1, target.maxsize//self.batch_size)

    def warp_worker(self):
        sdk = self.sdk
        while not sdk.stop_event.is_set():
            items, ended = take_batch(sdk.warp_f3d_queue, sdk.stop_event, self.batch_size)
            if items and not sdk.stop_event.is_set():
                indices = [item[0] for item in items]
                features = np.concatenate([sdk.source_info['f_s_lst'][i] for i in indices])
                source = np.concatenate([item[1] for item in items])
                driving = np.concatenate([item[2] for item in items])
                output = sdk.warp_f3d(features, source, driving)
                if len(output) != len(indices):
                    raise ValueError('Warper returned an incomplete frame batch.')
                size = str(len(items))
                self.warp_batches[size] = self.warp_batches.get(size, 0)+1
                if not put_unless_stopped(sdk.decode_f3d_queue, (indices, output), sdk.stop_event):
                    return
            if ended:
                put_unless_stopped(sdk.decode_f3d_queue, None, sdk.stop_event)
                return

    def decode_worker(self):
        sdk = self.sdk
        while not sdk.stop_event.is_set():
            try:
                item = sdk.decode_f3d_queue.get(timeout=.05)
            except queue.Empty:
                continue
            if item is None:
                put_unless_stopped(sdk.putback_queue, None, sdk.stop_event)
                return
            indices, features = item
            output = sdk.decode_f3d(features)
            if len(output) != len(indices):
                raise ValueError('Decoder returned an incomplete frame batch.')
            size = str(len(indices))
            self.decoder_batches[size] = self.decoder_batches.get(size, 0)+1
            for index, image in zip(indices, output):
                if not put_unless_stopped(sdk.putback_queue, (index, image), sdk.stop_event):
                    return

    def restore(self):
        if self.installed:
            self.sdk._warp_f3d_worker, self.sdk._decode_f3d_worker, self.sdk.decode_f3d = self.originals
            self.installed = False

    def summary(self):
        return dict(renderer_batch=self.batch_size,
                    renderer_batches={'warp': dict(self.warp_batches), 'decoder': dict(self.decoder_batches)})
