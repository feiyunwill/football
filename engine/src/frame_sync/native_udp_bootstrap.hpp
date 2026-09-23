// 2026-09-15: bounded native UDP return-route handshake before reliable channels.
// Application FNRC grants still authenticate seat ownership. This handshake
// does not encrypt traffic or authenticate the server against an on-path peer.
#pragma once
#include "frame_sync/reliable_udp.hpp"
#include "frame_sync/native_recovery_credentials.hpp"
#include <openssl/hmac.h>
#include <limits>
#include <span>
namespace frame_sync {
using NativeUDPAddress = std::array<uint8_t,23>;
using NativeUDPBootstrapPacket = std::array<uint8_t,64>;
enum class NativeUDPBootstrapKind : uint8_t { Hello=1, Challenge=2, Confirm=3, Established=4 };
struct NativeUDPBootstrapRecord {
  NativeUDPBootstrapKind kind=NativeUDPBootstrapKind::Hello;
  ReliableUDPConnection nonce{};
  uint64_t expires=0;
  NativeRecoverySecret cookie{};
  NativeUDPBootstrapRecord()=default;
  ~NativeUDPBootstrapRecord()=default;
  NativeUDPBootstrapRecord(const NativeUDPBootstrapRecord&)=default;
  NativeUDPBootstrapRecord& operator=(const NativeUDPBootstrapRecord&)=default;
  NativeUDPBootstrapRecord(NativeUDPBootstrapRecord&&)=default;
  NativeUDPBootstrapRecord& operator=(NativeUDPBootstrapRecord&&)=default;
};
namespace native_udp_bootstrap {
template<class Bytes> inline bool zero(const Bytes& bytes) {
  return std::all_of(bytes.begin(),bytes.end(),[](uint8_t b){return b==0;});
}
inline void put(uint8_t* out,uint64_t value,size_t n) {
  for(size_t i=0;i<n;++i)out[i]=static_cast<uint8_t>(value>>(8*i));
}
inline uint64_t get(const uint8_t* in,size_t n) {
  uint64_t value=0;for(size_t i=0;i<n;++i)value|=uint64_t(in[i])<<(8*i);return value;
}
inline std::optional<NativeUDPAddress> address(const udp::endpoint& endpoint) {
  if(!endpoint.port() || endpoint.address().is_unspecified())return std::nullopt;
  NativeUDPAddress key{};
  if(endpoint.address().is_v4()) {
    key[0]=4;const auto b=endpoint.address().to_v4().to_bytes();
    std::copy(b.begin(),b.end(),key.begin()+1);
  } else {
    const auto ip=endpoint.address().to_v6();const auto b=ip.to_bytes();
    if(ip.is_v4_mapped()) {
      if(ip.scope_id())return std::nullopt;
      key[0]=4;std::copy(b.begin()+12,b.end(),key.begin()+1);
    } else {
      if(ip.scope_id()>std::numeric_limits<uint32_t>::max())return std::nullopt;
      key[0]=6;std::copy(b.begin(),b.end(),key.begin()+1);
      put(key.data()+17,ip.scope_id(),4);
    }
  }
  if(zero(std::span(key.data()+1,key[0]==4 ? 4u : 16u)))return std::nullopt;
  put(key.data()+21,endpoint.port(),2);return key;
}
inline bool valid_address(const NativeUDPAddress& key) {
  if((key[0]!=4 && key[0]!=6) || get(key.data()+21,2)==0)return false;
  if(zero(std::span(key.data()+1,key[0]==4 ? 4u : 16u)))return false;
  return key[0]!=4 || zero(std::span(key.data()+5,16));
}
inline ReliableUDPConnection connection(const NativeRecoverySecret& cookie) {
  ReliableUDPConnection id{};std::copy_n(cookie.begin(),id.size(),id.begin());return id;
}
inline bool valid(const NativeUDPBootstrapRecord& record) {
  const auto kind=static_cast<uint8_t>(record.kind);
  if(kind<1 || kind>4 || zero(record.nonce))return false;
  if(record.kind==NativeUDPBootstrapKind::Hello)
    return record.expires==0 && zero(record.cookie);
  return record.expires>0 && !zero(connection(record.cookie));
}
inline NativeUDPBootstrapPacket encode(const NativeUDPBootstrapRecord& record) {
  if(!valid(record))throw std::invalid_argument("Invalid native UDP bootstrap record");
  NativeUDPBootstrapPacket bytes{'F','N','D','U',1,static_cast<uint8_t>(record.kind),0,0};
  std::copy(record.nonce.begin(),record.nonce.end(),bytes.begin()+8);
  put(bytes.data()+24,record.expires,8);
  std::copy(record.cookie.begin(),record.cookie.end(),bytes.begin()+32);return bytes;
}
inline std::optional<NativeUDPBootstrapRecord> decode(std::span<const uint8_t> bytes) {
  if(bytes.size()!=64 || bytes[0]!='F' || bytes[1]!='N' || bytes[2]!='D' ||
     bytes[3]!='U' || bytes[4]!=1 || bytes[6]!=0 || bytes[7]!=0)return std::nullopt;
  NativeUDPBootstrapRecord record;record.kind=static_cast<NativeUDPBootstrapKind>(bytes[5]);
  std::copy_n(bytes.begin()+8,16,record.nonce.begin());
  record.expires=get(bytes.data()+24,8);
  std::copy_n(bytes.begin()+32,32,record.cookie.begin());
  return valid(record) ? std::optional(record) : std::nullopt;
}
inline std::optional<ReliableUDPConnection> fresh_nonce(NativeRecoveryCredentials::Entropy entropy=native_entropy) {
  if(!entropy)return std::nullopt;
  ReliableUDPConnection value{};
  for(unsigned i=0;i<4;++i) {
    if(!entropy(value))return std::nullopt;
    if(!zero(value))return value;
  }
  return std::nullopt;
}
} // namespace native_udp_bootstrap

class NativeUDPBootstrapSigner;
class NativeUDPBootstrapLease {
 public:
  NativeUDPBootstrapLease()=delete;
  ~NativeUDPBootstrapLease()=default;
  NativeUDPBootstrapLease(const NativeUDPBootstrapLease&)=default;
  NativeUDPBootstrapLease& operator=(const NativeUDPBootstrapLease&)=default;
  NativeUDPBootstrapLease(NativeUDPBootstrapLease&&)=default;
  NativeUDPBootstrapLease& operator=(NativeUDPBootstrapLease&&)=default;
  const NativeUDPAddress& address() const {return address_;}
  ReliableUDPConnection connection() const {return native_udp_bootstrap::connection(record_.cookie);}
  uint64_t expires() const {return record_.expires;}
  NativeUDPBootstrapPacket reply() const {return native_udp_bootstrap::encode(record_);}
 private:
  friend class NativeUDPBootstrapSigner;
  NativeUDPBootstrapLease(const NativeUDPAddress& addr,NativeUDPBootstrapRecord record)
    :address_(addr),record_(std::move(record)) {record_.kind=NativeUDPBootstrapKind::Established;}
  NativeUDPAddress address_;
  NativeUDPBootstrapRecord record_;
};

class NativeUDPBootstrapSigner {
 public:
  NativeUDPBootstrapSigner()=delete;
  explicit NativeUDPBootstrapSigner(uint64_t lifetime_ms,
      NativeRecoveryCredentials::Entropy entropy=native_entropy):lifetime_(lifetime_ms) {
    if(!lifetime_ || lifetime_>30000 || !entropy)
      throw std::invalid_argument("Invalid native UDP cookie lifetime");
    for(unsigned i=0;i<4;++i) {
      if(!entropy(key_))break;
      if(!native_udp_bootstrap::zero(key_))return;
    }
    clear_native_secret(key_);throw std::runtime_error("Native UDP bootstrap entropy unavailable");
  }
  ~NativeUDPBootstrapSigner(){clear_native_secret(key_);}
  NativeUDPBootstrapSigner(const NativeUDPBootstrapSigner&)=delete;
  NativeUDPBootstrapSigner& operator=(const NativeUDPBootstrapSigner&)=delete;
  NativeUDPBootstrapSigner(NativeUDPBootstrapSigner&&)=delete;
  NativeUDPBootstrapSigner& operator=(NativeUDPBootstrapSigner&&)=delete;
  std::optional<NativeUDPBootstrapPacket> challenge(
      std::span<const uint8_t> hello,const NativeUDPAddress& addr,uint64_t now) const {
    auto request=native_udp_bootstrap::decode(hello);
    if(!request || request->kind!=NativeUDPBootstrapKind::Hello ||
       !native_udp_bootstrap::valid_address(addr) ||
       now>std::numeric_limits<uint64_t>::max()-lifetime_)return std::nullopt;
    request->kind=NativeUDPBootstrapKind::Challenge;request->expires=now+lifetime_;
    auto cookie=sign(addr,request->nonce,request->expires);
    if(!cookie || native_udp_bootstrap::zero(native_udp_bootstrap::connection(*cookie)))
      return std::nullopt;
    request->cookie=*cookie;return native_udp_bootstrap::encode(*request);
  }
  std::optional<NativeUDPBootstrapLease> verify(
      std::span<const uint8_t> confirm,const NativeUDPAddress& addr,uint64_t now) const {
    auto proof=native_udp_bootstrap::decode(confirm);
    if(!proof || proof->kind!=NativeUDPBootstrapKind::Confirm ||
       !native_udp_bootstrap::valid_address(addr) || now>=proof->expires ||
       proof->expires-now>lifetime_)return std::nullopt;
    auto expected=sign(addr,proof->nonce,proof->expires);
    if(!expected || !native_secret_equal(*expected,proof->cookie))return std::nullopt;
    return NativeUDPBootstrapLease(addr,*proof);
  }
 private:
  std::optional<NativeRecoverySecret> sign(
      const NativeUDPAddress& addr,const ReliableUDPConnection& nonce,uint64_t expires) const {
    std::array<uint8_t,55> message{'F','N','D','U',1,'C','K',0};
    std::copy(addr.begin(),addr.end(),message.begin()+8);
    std::copy(nonce.begin(),nonce.end(),message.begin()+31);
    native_udp_bootstrap::put(message.data()+47,expires,8);
    NativeRecoverySecret result{};unsigned count=0;
    if(!HMAC(EVP_sha256(),key_.data(),static_cast<int>(key_.size()),
             message.data(),message.size(),result.data(),&count) || count!=result.size())
      return std::nullopt;
    return result;
  }
  const uint64_t lifetime_;
  NativeRecoverySecret key_{};
};

// The IO owner serializes the registry with its channel table. An index alone
// must never identify a callback: retain and check the endpoint plus connection.
class NativeUDPConnectionRegistry {
 public:
  static constexpr size_t kCapacity=128;
  NativeUDPConnectionRegistry()=delete;
  explicit NativeUDPConnectionRegistry(size_t limit):limit_(limit) {
    if(!limit || limit>kCapacity)throw std::invalid_argument("Invalid native UDP connection cap");
  }
  ~NativeUDPConnectionRegistry()=default;
  NativeUDPConnectionRegistry(const NativeUDPConnectionRegistry&)=delete;
  NativeUDPConnectionRegistry& operator=(const NativeUDPConnectionRegistry&)=delete;
  NativeUDPConnectionRegistry(NativeUDPConnectionRegistry&&)=delete;
  NativeUDPConnectionRegistry& operator=(NativeUDPConnectionRegistry&&)=delete;
  // bool is true for a new channel; duplicates reuse the existing reliable state.
  std::optional<std::pair<size_t,bool>> claim(const NativeUDPBootstrapLease& lease,uint64_t now) {
    if(!advance(now) || now>=lease.expires())return std::nullopt;
    std::optional<size_t> free;
    for(size_t i=0;i<limit_;++i) {
      auto& item=entries_[i];
      if(!item.lease){if(!free)free=i;continue;}
      if(item.lease->address()==lease.address() && item.lease->connection()==lease.connection()) {
        if(item.retired || item.lease->reply()!=lease.reply())return std::nullopt;
        return std::pair{i,false};
      }
    }
    if(!free)return std::nullopt;
    entries_[*free].lease=lease;entries_[*free].retired=false;
    return std::pair{*free,true};
  }
  std::optional<size_t> find(const NativeUDPAddress& addr,const ReliableUDPConnection& id) const {
    for(size_t i=0;i<limit_;++i)
      if(entries_[i].lease && !entries_[i].retired &&
         entries_[i].lease->address()==addr && entries_[i].lease->connection()==id)return i;
    return std::nullopt;
  }
  bool retire(const NativeUDPAddress& addr,const ReliableUDPConnection& id,uint64_t now) {
    if(!advance(now))return false;
    auto index=find(addr,id);if(!index)return false;
    auto& item=entries_[*index];item.retired=true;
    if(now>=item.lease->expires())item.lease.reset();
    return true;
  }
  bool maintain(uint64_t now){return advance(now);}
  size_t active() const {
    size_t n=0;for(size_t i=0;i<limit_;++i)n+=entries_[i].lease.has_value()&&!entries_[i].retired;return n;
  }
  size_t retired() const {
    size_t n=0;for(size_t i=0;i<limit_;++i)n+=entries_[i].lease.has_value()&&entries_[i].retired;return n;
  }
 private:
  struct Entry {
    std::optional<NativeUDPBootstrapLease> lease;
    bool retired=false;
    Entry()=default;~Entry()=default;
    Entry(const Entry&)=default;Entry& operator=(const Entry&)=default;
    Entry(Entry&&)=default;Entry& operator=(Entry&&)=default;
  };
  bool advance(uint64_t now) {
    if(now<last_)return false;last_=now;
    for(size_t i=0;i<limit_;++i)
      if(entries_[i].lease && entries_[i].retired && now>=entries_[i].lease->expires())
        entries_[i].lease.reset();
    return true;
  }
  const size_t limit_;
  uint64_t last_=0;
  std::array<Entry,kCapacity> entries_{};
};

// One attempt owns a fresh nonce and an absolute LOCAL deadline. The server's
// expiry is opaque to this client; machines need not share a clock epoch.
// The caller paces retransmission and creates the channel only on receive()==true.
class NativeUDPBootstrapAttempt {
 public:
  enum class State { AwaitChallenge, AwaitEstablished, Established, Expired };
  NativeUDPBootstrapAttempt()=delete;
  NativeUDPBootstrapAttempt(const NativeUDPAddress& server,uint64_t now,uint64_t timeout_ms,
      NativeRecoveryCredentials::Entropy entropy=native_entropy):server_(server),last_(now) {
    if(!native_udp_bootstrap::valid_address(server) || !timeout_ms || timeout_ms>30000 ||
       now>std::numeric_limits<uint64_t>::max()-timeout_ms)
      throw std::invalid_argument("Invalid native UDP attempt deadline or peer");
    auto nonce=native_udp_bootstrap::fresh_nonce(std::move(entropy));
    if(!nonce)throw std::runtime_error("Native UDP attempt entropy unavailable");
    record_.nonce=*nonce;deadline_=now+timeout_ms;
  }
  ~NativeUDPBootstrapAttempt()=default;
  NativeUDPBootstrapAttempt(const NativeUDPBootstrapAttempt&)=delete;
  NativeUDPBootstrapAttempt& operator=(const NativeUDPBootstrapAttempt&)=delete;
  NativeUDPBootstrapAttempt(NativeUDPBootstrapAttempt&&)=delete;
  NativeUDPBootstrapAttempt& operator=(NativeUDPBootstrapAttempt&&)=delete;
  std::optional<NativeUDPBootstrapPacket> next_packet(uint64_t now) {
    if(!advance(now))return std::nullopt;
    return native_udp_bootstrap::encode(record_);
  }
  // Exactly one successful transition. A repeated Welcome cannot reset sequence
  // numbers, pending sends, RTT, or delivery callbacks in an existing channel.
  bool receive(std::span<const uint8_t> bytes,const NativeUDPAddress& from,uint64_t now) {
    if(!advance(now) || from!=server_)return false;
    auto packet=native_udp_bootstrap::decode(bytes);
    if(!packet || packet->nonce!=record_.nonce)return false;
    if(state_==State::AwaitChallenge && packet->kind==NativeUDPBootstrapKind::Challenge) {
      record_=*packet;record_.kind=NativeUDPBootstrapKind::Confirm;
      state_=State::AwaitEstablished;return false;
    }
    if(state_==State::AwaitEstablished && packet->kind==NativeUDPBootstrapKind::Established &&
       packet->expires==record_.expires && native_secret_equal(packet->cookie,record_.cookie)) {
      state_=State::Established;return true;
    }
    return false;
  }
  std::optional<ReliableUDPConnection> connection() const {
    if(state_!=State::Established)return std::nullopt;
    return native_udp_bootstrap::connection(record_.cookie);
  }
  State state() const {return state_;}
  uint64_t deadline() const {return deadline_;}
 private:
  bool advance(uint64_t now) {
    if(now<last_ || state_==State::Established || state_==State::Expired)return false;
    last_=now;
    if(now>=deadline_){state_=State::Expired;return false;}
    return true;
  }
  const NativeUDPAddress server_;
  uint64_t last_=0;
  uint64_t deadline_=0;
  NativeUDPBootstrapRecord record_;
  State state_=State::AwaitChallenge;
};
} // namespace frame_sync
