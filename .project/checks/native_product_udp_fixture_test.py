import socket,struct,unittest
from native_product_udp_fixture import Fixture,client_records,packet
class Socket:
 def __init__(self):self.sent=[]
 def sendto(self,data,source):self.sent.append((data,source))
class Tests(unittest.TestCase):
 def fixture(self):
  s=Socket();f=Fixture(s);addr=("127.0.0.1",4321)
  hello=b"FNDU\x01\x01\0\0"+bytes(range(1,17))+bytes(40)
  self.assertEqual(f.receive(hello,addr),[])
  challenge=s.sent[-1][0]
  self.assertEqual(challenge[:24],b"FNDU\x01\x02\0\0"+bytes(range(1,17)))
  f.receive(challenge[:5]+b"\x03"+challenge[6:],addr)
  self.assertTrue(f.established);return f,s,addr
 def data(self,f,seq,payload):return b"\x01"+f.identity+struct.pack("<IH",seq,len(payload))+payload
 def test_bootstrap_and_ack(self):
  f,s,a=self.fixture();f.send(b"abc")
  self.assertEqual(s.sent[-1][0],b"\x01"+f.identity+struct.pack("<IH",0,3)+b"abc")
  f.receive(b"\xfe"+f.identity+struct.pack("<I",0),a);self.assertFalse(f.pending)
 def test_identity_before_ack(self):
  f,s,a=self.fixture();f.send(b"abc");n=len(s.sent)
  for payload in [b"\xfe"+bytes(16)+bytes(4),b"\x01"+bytes(16)+struct.pack("<IH",0,1)+b"x"]:
   with self.assertRaises(RuntimeError):f.receive(payload,a)
  self.assertEqual(len(s.sent),n);self.assertIn(0,f.pending)
 def test_ordered_exactly_once(self):
  f,s,a=self.fixture();p=bytes([8])+bytes(8)
  self.assertEqual(f.receive(self.data(f,1,p[4:]),a),[])
  self.assertEqual(f.receive(self.data(f,0,p[:4]),a),[p])
  self.assertEqual(f.receive(self.data(f,0,p[:4]),a),[])
  with self.assertRaises(RuntimeError):f.receive(self.data(f,0,b"xxxx"),a)
 def test_bounds(self):
  f,s,a=self.fixture()
  for data in [self.data(f,64,b"x"),self.data(f,0,b""),self.data(f,0,b"x")+b"x",b"\xfe"+f.identity+struct.pack("<I",0)]:
   with self.assertRaises(RuntimeError):f.receive(data,a)
  with self.assertRaises(RuntimeError):client_records(bytearray(struct.pack("<BIH",2,0,23)))
 def test_fragmented_records(self):
  hello=packet(88,bytes([64])+b"FNAT\x01\0\0"+struct.pack("<HHHI",50,50,2,10000))
  control=packet(90,bytes(58));data=hello+control
  for split in range(len(data)+1):
   b=bytearray(data[:split]);rows=client_records(b);b.extend(data[split:]);rows+=client_records(b)
   self.assertEqual(rows,[hello,control]);self.assertFalse(b)
  for record in [b"\x58X",packet(88,bytes(19)),packet(91,bytes(58))]:
   with self.assertRaises(RuntimeError):client_records(bytearray(record))
if __name__=="__main__":unittest.main()
