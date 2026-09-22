# 2026-09-10: inherit v5 cadence validation and confirmation from the common match layer.
# """Match v4 on the existing bounded cookie/epoch UDP transport."""
# 2026-09-10: application control epochs are independent of UDP connection epochs.
# """Match v5 on the existing bounded cookie/epoch UDP transport."""
"""Match v6 pause barriers on the bounded cookie/epoch UDP transport."""
from gfootball.frame_sync.client_udp_resume import (
    ResumableFrameSyncUDPClient, ReconnectingFrameSyncUDPClient,
)
from gfootball.frame_sync.match_bootstrap import MatchResumeLimits
from gfootball.frame_sync.multiplayer_transport import (
    MatchClientProtocol, MatchServerRuntime, MatchServer, MatchReconnectingClient,
)
from gfootball.frame_sync.server_udp import UDPServerRuntime


class MatchUDPServerRuntime(UDPServerRuntime, MatchServerRuntime):
  """UDP owns socket IO; MatchServerRuntime owns the application protocol.

  Cooperative super() initializes one common ServerRuntime and one engine.
  The UDP receive/send/close hooks apply to the same peers and budgets.
  """

  def __init__(self, *args, **kwargs):
    self._end_linger_until = None
    super().__init__(*args, **kwargs)

  def finish_settled(self):
    acknowledged = self.finish_acknowledged()
    if not acknowledged:
      return False
    # Keep the UDP receiver available to regenerate a lost transport ACK for
    # the client's final EndAck. The outer match finish deadline still bounds
    # this grace period; this is not a guarantee under unlimited packet loss.
    # 2026-09-10: UDPState caps its adaptive RTO at one second.
    # if not hasattr(self, '_end_linger_until'):
    #   self._end_linger_until = self.loop.time() + min(1.0, self.udp_limits.max_rto)
    if self._end_linger_until is None:
      self._end_linger_until = self.loop.time() + 1.0
    return self.loop.time() >= self._end_linger_until


class MatchUDPServer(MatchServer):
  def __init__(self, *args, udp_limits=None, cookie_limits=None, **kwargs):
    self._udp_limits, self._cookie_limits = udp_limits, cookie_limits
    super().__init__(*args, **kwargs)

  def _make_runtime(self, values, limits, engine_factory):
    return MatchUDPServerRuntime(values, limits, engine_factory,
        udp_limits=self._udp_limits, cookie_limits=self._cookie_limits)


class MatchUDPClient(MatchClientProtocol, ResumableFrameSyncUDPClient):
  _resume_limits_type = MatchResumeLimits

  def _feed(self, chunk, generation):
    # A datagram can be larger than the configured stream buffer. Feed bounded
    # slices to the same parser; complete_delivery still ACKs the whole packet
    # only after every slice was accepted. No unbounded fragment list exists.
    stride = min(4096, self.limits.receive_bytes // 2)
    for offset in range(0, len(chunk), stride):
      super()._feed(chunk[offset:offset + stride], generation)

  def output_pending(self):
    with self._lock:
      # UDP enqueue success alone is insufficient: close must wait for actual
      # ordered-delivery ACKs or report the caller's bounded flush timeout.
      return bool(self._send_queue or (self._channel is not None
                  and self._channel.stats()['pending_packets']))


class MatchReconnectingUDPClient(MatchReconnectingClient):
  _retryable = ReconnectingFrameSyncUDPClient._retryable

  def __init__(self, *args, udp_limits=None, **kwargs):
    self._udp_limits = udp_limits
    super().__init__(*args, **kwargs)

  def _new_client(self):
    return MatchUDPClient(self.host, self.port, self.controlled_slots_callback,
        udp_limits=self._udp_limits, **self._client_options)
