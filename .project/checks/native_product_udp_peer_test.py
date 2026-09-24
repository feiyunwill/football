import struct,unittest
import native_product_protocol_probe as wire
from native_product_udp_peer import NativeProductUDPPeer
class Socket:
 def __init__(self,rows):self.rows=list(rows);self.sent=[]
 def recv(self,size):return self.rows.pop(0)
 def sendall(self,data):self.sent.append(data)
class PeerTest(unittest.TestCase):
 def peer(self,rows):
  p=NativeProductUDPPeer.__new__(NativeProductUDPPeer);p.identity=bytes(range(1,17));p.socket=Socket(rows)
  p.pending={};p.ordered={};p.buffer=bytearray();p.tx=0;p.rx=0;p.bootstrap_record=None
  return p
 def data(self,seq,payload=b"\x08"+bytes(8),identity=bytes(range(1,17))):
  return b"\1"+identity+struct.pack("<IH",seq,len(payload))+payload
 def test_independent_send_bytes(self):
  p=self.peer([]);p.send(b"abc")
  self.assertEqual(p.socket.sent,[b"\x01"+bytes(range(1,17))+b"\0\0\0\0\x03\0abc"])
 def test_order_and_exactly_once_delivery(self):
  p=self.peer([self.data(1),self.data(0),self.data(0)])
  self.assertEqual(p.pump(),[]);self.assertEqual(p.pump(),[b"\x08"+bytes(8)]*2)
  self.assertEqual(p.pump(),[]);self.assertEqual(p.rx,2)
 def test_foreign_identity_rejected_before_ack(self):
  p=self.peer([self.data(0,identity=bytes(16))])
  with self.assertRaises(RuntimeError):p.pump()
  self.assertFalse(p.socket.sent);self.assertEqual(p.rx,0)
 def test_changed_retransmission_rejected(self):
  p=self.peer([self.data(1),self.data(1,b"\x08"+bytes(7)+b"\1")]);p.pump()
  with self.assertRaises(RuntimeError):p.pump()
 def test_truncated_or_extended_data_rejected(self):
  for data in [self.data(0)[:-1],self.data(0)+b"\0",b"\x01"+bytes(range(1,17))+bytes(4)]:
   p=self.peer([data])
   with self.assertRaises(RuntimeError):p.pump()
   self.assertFalse(p.socket.sent)
 def test_ack_bounds_and_identity(self):
  for identity,seq,suffix in [(bytes(16),0,b""),(bytes(range(1,17)),1,b""),(bytes(range(1,17)),0,b"\0")]:
   p=self.peer([b"\xfe"+identity+struct.pack("<I",seq)+suffix]);p.send(b"x")
   with self.assertRaises(RuntimeError):p.pump()
   self.assertIn(0,p.pending)
 def test_ack_clears_only_matching_sequence(self):
  p=self.peer([b"\xfe"+bytes(range(1,17))+bytes(4)]);p.send(b"x");p.send(b"y");p.pump()
  self.assertNotIn(0,p.pending);self.assertIn(1,p.pending)
 def test_bootstrap_exact_shape_nonce_cookie(self):
  nonce=b"x"*16;good=b"FNDU\1\2\0\0"+nonce+struct.pack("<Q",1)+b"y"*32
  self.assertEqual(NativeProductUDPPeer.record(good,nonce),good)
  for b in [good[:-1],good+b"\0",good[:8]+b"z"*16+good[24:],good[:24]+bytes(40)]:
   with self.assertRaises(RuntimeError):NativeProductUDPPeer.record(b,nonce)
 def test_send_and_receive_windows_bounded(self):
  p=self.peer([self.data(64)])
  with self.assertRaises(RuntimeError):p.pump()
  p=self.peer([])
  for i in range(64):p.send(b"x")
  with self.assertRaises(RuntimeError):p.send(b"x")
if __name__=="__main__":unittest.main()
