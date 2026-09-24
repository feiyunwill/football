"""Independent bounded loopback UDP fixture for actual native client contracts."""
import os, struct, time
import native_product_protocol_probe as wire

def packet(kind, payload):
    wire.require(80 <= kind <= 92 and len(payload) <= 1090, "Invalid fixture record")
    return bytes([kind])+b"FNRC\x01\0\0"+struct.pack("<H",len(payload))+payload

def client_records(buffer):
    rows=[]
    wire.require(len(buffer)<=8192,"Unbounded fixture application buffer")
    while buffer:
        kind=buffer[0]
        if 80<=kind<=92:
            marker=b"FNRC\x01\0\0"
            wire.require(buffer[1:min(8,len(buffer))]==marker[:max(0,min(7,len(buffer)-1))],
                         "Invalid client recovery marker")
            if len(buffer)<10:break
            payload=struct.unpack_from("<H",buffer,8)[0]
            expected={88:(18,22),89:(58,),90:(58,),85:(70,)}
            wire.require(kind in expected and payload in expected[kind],"Unexpected client recovery record")
            size=10+payload
        elif kind==2:
            if len(buffer)<7:break
            count=struct.unpack_from("<H",buffer,5)[0]
            wire.require(0<count<=22,"Unbounded client input")
            size=7+count*12
        else:
            wire.require(kind==8,"Unexpected client application kind")
            size=9
        if len(buffer)<size:break
        rows.append(bytes(buffer[:size]));del buffer[:size]
    return rows

class Fixture:
    def __init__(self,socket):
        self.socket=socket;self.address=None;self.nonce=None;self.challenge=None
        self.identity=None;self.established=False;self.tx=0;self.rx=0
        self.pending={};self.ordered={};self.recent={};self.buffer=bytearray()
    def raw(self,data):
        self.socket.sendto(data,self.address)
    def send(self,payload):
        wire.require(self.established and 0<len(payload)<=1177,"Invalid fixture payload")
        wire.require(len(self.pending)<64 and self.tx<0xffffffff and
                     (not self.pending or self.tx-min(self.pending)<64),"Fixture send window exhausted")
        data=b"\x01"+self.identity+struct.pack("<IH",self.tx,len(payload))+payload
        self.pending[self.tx]=(data,time.monotonic());self.tx+=1;self.raw(data)
    def retransmit(self):
        now=time.monotonic()
        for seq,(data,sent) in list(self.pending.items()):
            if now-sent>=.1:self.raw(data);self.pending[seq]=(data,now)
    def receive(self,data,source):
        wire.require(len(data)<=1200,"Oversized client datagram")
        if data.startswith(b"FNDU"):
            wire.require(len(data)==64 and data[4]==1 and data[6:8]==b"\0\0","Invalid bootstrap")
            if data[5]==1:
                wire.require(data[24:]==bytes(40) and any(data[8:24]),"Invalid initial hello")
                if self.address is None:
                    self.address=source;self.nonce=data[8:24]
                    self.challenge=b"FNDU\x01\x02\0\0"+self.nonce+struct.pack("<Q",1)+os.urandom(32)
                    self.identity=self.challenge[32:48]
                wire.require(source==self.address and data[8:24]==self.nonce,"Changed bootstrap owner")
                self.raw(self.challenge)
            else:
                wire.require(self.challenge is not None and source==self.address and
                             data==self.challenge[:5]+b"\x03"+self.challenge[6:],"Invalid confirmation")
                self.established=True
                self.raw(self.challenge[:5]+b"\x04"+self.challenge[6:])
            return []
        wire.require(self.established and source==self.address,"Data before established transport")
        wire.require(len(data)>=17 and data[1:17]==self.identity,"Wrong transport identity")
        if data[0]==254:
            wire.require(len(data)==21,"Invalid client ACK")
            seq=struct.unpack_from("<I",data,17)[0]
            wire.require(seq<self.tx,"Client ACK for unsent data")
            self.pending.pop(seq,None);return []
        wire.require(data[0]==1 and len(data)>=23,"Invalid client data")
        seq,length=struct.unpack_from("<IH",data,17)
        wire.require(0<length<=1177 and length==len(data)-23 and seq<0xffffffff,
                     "Invalid client payload length")
        payload=data[23:]
        wire.require(seq<self.rx+64,"Client receive window exceeded")
        if seq in self.recent:wire.require(self.recent[seq]==payload,"Changed delivered client data")
        if seq in self.ordered:wire.require(self.ordered[seq]==payload,"Changed queued client data")
        self.raw(b"\xfe"+self.identity+struct.pack("<I",seq))
        if seq>=self.rx:self.ordered.setdefault(seq,payload)
        while self.rx in self.ordered:
            payload=self.ordered.pop(self.rx);self.recent[self.rx]=payload
            self.buffer.extend(payload);self.rx+=1
            self.recent.pop(self.rx-65,None)
        return client_records(self.buffer)
