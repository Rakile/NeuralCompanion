// Extract only numerical health and route class, never raw RTC stats/IP/SDP.
export function rtcHealthFields(report: Map<string, any>): Record<string, string | number> {
  const fields: Record<string, string | number> = {};
  let selected = '';
  report.forEach(stat => { if (stat.type === 'transport' && stat.selectedCandidatePairId) selected = stat.selectedCandidatePairId; });
  let received = 0, lost = 0, jitter = 0;
  const finite = (value: unknown) => typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : 0;
  report.forEach(stat => {
    if (stat.type === 'candidate-pair' && (report.get(selected) === stat || (!selected && (stat.selected || (stat.nominated && stat.state === 'succeeded'))))) {
      const local = report.get(stat.localCandidateId), remote = report.get(stat.remoteCandidateId);
      const type = local?.candidateType === 'relay' || remote?.candidateType === 'relay' ? 'relay' : local?.candidateType;
      if (['host','srflx','prflx','relay'].includes(type)) fields.candidate_type = type;
      if (['udp','tcp'].includes(local?.protocol)) fields.protocol = local.protocol;
      fields.rtt_ms = finite(stat.currentRoundTripTime) * 1000;
      fields.received_bytes = finite(stat.bytesReceived); fields.sent_bytes = finite(stat.bytesSent);
    }
    if (stat.type === 'inbound-rtp') {
      received += finite(stat.packetsReceived); lost += finite(stat.packetsLost);
      jitter = Math.max(jitter, finite(stat.jitter)*1000);
    }
  });
  return {...fields, packets_received:received, packets_lost:lost, jitter_ms:jitter};
}
