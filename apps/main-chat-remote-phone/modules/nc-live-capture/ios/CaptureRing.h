#ifndef NC_CAPTURE_RING_H
#define NC_CAPTURE_RING_H

#ifdef __cplusplus
extern "C" {
#endif

typedef struct NCCaptureRing NCCaptureRing;

/* Single producer/single consumer, noninterleaved Float32 input only.
 * Caller validates negotiated 8-96 kHz mono/stereo format and passes at most
 * one second of input frames as capacity. This rate-independent API enforces
 * the absolute 96,000-frame ceiling and one/two channels.
 * Creation fails when bounds, allocation, or lock-free atomics are unavailable.
 */
NCCaptureRing *nc_ring_create(unsigned capacity_frames, unsigned channels);
/* Only after producer shutdown AND consumer drain. */
void nc_ring_destroy(NCCaptureRing *ring);
/* Complete-block acceptance, or zero with a coalesced overflow flag. */
unsigned nc_ring_write(NCCaptureRing *ring, const float *const *planes, unsigned frames);
/* Consumer owns a separate preallocated max_frames * channels output buffer. */
unsigned nc_ring_read(NCCaptureRing *ring, float *interleaved, unsigned max_frames);
/* Returns 0/1 and clears the flag; consumer must reset segmentation on overflow. */
unsigned nc_ring_take_overflows(NCCaptureRing *ring);
/* Consumer requests a fresh producer boundary without touching producer indices.
 * The single producer drops its next complete callback and acknowledges it.
 * After acknowledgement, the consumer must drain remaining pre-boundary frames
 * before reopening capture. Stale generations never acknowledge a newer request.
 */
unsigned nc_ring_request_discard(NCCaptureRing *ring);
unsigned nc_ring_discard_is_acknowledged(NCCaptureRing *ring, unsigned generation);

#ifdef __cplusplus
}
#endif
#endif
