import struct,unittest
from native_product_records import records
class RecordsTest(unittest.TestCase):
 def record(self,kind,payload):return bytes([kind])+b"FNRC\1\0\0"+struct.pack("<H",len(payload))+payload
 def test_all_fragment_boundaries_preserve_suffix(self):
  first=self.record(81,bytes(95));tail=struct.pack("<BIH",3,0,3)+bytes(30);whole=first+tail
  for split in range(len(whole)+1):
   pending=bytearray(whole[:split]);out=records(pending);pending.extend(whole[split:]);out+=records(pending)
   self.assertEqual(out,[first,tail]);self.assertFalse(pending)
 def test_malformed_envelope_and_oversized_records_rejected(self):
  for packet in [b"\x51badxxxxx\0\0",self.record(81,bytes(1091))]:
   with self.assertRaises(RuntimeError):records(bytearray(packet))
 def test_roster_bounds(self):
  for count in [0,23,65535]:
   with self.assertRaises(RuntimeError):records(bytearray(struct.pack("<BIH",3,0,count)))
 def test_unknown_kind_is_not_silently_skipped(self):
  for kind in [0,2,19,79,93,255]:
   with self.assertRaises(RuntimeError):records(bytearray([kind]))
 def test_notices_and_hashes_remain_distinct(self):
  packets=[struct.pack("<BHI",10,1,2),struct.pack("<BHI",11,1,2),struct.pack("<BIQ",4,0,42)]
  data=bytearray(b"".join(packets));self.assertEqual(records(data),packets);self.assertFalse(data)
if __name__=="__main__":unittest.main()
