"""Bounded independent parser for passive current native product observations."""
import struct
import native_product_protocol_probe as wire
def records(buffer):
    rows=[]
    while buffer:
        kind=buffer[0]
        if 80<=kind<=92:
            if len(buffer)<10:break
            wire.require(buffer[1:8]==b"FNRC\x01\0\0","Invalid native recovery envelope")
            size=10+struct.unpack_from("<H",buffer,8)[0]
            wire.require(size<=1100,"Unbounded native recovery record")
        elif kind in (3,7):
            offset=5 if kind==3 else 1
            if len(buffer)<offset+2:break
            count=struct.unpack_from("<H",buffer,offset)[0]
            wire.require(0<count<=22,"Unbounded native roster")
            size=offset+2+count*(10 if kind==3 else 2)
        else:
            size={66:32,4:13,8:9,10:7,11:7}.get(kind)
            wire.require(size is not None,"Unexpected observed server kind")
        if len(buffer)<size:break
        rows.append(bytes(buffer[:size]));del buffer[:size]
    return rows
