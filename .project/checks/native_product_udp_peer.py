"""Independent loopback probe peer for the current native UDP product transport."""
import os,socket,struct,time
import native_product_protocol_probe as wire
class NativeProductUDPPeer(wire.Peer):
    def __init__(self,port):
        super().__init__("udp",port)
        self.identity=None
        self.bootstrap_record=None
    @staticmethod
    def record(data,nonce):
        wire.require(len(data)==64 and data[:5]==b"FNDU\x01" and data[6:8]==b"\0\0",
                     "Malformed native UDP bootstrap record")
        wire.require(data[8:24]==nonce and data[5] in (2,4) and
                     struct.unpack_from("<Q",data,24)[0]>0 and any(data[32:48]),
                     "Mismatched native UDP bootstrap record")
        return data
    def establish(self,deadline):
        nonce=os.urandom(16);wire.require(any(nonce),"Empty native UDP attempt nonce")
        packet=b"FNDU\x01\x01\0\0"+nonce+bytes(40);challenge=None;sent=0.
        while time.monotonic()<deadline:
            if time.monotonic()-sent>=.1:
                self.raw(packet);sent=time.monotonic()
            try:data=self.socket.recv(1201)
            except socket.timeout:continue
            self.record(data,nonce)
            if data[5]==2:
                if challenge is None:
                    challenge=data;packet=data[:5]+b"\x03"+data[6:];sent=0.
                else:wire.require(data==challenge,"Challenge changed within native UDP attempt")
            elif data[5]==4:
                wire.require(challenge is not None and data[6:]==challenge[6:],
                             "Unexpected native UDP establishment")
                self.identity=data[32:48];self.bootstrap_record=data;return
        raise RuntimeError("Native UDP bootstrap deadline")
    def send(self,data):
        wire.require(self.identity is not None and 0<len(data)<=1177,"Native UDP send bounds")
        wire.require(len(self.pending)<64 and (not self.pending or self.tx-min(self.pending)<64),
                     "Native UDP sender window exhausted")
        wire.require(self.tx<0xffffffff,"Native UDP sequence exhausted")
        packet=b"\x01"+self.identity+struct.pack("<IH",self.tx,len(data))+data
        self.pending[self.tx]=(packet,time.monotonic());self.tx+=1;self.raw(packet)
    def pump(self):
        now=time.monotonic()
        for seq,(packet,sent) in list(self.pending.items()):
            if now-sent>=.1:self.raw(packet);self.pending[seq]=(packet,now)
        try:data=self.socket.recv(1201)
        except socket.timeout:return []
        if data.startswith(b"FNDU"):
            wire.require(data==self.bootstrap_record,"Unexpected repeated native UDP establishment")
            return []
        wire.require(self.identity is not None and len(data)>=21 and data[1:17]==self.identity,
                     "Foreign native UDP connection identity")
        seq=struct.unpack_from("<I",data,17)[0]
        if data[0]==254:
            wire.require(len(data)==21 and seq<self.tx,"Invalid native UDP ACK")
            self.pending.pop(seq,None);return []
        wire.require(data[0]==1 and 23<=len(data)<=1200 and
                     struct.unpack_from("<H",data,21)[0]==len(data)-23,"Invalid native UDP data shape")
        wire.require(seq<self.rx+64,"Native UDP receive window exhausted")
        if seq>=self.rx:
            prior=self.ordered.get(seq)
            wire.require(prior is None or prior==data[23:],"Native UDP retransmission changed bytes")
            self.ordered.setdefault(seq,data[23:])
        self.raw(b"\xfe"+self.identity+struct.pack("<I",seq))
        while self.rx in self.ordered:
            self.buffer.extend(self.ordered.pop(self.rx));self.rx+=1
        wire.require(len(self.buffer)<=8192,"Native UDP application buffer exhausted")
        return wire.messages(self.buffer)
    def bootstrap(self,fragment=False):
        wire.require(not fragment,"UDP datagram fragmentation is not a TCP stream test")
        deadline=time.monotonic()+3
        self.establish(deadline)
        self.send(wire.HELLO)
        rows=[]
        while len(rows)<2 and time.monotonic()<deadline:rows+=self.pump()
        wire.require(len(rows)==2 and rows[0]==wire.SESSION and rows[1][0]==7,
                     "Expected current UDP product bootstrap before timeout")
        wire.require(len(rows[1])==5 and struct.unpack_from("<H",rows[1],1)[0]==1,
                     "One slot per tactical probe peer expected")
        return struct.unpack_from("<H",rows[1],3)[0]
