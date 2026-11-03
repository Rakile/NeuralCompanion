#include "CaptureRing.h"
#include <stdatomic.h>
#include <stdint.h>
#include <stdlib.h>

struct NCCaptureRing {
    unsigned capacity;
    unsigned channels;
    float *samples;
    atomic_uint write_position;
    atomic_uint read_position;
    atomic_uint overflow;
    atomic_uint discard_request;
    atomic_uint discard_acknowledged;
};

NCCaptureRing *nc_ring_create(unsigned capacity_frames, unsigned channels) {
    if (capacity_frames == 0 || capacity_frames > 96000 || channels == 0 || channels > 2)
        return NULL;
    if ((size_t)capacity_frames > SIZE_MAX / channels / sizeof(float)) return NULL;
    NCCaptureRing *ring = calloc(1, sizeof(*ring));
    if (ring == NULL) return NULL;
    atomic_init(&ring->write_position, 0);
    atomic_init(&ring->read_position, 0);
    atomic_init(&ring->overflow, 0);
    atomic_init(&ring->discard_request, 0);
    atomic_init(&ring->discard_acknowledged, 0);
    if (!atomic_is_lock_free(&ring->write_position) ||
        !atomic_is_lock_free(&ring->read_position) || !atomic_is_lock_free(&ring->overflow) ||
        !atomic_is_lock_free(&ring->discard_request) || !atomic_is_lock_free(&ring->discard_acknowledged)) {
        free(ring);
        return NULL;
    }
    ring->samples = calloc((size_t)capacity_frames * channels, sizeof(float));
    if (ring->samples == NULL) {
        free(ring);
        return NULL;
    }
    ring->capacity = capacity_frames;
    ring->channels = channels;
    return ring;
}

void nc_ring_destroy(NCCaptureRing *ring) {
    if (ring == NULL) return;
    free(ring->samples);
    free(ring);
}

/* Positions wrap at twice capacity, not UINT_MAX: arbitrary capacities remain
 * correct after indefinitely many wraps, with full distinguished from empty. */
static unsigned distance(unsigned write, unsigned read, unsigned modulus) {
    return write >= read ? write - read : modulus - read + write;
}

unsigned nc_ring_write(NCCaptureRing *ring, const float *const *planes, unsigned frames) {
    if (ring == NULL || frames == 0) return 0;
    if (planes == NULL) {
        atomic_store_explicit(&ring->overflow, 1, memory_order_release);
        return 0;
    }
    for (unsigned channel = 0; channel < ring->channels; ++channel) {
        if (planes[channel] == NULL) {
            atomic_store_explicit(&ring->overflow, 1, memory_order_release);
            return 0;
        }
    }
    unsigned discard = atomic_load_explicit(&ring->discard_request, memory_order_acquire);
    if (discard != atomic_load_explicit(&ring->discard_acknowledged, memory_order_relaxed)) {
        /* Earlier writes from this single producer have finished. This callback
         * may also include old audio, so discard it entirely before acknowledging. */
        atomic_store_explicit(&ring->discard_acknowledged, discard, memory_order_release);
        return 0;
    }
    unsigned write = atomic_load_explicit(&ring->write_position, memory_order_relaxed);
    unsigned read = atomic_load_explicit(&ring->read_position, memory_order_acquire);
    unsigned used = distance(write, read, 2 * ring->capacity);
    if (frames > ring->capacity - used) {
        atomic_store_explicit(&ring->overflow, 1, memory_order_release);
        return 0;
    }
    for (unsigned frame = 0; frame < frames; ++frame) {
        unsigned index = (write + frame) % ring->capacity;
        for (unsigned channel = 0; channel < ring->channels; ++channel)
            ring->samples[(size_t)index * ring->channels + channel] = planes[channel][frame];
    }
    atomic_store_explicit(&ring->write_position, (write + frames) % (2 * ring->capacity), memory_order_release);
    return frames;
}

unsigned nc_ring_read(NCCaptureRing *ring, float *interleaved, unsigned max_frames) {
    if (ring == NULL || interleaved == NULL || max_frames == 0) return 0;
    unsigned read = atomic_load_explicit(&ring->read_position, memory_order_relaxed);
    unsigned write = atomic_load_explicit(&ring->write_position, memory_order_acquire);
    unsigned count = distance(write, read, 2 * ring->capacity);
    if (count > max_frames) count = max_frames;
    for (unsigned frame = 0; frame < count; ++frame) {
        unsigned index = (read + frame) % ring->capacity;
        for (unsigned channel = 0; channel < ring->channels; ++channel)
            interleaved[(size_t)frame * ring->channels + channel] = ring->samples[(size_t)index * ring->channels + channel];
    }
    atomic_store_explicit(&ring->read_position, (read + count) % (2 * ring->capacity), memory_order_release);
    return count;
}

unsigned nc_ring_take_overflows(NCCaptureRing *ring) {
    return ring == NULL ? 0 : atomic_exchange_explicit(&ring->overflow, 0, memory_order_acq_rel);
}

unsigned nc_ring_request_discard(NCCaptureRing *ring) {
    return ring == NULL ? 0 : atomic_fetch_add_explicit(&ring->discard_request, 1, memory_order_acq_rel) + 1;
}

unsigned nc_ring_discard_is_acknowledged(NCCaptureRing *ring, unsigned generation) {
    return ring != NULL &&
        atomic_load_explicit(&ring->discard_request, memory_order_acquire) == generation &&
        atomic_load_explicit(&ring->discard_acknowledged, memory_order_acquire) == generation;
}
