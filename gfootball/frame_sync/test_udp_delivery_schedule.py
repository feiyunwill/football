"""Delivery ACK scheduling, wraparound, retention and unchanged failure budgets."""
import struct
import json
from gfootball.frame_sync.udp_state import UDPState, UDPLimits, MASK
from gfootball.frame_sync.client_buffers import ClientFailure


def test_delivery_ack_window_and_rtt_contract():
  checks=0
  def require(value,message):
   nonlocal checks;checks+=1
   if not value:raise AssertionError(message)
  for start in [0,MASK-31]:
   sender=UDPState(ack_on_delivery=True);receiver=UDPState(ack_on_delivery=True)
   sender.next_send=receiver.next_receive=start
   for i in range(100):require(sender.enqueue(bytes([i]),0)==((start+i)&MASK),"Sequence admission")
   first=sender.due(0,count=256);require(len(first)==64,"Bounded epoch flight")
   for seq,packet in first:sender.mark_sent(seq,0)
   require(sender.due(.001,count=256)==[],"Future packet emitted before ACK progress")
   # An ACK advances one slot without changing queued retention or sequence.
   sender.receive(struct.pack('<BI',255,start),.002)
   require([seq for seq,p in sender.due(.003,count=256)]==[((start+64)&MASK)],"ACK must release one flight slot")
   require(len(sender.pending)==99,"Flight bound must not discard queued payload")
   # Fresh pair: one real missing sequence and ordered delivery across uint32 wrap.
   sender=UDPState(ack_on_delivery=True);receiver=UDPState(ack_on_delivery=True)
   sender.next_send=receiver.next_receive=start;delivered=[];dropped=False
   for i in range(100):sender.enqueue(bytes([i]),0)
   for tick in range(500):
    now=tick*.005
    # 2026-09-22: mirror the real non-awaiting send batch; ACK processing
    # happens after every packet in this due batch has been marked sent.
    packets=sender.due(now)
    for seq,packet in packets:sender.mark_sent(seq,now)
    for seq,packet in packets:
     if seq==((start+3)&MASK) and not dropped:dropped=True;continue
     ack=receiver.receive(packet,now)
     if ack is not None:sender.receive(ack,now)
     while True:
      payload=receiver.next_delivery()
      if payload is None:break
      delivered.append(payload);ack=receiver.complete_delivery()
      if ack is not None:sender.receive(ack,now)
    receiver.check_deadlines(now)
    if not sender.pending:break
   require(delivered==[bytes([i]) for i in range(100)],"Gap recovery changed ordered payload")
   require(sender.pending_bytes==receiver.receive_bytes==0,"Charged bytes leaked")
   require(sender.failure is None and receiver.failure is None,"Unchanged deadlines failed")
  legacy=UDPState()
  for i in range(100):legacy.enqueue(b'x',0)
  require(len(legacy.due(0,count=256))==100,"Legacy admission-ACK scheduling changed")
  state=UDPState(UDPLimits(max_retries=0),ack_on_delivery=True);state.enqueue(b'x',0);state.mark_sent(0,0)
  try:state.due(.141)
  except ClientFailure as e:require(e.reason=="udp_retry_exhausted","Retry limit changed")
  else:raise AssertionError("Original retry exhaustion was waived")
  state=UDPState(ack_on_delivery=True);state.receive(struct.pack('<BIH',0,1,1)+b'x',0)
  try:state.check_deadlines(2)
  except ClientFailure as e:require(e.reason=="udp_gap_timeout","Gap deadline changed")
  else:raise AssertionError("Original2s gap deadline was waived")
  # Delivery ACKs for future packets do not estimate network RTT.
  state=UDPState(ack_on_delivery=True)
  for value in (b'a',b'b',b'c'):state.enqueue(value,0)
  for seq,packet in state.due(0):state.mark_sent(seq,0)
  require(state._rtt_probe==0,"First pending send must be the single RTT probe")
  state.receive(struct.pack('<BI',255,0),.01)
  state.receive(struct.pack('<BI',255,1),.9)
  state.receive(struct.pack('<BI',255,2),1.)
  require(list(state.rtt)==[.01],"Delayed in-order delivery poisoned RTT")
  require(state._rtt_probe is None and state.pending_bytes==0,"Probe was not retired")
  state.enqueue(b'd',1.1);state.mark_sent(3,1.1)
  state.receive(struct.pack('<BI',255,3),1.12)
  require(len(state.rtt)==2 and abs(state.rtt[-1]-.02)<1e-9,"A subsequent head probe did not refresh RTT")
  state.enqueue(b'e',1.2);state.mark_sent(4,1.2);state.mark_sent(4,1.4)
  state.receive(struct.pack('<BI',255,4),1.41)
  require(len(state.rtt)==2 and state._rtt_probe is None,"Retransmission violates Karn's RTT rule")
  state.enqueue(b'f',1.5);state.mark_sent(5,1.5);state.close()
  require(state._rtt_probe is None,"Probe survives terminal close")
  legacy=UDPState()
  legacy.enqueue(b'a',0);legacy.enqueue(b'b',0);legacy.mark_sent(0,0);legacy.mark_sent(1,0)
  legacy.receive(struct.pack('<BI',255,1),.4)
  require(list(legacy.rtt)==[.4],"Legacy admission ACK RTT was changed")
  print(json.dumps(dict(passed=True,assertions=checks,skipped=0,legacy_unchanged=True,deadlines_unchanged=True)))
